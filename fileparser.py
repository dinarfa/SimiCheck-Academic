"""Validasi dan ekstraksi PDF berbasis teks, DOCX, serta TXT."""

import io
import re
from pathlib import Path
from zipfile import BadZipFile, ZipFile

import pymupdf
from docx import Document
from lxml.etree import XMLSyntaxError

MAX_FILE_BYTES = 15 * 1024 * 1024
MAX_TEXT_CHARS = 2_000_000
MAX_PDF_PAGES = 400
MAX_DOCX_EXPANDED = 64 * 1024 * 1024
SUPPORTED_TYPES = ("pdf", "docx", "txt")
pymupdf.TOOLS.mupdf_display_errors(False)
pymupdf.TOOLS.mupdf_display_warnings(False)


class DocumentError(ValueError):
    """Kesalahan file dengan pesan yang aman untuk ditampilkan."""


def _text_file(content: bytes) -> str:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise DocumentError("Simpan file TXT dengan encoding UTF-8.") from None
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", text):
        raise DocumentError("Isi file tidak sesuai dengan format TXT.")
    return text


def validate_upload(filename: str, content: bytes) -> str:
    """Periksa ukuran dan struktur dasar sebelum mengekstrak isi file."""
    if not content:
        raise DocumentError("File kosong.")
    if len(content) > MAX_FILE_BYTES:
        raise DocumentError("Ukuran file melebihi 15 MB.")
    kind = Path(filename).suffix.lower().lstrip(".")
    if kind == "pdf":
        if not re.search(rb"%PDF-\d\.\d", content[:1024]):
            raise DocumentError("Isi file tidak sesuai dengan format PDF.")
    elif kind == "docx":
        try:
            with ZipFile(io.BytesIO(content)) as archive:
                entries = archive.infolist()
                if len(entries) > 2048 or sum(entry.file_size for entry in entries) > MAX_DOCX_EXPANDED:
                    raise DocumentError("Ukuran DOCX setelah dibuka terlalu besar.")
                if not {"[Content_Types].xml", "word/document.xml"}.issubset(archive.namelist()):
                    raise DocumentError("Isi file tidak sesuai dengan format DOCX.")
        except BadZipFile:
            raise DocumentError("DOCX rusak atau formatnya tidak sesuai.") from None
    elif kind == "txt":
        _text_file(content)
    else:
        raise DocumentError("Format yang didukung adalah PDF, DOCX, dan TXT.")
    return kind


def _join_limited(parts) -> str:
    collected = []
    length = 0
    for part in parts:
        length += len(part) + 1
        if length > MAX_TEXT_CHARS:
            raise DocumentError("Teks terlalu panjang. Bagi dokumen sebelum mengunggah.")
        collected.append(part)
    return "\n".join(collected)


def _docx_parts(doc):
    yield from (p.text for p in doc.paragraphs)
    for table in doc.tables:
        for row in table.rows:
            yield from (cell.text for cell in row.cells)


def read_document(filename: str, content: bytes) -> str:
    """Ekstrak hingga dua juta karakter dengan batas halaman PDF."""
    kind = validate_upload(filename, content)
    try:
        if kind == "pdf":
            with pymupdf.open(stream=content, filetype="pdf") as pdf:
                if pdf.needs_pass:
                    raise DocumentError("Buka proteksi kata sandi PDF sebelum mengunggah.")
                if len(pdf) > MAX_PDF_PAGES:
                    raise DocumentError("PDF melebihi 400 halaman. Bagi dokumen agar dapat diproses.")
                text = _join_limited(page.get_text("text", sort=True) for page in pdf)
        elif kind == "docx":
            text = _join_limited(_docx_parts(Document(io.BytesIO(content))))
        else:
            text = _text_file(content)
            if len(text) > MAX_TEXT_CHARS:
                raise DocumentError("Teks terlalu panjang. Bagi dokumen sebelum mengunggah.")
    except (pymupdf.FileDataError, BadZipFile, KeyError, RuntimeError, ValueError, XMLSyntaxError) as exc:
        if isinstance(exc, DocumentError):
            raise
        raise DocumentError("File rusak atau isi file tidak dapat dibaca.") from None
    text = text.strip()
    if len(text.split(maxsplit=30)) < 30:
        if kind == "pdf":
            raise DocumentError("Teks PDF tidak cukup untuk diperiksa. PDF hasil pindai memerlukan OCR.")
        raise DocumentError("Dokumen perlu memuat minimal 30 kata yang dapat dibaca.")
    return text
