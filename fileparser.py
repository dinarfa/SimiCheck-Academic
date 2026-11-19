"""Extract text from text-based PDFs, DOCX and TXT (no OCR)."""
import io
import fitz
from docx import Document

MAX_FILE_BYTES = 15 * 1024 * 1024
MAX_TEXT_CHARS = 2_000_000


def read_document(filename: str, content: bytes) -> str:
    if not content:
        raise ValueError('File kosong.')
    if len(content) > MAX_FILE_BYTES:
        raise ValueError('File lebih besar dari 15 MB. Kompres atau bagi file dulu.')
    lower = filename.lower()
    if lower.endswith('.pdf'):
        with fitz.open(stream=content, filetype='pdf') as doc:
            if len(doc) > 400:
                raise ValueError('PDF lebih dari 400 halaman, bagi terlebih dahulu.')
            text = '\n'.join(page.get_text('text', sort=True) for page in doc)
    elif lower.endswith('.docx'):
        d = Document(io.BytesIO(content))
        text = '\n'.join(p.text for p in d.paragraphs)
        # Also read tables, often used in Indonesian academic proposals.
        text += '\n' + '\n'.join(cell.text for table in d.tables for row in table.rows for cell in row.cells)
    elif lower.endswith('.txt'):
        text = content.decode('utf-8-sig', errors='replace')
    else:
        raise ValueError('Gunakan file PDF, DOCX, atau TXT.')
    text = text[:MAX_TEXT_CHARS].strip()
    if len(text.split()) < 30:
        raise ValueError('Teks tidak terbaca atau terlalu pendek. PDF scan perlu OCR terlebih dahulu.')
    return text
