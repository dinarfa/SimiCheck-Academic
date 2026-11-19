"""Transparent word-coverage similarity engine; NOT Turnitin's proprietary score."""
from __future__ import annotations
from dataclasses import dataclass
from collections.abc import Callable
from time import monotonic
from collections import defaultdict
import re

WORD = re.compile(r"[^\W_]+", re.UNICODE)
REFERENCES = re.compile(r"(?im)^\s*(?:DAFTAR\s+PUSTAKA|REFERENCES|BIBLIOGRAPHY|DAFTAR\s+REFERENSI)\s*$")
QUOTATIONS = re.compile(r'“[^”]*”|«[^»]*»|"[^"\n]*"', re.S)

@dataclass
class Token:
    value: str
    start: int
    end: int

@dataclass
class Match:
    source_id: str
    source_title: str
    doc_start: int
    doc_end: int
    source_start: int
    source_end: int
    length: int
    doc_excerpt: str
    source_excerpt: str

@dataclass
class Result:
    percentage: float
    covered_words: int
    eligible_words: int
    tokens: list[Token]
    attribution: list[str | None]
    matches: list[Match]
    source_words: dict[str, int]
    checked_sources: int = 0


def tokenize(text: str) -> list[Token]:
    return [Token(m.group().casefold(), m.start(), m.end()) for m in WORD.finditer(text)]


def allowed_words(text: str, tokens: list[Token], exclude_bibliography=True, exclude_quotes=False) -> list[bool]:
    cutoff = len(text)
    if exclude_bibliography:
        match = REFERENCES.search(text)
        if match:
            cutoff = match.start()
    quote_spans = []
    if exclude_quotes:
        quote_spans = [(q.start(), q.end()) for q in QUOTATIONS.finditer(text)]
    result = []
    q = 0
    for t in tokens:
        while q < len(quote_spans) and quote_spans[q][1] <= t.start:
            q += 1
        in_quote = q < len(quote_spans) and t.start < quote_spans[q][1] and t.end > quote_spans[q][0]
        result.append(t.start < cutoff and not in_quote)
    return result


class AnalysisLimit(ValueError):
    """Batas komputasi yang aman dilaporkan kepada pengguna."""


def analyze(document: str, sources: list[dict], min_match_words=10,
            exclude_bibliography=True, exclude_quotes=False, max_index_words=250_000,
            *, progress: Callable[[int], None] | None = None, deadline: float | None = None) -> Result:
    """Cocokkan N-gram dokumen dan perluas segmen pada tiap sumber."""
    size = max(5, int(min_match_words))
    doc = tokenize(document)
    allowed = allowed_words(document, doc, exclude_bibliography, exclude_quotes)
    values = [token.value for token in doc]
    attribution: list[str | None] = [None] * len(doc)
    eligible = sum(allowed)
    if eligible < size:
        return Result(0, 0, eligible, doc, attribution, [], {})

    seeds = defaultdict(list)
    span = 0
    for end, valid in enumerate(allowed):
        span = span + 1 if valid else 0
        if span >= size:
            start = end - size + 1
            seeds[tuple(values[start:end + 1])].append(start)

    ranges = {}
    total = checked = comparisons = extensions = 0
    for source in sorted(sources, key=lambda row: str(row["id"])):
        text = source.get("text_content") or ""
        tokens = tokenize(text)
        if len(tokens) < size:
            continue
        total += len(tokens)
        if total > max_index_words:
            raise AnalysisLimit("Teks sumber terlalu besar. Kurangi sumber yang dipilih.")
        source_values = [token.value for token in tokens]
        if source_values == values and all(allowed):
            ranges.setdefault((0, len(doc)), (source, tokens, 0))
            checked += 1
            if progress:
                progress(checked)
            continue
        end_on_diagonal = {}
        for source_start in range(len(tokens) - size + 1):
            if source_start % 256 == 0 and deadline is not None and monotonic() >= deadline:
                raise AnalysisLimit("Pencocokan melewati batas waktu. Kurangi ukuran dokumen atau sumber.")
            key = tuple(source_values[source_start:source_start + size])
            starts = seeds.get(key, ())
            comparisons += len(starts)
            if comparisons > 2_000_000:
                raise AnalysisLimit("Terlalu banyak frasa berulang. Bagi dokumen atau kurangi jumlah sumber.")
            for left in starts:
                diagonal = left - source_start
                if end_on_diagonal.get(diagonal, 0) >= left + size:
                    continue
                right = left + size
                source_right = source_start + size
                while (right < len(doc) and source_right < len(tokens) and allowed[right]
                       and values[right] == source_values[source_right]):
                    right += 1
                    source_right += 1
                    extensions += 1
                    if extensions > 5_000_000:
                        raise AnalysisLimit("Teks berulang melebihi batas pekerjaan. Bagi dokumen menjadi beberapa bagian.")
                end_on_diagonal[diagonal] = right
                span_key = (left, right)
                if span_key not in ranges:
                    ranges[span_key] = (source, tokens, source_start)
                    if len(ranges) > 40_000:
                        raise AnalysisLimit("Terlalu banyak kecocokan pendek. Naikkan minimum kata cocok.")
        checked += 1
        if progress:
            progress(checked)

    matches = []
    source_words = defaultdict(int)
    covered = 0
    ordered = sorted(ranges, key=lambda key: (key[0] - key[1], key[0]))
    for index, (left, right) in enumerate(ordered):
        if covered == eligible:
            break
        if index % 128 == 0 and deadline is not None and monotonic() >= deadline:
            raise AnalysisLimit("Pencocokan melewati batas waktu. Kurangi ukuran dokumen atau sumber.")
        source, tokens, source_start = ranges[left, right]
        sid = str(source["id"])
        cursor = left
        while cursor < right:
            if attribution[cursor] is not None:
                cursor += 1
                continue
            end = cursor + 1
            while end < right and attribution[end] is None:
                end += 1
            if end - cursor >= size:
                sl = source_start + cursor - left
                sr = sl + end - cursor
                attribution[cursor:end] = [sid] * (end - cursor)
                source_words[sid] += end - cursor
                covered += end - cursor
                matches.append(Match(
                    sid, source["title"], cursor, end, sl, sr, end - cursor,
                    document[doc[cursor].start:doc[end - 1].end][:500],
                    source["text_content"][tokens[sl].start:tokens[sr - 1].end][:500],
                ))
            cursor = end

    matches.sort(key=lambda match: (-match.length, match.doc_start))
    return Result(100 * covered / eligible if eligible else 0, covered, eligible,
                  doc, attribution, matches, dict(source_words), checked)
