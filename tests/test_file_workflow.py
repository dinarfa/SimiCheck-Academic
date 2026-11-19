import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pymupdf
from docx import Document

from fileparser import DocumentError, read_document, validate_upload
from openalex import Work
from storage import SourceStore
from workflow import CheckError, CheckSettings, keywords, queries, run_check

PHRASE = ("Kualitas air sungai membaik setelah warga secara rutin menjalankan pengolahan limbah rumah tangga "
          "dengan prosedur pengendapan yang dikembangkan bersama pemerintah daerah. ")
DOCUMENT = PHRASE * 6


class FileValidationTests(unittest.TestCase):
    def test_valid_txt_pdf_and_docx(self):
        self.assertEqual(read_document("uji.txt", DOCUMENT.encode()), DOCUMENT.strip())
        docx = Document()
        docx.add_paragraph(DOCUMENT)
        output = BytesIO()
        docx.save(output)
        self.assertEqual(read_document("uji.docx", output.getvalue()), DOCUMENT.strip())
        with pymupdf.open() as pdf:
            page = pdf.new_page()
            self.assertGreater(page.insert_textbox(pymupdf.Rect(30, 30, 560, 300), DOCUMENT), 0)
            content = pdf.tobytes()
        self.assertIn("Kualitas air sungai", read_document("uji.pdf", content))

    def test_disguised_upload_and_scan(self):
        for filename, content in (("palsu.pdf", b"fake"), ("palsu.docx", b"fake"), ("biner.txt", b"\0")):
            with self.subTest(filename=filename), self.assertRaises(DocumentError):
                validate_upload(filename, content)
        with pymupdf.open() as pdf:
            pdf.new_page()
            content = pdf.tobytes()
        with self.assertRaisesRegex(DocumentError, "OCR"):
            read_document("pindai.pdf", content)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(sandbox.cleanup)
        self.store = SourceStore(local_path=str(Path(sandbox.name) / "sources.sqlite3"))
        self.settings = CheckSettings("OpenAlex otomatis", 10, True, False)
        self.work = Work("W1", "Sumber uji", 2024, "https://doi.org/10.123/test", "cc-by",
                         "https://example.org", True, "https://example.org/paper")
        self.progress = []

    def _run(self, **overrides):
        params = dict(selected=[], api_key="dummy", search_queries=queries("kualitas, sungai"),
                      progress=lambda value, status: self.progress.append(value))
        params.update(overrides)
        return run_check("uji.txt", DOCUMENT, self.settings, self.store, **params)

    def test_empty_library_can_use_openalex_without_persisting_document(self):
        with patch("workflow.search_works", return_value=[self.work, self.work]), \
                patch("workflow.download_full_text", return_value=DOCUMENT) as download:
            analysis = self._run()
        self.assertEqual(analysis.result.percentage, 100)
        self.assertEqual(analysis.result.checked_sources, 1)
        self.assertEqual(analysis.candidates, 1)
        self.assertNotIn("text_content", analysis.sources[0])
        download.assert_called_once()
        self.assertEqual(self.store.list(), [])
        self.assertEqual(self.progress, sorted(self.progress))
        self.assertEqual(self.progress[-1], 1)

    def test_no_sources_does_not_return_a_score(self):
        with patch("workflow.search_works", return_value=[]):
            with self.assertRaisesRegex(CheckError, "Tidak ada sumber"):
                self._run()

    def test_combined_mode_can_finish_when_openalex_fails(self):
        from openalex import OpenAlexError

        local = self.store.add("Lokal", DOCUMENT)
        self.settings = CheckSettings("Gabungan", 10, True, False)
        with patch("workflow.search_works", side_effect=OpenAlexError("OpenAlex belum tersedia.")):
            analysis = self._run(selected=[local])
        self.assertEqual(analysis.result.checked_sources, 1)
        self.assertTrue(any("belum tersedia" in warning for warning in analysis.warnings))

    def test_keywords_exclude_references(self):
        terms = keywords(DOCUMENT + "\nDAFTAR PUSTAKA\nrahasia rahasia rahasia")
        self.assertIn("sungai", terms)
        self.assertNotIn("rahasia", terms)
