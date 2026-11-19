"""Alur pemeriksaan yang dapat dipakai tanpa Streamlit."""

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from threading import BoundedSemaphore
from time import monotonic
from zoneinfo import ZoneInfo

from engine import Result, allowed_words, analyze, tokenize
from openalex import OpenAlexError, download_full_text, search_works
from semantic import SemanticError, SemanticResult, find_paraphrases
from storage import SourceStore

MAX_DOCUMENT_WORDS = 40_000
MAX_LOCAL_SOURCES = 12
MAX_SOURCE_WORDS = 250_000
MAX_SOURCE_CHARS = 2_000_000
MAX_DOWNLOADS = 3
TOKENS = re.compile(r"[^\W\d_]{4,}", re.UNICODE)
STOP_WORDS = frozenset("""
akan agar atau bagi bahwa dalam dari dengan dapat hasil hanya ini itu jadi juga karena
lebih maka masih oleh pada para pernah sebagai serta telah tentang tersebut tidak untuk yang
anda penelitian peneliti kajian analisis metode dokumen halaman pendahuluan abstrak jurnal
this that about also after before between have from with where when which while their them
these those will were would could should there study studies research results analysis using used
""".split())
CHECK_SLOT = BoundedSemaphore(1)


@dataclass(frozen=True)
class CheckSettings:
    mode: str
    minimum: int
    bibliography: bool
    quotes: bool
    semantic: bool = False


@dataclass
class Analysis:
    filename: str
    document: str
    result: Result
    sources: list[dict]
    settings: CheckSettings
    analyzed_at: datetime
    warnings: list[str]
    candidates: int
    semantic: SemanticResult | None = None


class CheckError(ValueError):
    """Pemeriksaan tidak dapat menghasilkan skor yang valid."""


def keywords(document: str, *, bibliography: bool = True, quotes: bool = True) -> str:
    """Buat kueri kata kunci singkat yang dapat ditinjau sebelum dikirim."""
    tokens = tokenize(document)
    valid = allowed_words(document, tokens, bibliography, quotes)
    counter = Counter(
        token.value for token, include in zip(tokens[:5000], valid[:5000])
        if include and TOKENS.fullmatch(token.value) and token.value not in STOP_WORDS
    )
    return ", ".join(word for word, _ in counter.most_common(9))


def queries(edited: str) -> list[str]:
    terms = list(dict.fromkeys(
        word.casefold() for word in TOKENS.findall(edited[:180])
        if word.casefold() not in STOP_WORDS
    ))[:9]
    return [" OR ".join(group) for start in range(0, len(terms), 3)
            if (group := terms[start:start + 3])]


def _doi(source: dict) -> str:
    return str(source.get("doi") or "").lower().removeprefix("https://doi.org/").strip()


def run_check(filename: str, document: str, settings: CheckSettings, store: SourceStore, *,
              selected: list[str], api_key: str, search_queries: list[str],
              progress: Callable[[float, str], None]) -> Analysis:
    """Carilah sumber, jalankan engine, lalu sisakan metadata yang diperlukan laporan."""
    if not CHECK_SLOT.acquire(blocking=False):
        raise CheckError("Pemeriksaan lain sedang berjalan. Coba lagi setelah selesai.")
    try:
        return _check(filename, document, settings, store, selected, api_key, search_queries, progress)
    finally:
        CHECK_SLOT.release()


def _check(filename, document, settings, store, selected, api_key, search_queries, progress) -> Analysis:
    deadline = monotonic() + 45
    tokens = tokenize(document)
    if len(tokens) > MAX_DOCUMENT_WORDS:
        raise CheckError("Dokumen melebihi 40.000 token. Bagi dokumen sebelum diperiksa.")
    if sum(allowed_words(document, tokens, settings.bibliography, settings.quotes)) < settings.minimum:
        raise CheckError("Kata yang tersisa setelah pengecualian terlalu sedikit untuk diperiksa.")
    progress(0.10, f"Teks dokumen terbaca ? {len(tokens):,} token")
    warnings = []
    sources = []
    words = 0
    chars = 0
    if settings.mode in ("Koleksi sumber", "Gabungan"):
        if not selected or len(selected) > MAX_LOCAL_SOURCES:
            raise CheckError("Pilih antara 1 dan 12 sumber dari koleksi.")
        for offset in range(0, len(selected), 3):
            if monotonic() >= deadline:
                warnings.append("Sebagian sumber koleksi belum diambil karena batas waktu.")
                break
            try:
                batch = store.get_selected(selected[offset:offset + 3])
            except Exception:
                warnings.append("Sebagian sumber koleksi belum dapat dimuat.")
                break
            if len(batch) != len(selected[offset:offset + 3]):
                warnings.append("Beberapa sumber terpilih sudah tidak tersedia di koleksi.")
            for source in batch:
                size = len(source["text_content"])
                if words + source["word_count"] > MAX_SOURCE_WORDS or chars + size > MAX_SOURCE_CHARS:
                    warnings.append("Beberapa sumber koleksi dilewati karena batas teks pemeriksaan.")
                    continue
                words += source["word_count"]
                chars += size
                sources.append(source)

    found = {}
    if settings.mode in ("OpenAlex otomatis", "Gabungan"):
        if not search_queries:
            raise CheckError("Masukkan kata kunci yang disetujui untuk penelusuran OpenAlex.")
        progress(0.20, "Mencari artikel open-access di OpenAlex")
        for query in search_queries[:3]:
            try:
                for work in search_works(query, api_key, 15, full_text_only=True, deadline=min(deadline, monotonic() + 8)):
                    found.setdefault(work.id, work)
            except OpenAlexError as exc:
                warnings.append(str(exc))
                break
        do_attempt = 0
        dois = {_doi(source) for source in sources} - {""}
        for work in found.values():
            doi = _doi({"doi": work.doi})
            if doi and doi in dois:
                continue
            if do_attempt >= MAX_DOWNLOADS:
                warnings.append("Sebagian kandidat OpenAlex belum diperiksa karena batas unduhan.")
                break
            do_attempt += 1
            progress(0.25 + 0.09 * do_attempt, f"Mengambil artikel OpenAlex ? percobaan {do_attempt}/{MAX_DOWNLOADS}")
            try:
                text = download_full_text(work, api_key, deadline=min(deadline, monotonic() + 8))
            except OpenAlexError as exc:
                warnings.append(str(exc))
                continue
            more_words = len(text.split())
            if words + more_words > MAX_SOURCE_WORDS or chars + len(text) > MAX_SOURCE_CHARS:
                warnings.append("Beberapa kandidat OpenAlex dilewati karena batas teks pemeriksaan.")
                continue
            words += more_words
            chars += len(text)
            sources.append(work.as_source(text))
            if doi:
                dois.add(doi)
        if not found:
            warnings.append("OpenAlex tidak menemukan kandidat dengan XML dan lisensi yang memenuhi syarat.")

    if not sources:
        detail = " " + " ".join(dict.fromkeys(warnings)) if warnings else ""
        raise CheckError("Tidak ada sumber yang berhasil disiapkan untuk dibandingkan." + detail)
    progress(0.55, f"Menyiapkan pencocokan untuk {len(sources)} sumber")
    result = analyze(
        document, sources, settings.minimum, settings.bibliography, settings.quotes,
        max_index_words=MAX_SOURCE_WORDS, deadline=deadline,
        progress=lambda count: progress(0.55 + 0.40 * count / len(sources),
                                       f"{count} dari {len(sources)} sumber dibandingkan"),
    )
    if not result.checked_sources:
        raise CheckError("Tidak ada sumber dengan teks yang cukup panjang untuk dibandingkan.")
    if result.checked_sources < len(sources):
        warnings.append("Beberapa sumber memiliki teks yang terlalu pendek untuk ambang yang dipilih.")
    semantic = None
    if settings.semantic:
        progress(0.96, "Meninjau kemungkinan parafrase")
        try:
            semantic = find_paraphrases(
                document, result, sources, bibliography=settings.bibliography,
                quotes=settings.quotes, deadline=monotonic() + 50,
            )
        except SemanticError as exc:
            warnings.append(str(exc))
    metadata = [{key: value for key, value in item.items() if key != "text_content"} for item in sources]
    progress(1.0, f"Pemeriksaan selesai ? {result.checked_sources} sumber dibandingkan")
    return Analysis(filename, document, result, metadata, settings,
                    datetime.now(ZoneInfo("Asia/Makassar")), list(dict.fromkeys(warnings)), len(found), semantic)
