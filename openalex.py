"""Penelusuran kandidat dan ekstraksi full-text berlisensi dari OpenAlex."""

import json
import re
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import BoundedSemaphore, Lock
from time import monotonic, sleep
from urllib.parse import urlsplit

import requests
from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException
from xml.etree.ElementTree import ParseError

API = "https://api.openalex.org/works"
CONTENT = "https://content.openalex.org/works/{}.grobid-xml"
WORK_ID = re.compile(r"W\d+")
LICENSE = re.compile(r"cc-by(?:-sa)?(?:-[1-4]\.0)?|cc0(?:-1\.0)?|public-domain")
MAX_XML_BYTES = 5 * 1024 * 1024
MAX_ARTICLE_CHARS = 300_000
MAX_METADATA_BYTES = 2 * 1024 * 1024
_DOWNLOAD_SLOTS = BoundedSemaphore(2)
_LOCK = Lock()
_CACHE = OrderedDict()
_DAILY = {"date": None, "search": 0, "download": 0}
_CAPS = {"search": 150, "download": 75}


class OpenAlexError(RuntimeError):
    """Pesan layanan yang aman ditampilkan pada pengguna."""


@dataclass(frozen=True)
class Work:
    id: str
    title: str
    year: int | str
    doi: str
    license: str
    source_url: str
    has_full_text: bool
    location_url: str = ""
    version: str = ""
    authors: tuple[str, ...] = ()

    def as_source(self, text: str) -> dict:
        return {
            "id": self.id, "title": self.title, "doi": self.doi, "license": self.license,
            "source_url": self.source_url, "origin": "OpenAlex full-text", "text_content": text,
            "authors": self.authors, "version": self.version, "location_url": self.location_url,
        }


def _license(value: object) -> str:
    raw = str(value or "").strip().lower()
    return raw if LICENSE.fullmatch(raw) else ""


def licensed(record: dict) -> bool:
    loc = record.get("best_oa_location") or {}
    return bool(_license(loc.get("license")))


def _record(item: dict) -> Work | None:
    loc = item.get("best_oa_location") or {}
    work = str(item.get("id") or "").rsplit("/", 1)[-1]
    if not WORK_ID.fullmatch(work) or not licensed(item) or loc.get("is_oa") is not True:
        return None
    expected = CONTENT.format(work)
    has_xml = (item.get("content_urls") or {}).get("grobid_xml") == expected
    doi = item.get("doi") or ""
    location_url = loc.get("landing_page_url") or loc.get("pdf_url") or ""
    return Work(
        work, item.get("display_name") or "Tanpa judul", item.get("publication_year") or "",
        doi, _license(loc.get("license")), doi or location_url or f"https://openalex.org/{work}",
        has_xml, location_url, loc.get("version") or "",
        tuple(a["author"]["display_name"] for a in item.get("authorships", [])
              if (a.get("author") or {}).get("display_name")),
    )


def _reserve(kind: str) -> None:
    today = datetime.now(timezone.utc).date()
    with _LOCK:
        if _DAILY["date"] != today:
            _DAILY.update(date=today, search=0, download=0)
        if _DAILY[kind] >= _CAPS[kind]:
            raise OpenAlexError("Batas penggunaan OpenAlex aplikasi tercapai hari ini.")
        _DAILY[kind] += 1


def _body(response: requests.Response, limit: int, deadline: float) -> bytes:
    data = bytearray()
    for part in response.iter_content(chunk_size=65_536):
        if monotonic() >= deadline:
            raise OpenAlexError("Waktu pemrosesan OpenAlex habis.")
        if len(data) + len(part) > limit:
            raise OpenAlexError("Respons OpenAlex terlalu besar untuk diproses.")
        data.extend(part)
    return bytes(data)


def _get(url: str, key: str, params: dict, *, kind: str, limit: int, deadline: float) -> bytes:
    if not key:
        raise OpenAlexError("OpenAlex belum dikonfigurasi. Hubungi pengelola aplikasi.")
    if not _DOWNLOAD_SLOTS.acquire(blocking=False):
        raise OpenAlexError("OpenAlex sedang dipakai. Coba kembali sebentar lagi.")
    try:
        for attempt in range(2):
            remaining = deadline - monotonic()
            if remaining <= 0:
                break
            _reserve(kind)
            wait = 0.5 * 2 ** attempt
            try:
                with requests.get(
                    url, params=params, headers={"Authorization": f"Bearer {key}"},
                    timeout=(min(3, remaining), min(5, remaining)), stream=True,
                ) as response:
                    if response.ok:
                        return _body(response, limit, deadline)
                    code = response.status_code
                    if code not in (429, 502, 503, 504):
                        raise OpenAlexError(f"OpenAlex tidak dapat memenuhi permintaan (HTTP {code}).")
                    if code == 429:
                        budget = response.headers.get("X-RateLimit-Remaining")
                        if budget == "0":
                            raise OpenAlexError("Kuota harian OpenAlex habis.")
                        retry_after = response.headers.get("Retry-After", "")
                        if retry_after.isdecimal():
                            wait = max(wait, int(retry_after))
            except requests.RequestException:
                pass
            if attempt == 0 and monotonic() + wait < deadline:
                sleep(wait)
            else:
                break
        raise OpenAlexError("OpenAlex sedang sibuk atau tidak dapat dihubungi. Coba kembali.")
    finally:
        _DOWNLOAD_SLOTS.release()


def search_works(query: str, api_key: str, limit: int = 15, *,
                 full_text_only: bool = False, deadline: float | None = None) -> list[Work]:
    filters = "is_oa:true"
    if full_text_only:
        filters += ",has_content.grobid_xml:true"
    raw = _get(
        API, api_key, {
            "search": query[:240], "per_page": max(1, min(int(limit), 30)), "filter": filters,
            "select": "id,display_name,publication_year,doi,best_oa_location,content_urls,authorships",
        },
        kind="search", limit=MAX_METADATA_BYTES, deadline=deadline or monotonic() + 10,
    )
    try:
        return [work for item in json.loads(raw)["results"] if (work := _record(item)) is not None]
    except (ValueError, TypeError, KeyError, AttributeError):
        raise OpenAlexError("Format hasil pencarian OpenAlex tidak dapat dibaca.") from None


def _tag(node) -> str:
    return node.tag.rsplit("}", 1)[-1].lower()


def parse_tei(raw: bytes, work: Work) -> str:
    """Baca isi TEI standar dan versi lama yang dibungkus HTML."""
    try:
        root = SafeET.fromstring(raw)
    except (ParseError, DefusedXmlException):
        raise OpenAlexError("Berkas XML artikel tidak dapat dibaca.") from None
    tei = next((node for node in root.iter() if _tag(node) == "tei"), None)
    if tei is None:
        raise OpenAlexError("Format artikel bukan TEI.")
    for node in tei.iter():
        if _tag(node) not in ("licence", "license"):
            continue
        url = node.get("target") or ""
        try:
            parts = urlsplit(url) if url else None
        except ValueError:
            raise OpenAlexError("Identitas lisensi di XML tidak valid.") from None
        if parts and parts.hostname in ("creativecommons.org", "www.creativecommons.org"):
            path = parts.path.strip("/").split("/")
            declared = ("cc-" + "-".join(path[1:3]) if path[:1] == ["licenses"] else
                        "cc0-1.0" if path[:2] == ["publicdomain", "zero"] else
                        "public-domain" if path[:2] == ["publicdomain", "mark"] else "")
            # Informasi eksplisit dari file tidak boleh bertentangan dengan metadata.
            normalize = lambda label: re.sub(r"-[1-4]\.0$", "", label)
            if not _license(declared) or normalize(declared) != normalize(work.license):
                raise OpenAlexError("Lisensi di artikel tidak sesuai dengan metadata OpenAlex.")
    text = next((node for node in tei if _tag(node) == "text"), None)
    if text is None:
        raise OpenAlexError("Isi artikel tidak tersedia.")
    body = next((node for node in text if _tag(node) == "body"), text)
    paragraphs = []
    length = 0
    pending = [body]
    while pending:
        node = pending.pop()
        tag = _tag(node)
        if tag in {"back", "listbibl", "bibl", "figure", "table"}:
            continue
        if tag in {"p", "head"}:
            value = " ".join("".join(node.itertext()).split())
            if value:
                length += len(value) + 1
                if length > MAX_ARTICLE_CHARS:
                    raise OpenAlexError("Teks artikel melebihi batas pemeriksaan.")
                paragraphs.append(value)
        else:
            pending.extend(reversed(list(node)))
    combined = "\n".join(paragraphs)
    if len(combined.split(maxsplit=100)) < 100:
        raise OpenAlexError("Isi artikel terlalu pendek untuk dibandingkan.")
    return combined


def download_full_text(work: Work, api_key: str, *, deadline: float | None = None) -> str:
    if (not WORK_ID.fullmatch(work.id) or not _license(work.license)
            or not work.has_full_text or not work.location_url):
        raise OpenAlexError("Artikel belum memiliki lisensi, lokasi, dan XML yang dapat diverifikasi.")
    with _LOCK:
        cached = _CACHE.get(work)
        if cached and cached[0] > monotonic():
            _CACHE.move_to_end(work)
            return cached[1]
    raw = _get(
        CONTENT.format(work.id), api_key, {}, kind="download",
        limit=MAX_XML_BYTES, deadline=deadline or monotonic() + 12,
    )
    text = parse_tei(raw, work)
    with _LOCK:
        _CACHE[work] = (monotonic() + 1800, text)
        _CACHE.move_to_end(work)
        while len(_CACHE) > 16:
            _CACHE.popitem(last=False)
    return text
