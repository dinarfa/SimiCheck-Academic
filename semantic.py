"""Pencocokan parafrase opsional, dengan inferensi ONNX di server aplikasi."""

import hashlib
import re
from bisect import bisect_left
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import monotonic

import requests

from engine import Result, allowed_words, tokenize

MODEL = "https://huggingface.co/Xenova/multilingual-e5-small/resolve/761b726dd34fb83930e26aab4e9ac3899aa1fa78/"
ASSETS = (
    ("tokenizer.json", "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39", 25_000_000),
    ("onnx/model_quantized.onnx", "f80102d3f2a1229f387d3c81909990d8945513e347b0eab049f7de3c6f98c193", 125_000_000),
)
BOUNDARY = re.compile(r"(?<=[.!?])\s+|\n+")
MAX_DOC_SEGMENTS = 64
MAX_SOURCE_SEGMENTS = 120
THRESHOLD = 0.86
POLARITY = (
    (
        frozenset("naik menaikkan meningkat peningkatan naiknya increased increases rose higher".split()),
        frozenset("turun menurunkan menurun penurunan berkurang decreased decreases fell lower".split()),
    ),
    (
        frozenset("membuang dihapus menghapus removed removing discarded excludes excluded".split()),
        frozenset("mempertahankan dipertahankan retained retaining kept keeps included includes".split()),
    ),
)
NUMBERS = re.compile(r"(?<!\w)\d+(?:[.,]\d+)?(?!\w)")


class SemanticError(RuntimeError):
    """Mode semantik belum menghasilkan temuan yang valid."""


@dataclass(frozen=True)
class Segment:
    start: int
    end: int
    words: int
    text: str
    source_id: str = ""
    source_title: str = ""


@dataclass(frozen=True)
class SemanticMatch:
    document: Segment
    source: Segment
    similarity: float


@dataclass(frozen=True)
class SemanticResult:
    matches: list[SemanticMatch]
    document_segments: int
    eligible_segments: int
    source_segments: int

    @property
    def covered_words(self) -> int:
        return sum(match.document.words for match in self.matches)


def _asset(relative: str, checksum: str, limit: int, deadline: float) -> Path:
    target = Path(".simicheck-models") / Path(relative).name
    if target.is_file() and target.stat().st_size <= limit:
        with target.open("rb") as file:
            if hashlib.file_digest(file, "sha256").hexdigest() == checksum:
                return target
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    length = 0
    pending = None
    try:
        with NamedTemporaryFile(dir=target.parent, delete=False) as file:
            pending = Path(file.name)
            with requests.get(MODEL + relative, timeout=(4, 8), stream=True) as response:
                response.raise_for_status()
                for chunk in response.iter_content(chunk_size=256 * 1024):
                    length += len(chunk)
                    if length > limit or monotonic() >= deadline:
                        raise SemanticError("Aset semantik melewati batas ukuran atau waktu.")
                    digest.update(chunk)
                    file.write(chunk)
        if digest.hexdigest() != checksum:
            raise SemanticError("Validasi aset semantik gagal.")
        pending.replace(target)
    except (requests.RequestException, OSError):
        raise SemanticError("Model semantik belum dapat disiapkan. Coba kembali.") from None
    finally:
        if pending:
            pending.unlink(missing_ok=True)
    return target


@lru_cache(maxsize=1)
def _load_cached() -> tuple:
    import onnxruntime as ort
    from tokenizers import Tokenizer

    deadline = monotonic() + 35
    tokenizer_path, model_path = (_asset(*item, deadline) for item in ASSETS)
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    tokenizer.enable_truncation(max_length=128)
    tokenizer.enable_padding(pad_id=tokenizer.token_to_id("<pad>"), pad_token="<pad>")
    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.enable_cpu_mem_arena = False
    options.add_session_config_entry("session.disable_prepacking", "1")
    options.log_severity_level = 4
    session = ort.InferenceSession(str(model_path), sess_options=options, providers=["CPUExecutionProvider"])
    return tokenizer, session


def _embed(texts: list[str], deadline: float):
    import numpy as np

    try:
        tokenizer, session = _load_cached()
        features = []
        for start in range(0, len(texts), 8):
            if monotonic() >= deadline:
                raise SemanticError("Pencocokan semantik melewati batas waktu.")
            batch = tokenizer.encode_batch(["query: " + text for text in texts[start:start + 8]])
            feeds = {
                "input_ids": np.array([row.ids for row in batch], dtype=np.int64),
                "attention_mask": np.array([row.attention_mask for row in batch], dtype=np.int64),
                "token_type_ids": np.array([row.type_ids for row in batch], dtype=np.int64),
            }
            values = session.run(None, {item.name: feeds[item.name] for item in session.get_inputs()})[0]
            mask = feeds["attention_mask"][:, :, None]
            averaged = (values * mask).sum(1) / np.maximum(mask.sum(1), 1)
            features.extend(averaged / np.maximum(np.linalg.norm(averaged, axis=1, keepdims=True), 1e-12))
        return np.asarray(features, dtype=np.float32)
    except SemanticError:
        raise
    except Exception:
        raise SemanticError("Model semantik belum dapat dijalankan pada server ini.") from None


def _segments(text, tokens, excluded, *, sid="", title=""):
    offsets = [token.start for token in tokens]
    cut_points = [0, *(match.end() for match in BOUNDARY.finditer(text)), len(text)]
    for start, stop in zip(cut_points, cut_points[1:]):
        left, right = bisect_left(offsets, start), bisect_left(offsets, stop)
        for index in range(left, right, 65):
            end = min(index + 65, right)
            if end - index < 8 or any(excluded[index:end]):
                continue
            first, last = tokens[index].start, tokens[end - 1].end
            yield Segment(first, last, end - index, text[first:last][:480], sid, title)


def _sample(parts: list[Segment], max_count: int) -> list[Segment]:
    if len(parts) <= max_count:
        return parts
    if max_count == 1:
        return parts[:1]
    return [parts[i * (len(parts) - 1) // (max_count - 1)] for i in range(max_count)]


def _compatible(first: str, second: str) -> bool:
    words_first = set(re.findall(r"\w+", first.casefold()))
    words_second = set(re.findall(r"\w+", second.casefold()))
    for positive, negative in POLARITY:
        first_goes_up = bool(words_first & positive and not words_first & negative)
        first_goes_down = bool(words_first & negative and not words_first & positive)
        second_goes_up = bool(words_second & positive and not words_second & negative)
        second_goes_down = bool(words_second & negative and not words_second & positive)
        if (first_goes_up and second_goes_down) or (first_goes_down and second_goes_up):
            return False
    numbers_first, numbers_second = set(NUMBERS.findall(first)), set(NUMBERS.findall(second))
    return not (numbers_first and numbers_second and numbers_first.isdisjoint(numbers_second))


def find_paraphrases(document: str, result: Result, sources: list[dict], *,
                     bibliography: bool, quotes: bool, deadline: float) -> SemanticResult:
    """Cari pasangan semantik pada bagian yang belum memiliki atribusi langsung."""
    valid = allowed_words(document, result.tokens, bibliography, quotes)
    excluded = [not ok or attr is not None for ok, attr in zip(valid, result.attribution)]
    eligible = list(_segments(document, result.tokens, excluded))
    doc_parts = _sample(eligible, MAX_DOC_SEGMENTS)
    if not doc_parts:
        return SemanticResult([], 0, len(eligible), 0)
    source_parts = []
    per_source = max(1, MAX_SOURCE_SEGMENTS // len(sources))
    for source in sources:
        text = source["text_content"]
        tokens = tokenize(text)
        valid = allowed_words(text, tokens)
        parts = _segments(text, tokens, [not value for value in valid], sid=source["id"], title=source["title"])
        source_parts.extend(_sample(list(parts), per_source))
    if not source_parts:
        return SemanticResult([], 0, len(eligible), 0)
    vectors = _embed([item.text for item in doc_parts + source_parts], deadline)
    similarity = vectors[:len(doc_parts)] @ vectors[len(doc_parts):].T
    matches = []
    for index, part in enumerate(doc_parts):
        best = max(
            (position for position, source in enumerate(source_parts)
             if 0.45 <= source.words / part.words <= 2.2 and _compatible(part.text, source.text)),
            key=lambda position: similarity[index, position], default=None,
        )
        if best is not None and similarity[index, best] >= THRESHOLD:
            matches.append(SemanticMatch(part, source_parts[best], min(1.0, float(similarity[index, best]))))
    return SemanticResult(matches, len(doc_parts), len(eligible), len(source_parts))


if __name__ == "__main__":
    _load_cached()
    print("Model semantik siap untuk pengujian lokal.")
