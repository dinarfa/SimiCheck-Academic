import csv
import io
import json
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

import pymupdf

from engine import analyze
from pdf_report import make_pdf
from report import Report, make_csv, make_html, make_json
from semantic import Segment, SemanticMatch, SemanticResult
from workflow import Analysis, CheckSettings

PHRASES = [
    "Sejumlah mahasiswa meninjau keterbacaan tabel akademik bersama pembimbing sebelum menyerahkan laporan akhir.",
    "Pemerintah daerah memantau kebersihan air sungai secara rutin selama musim kemarau panjang.",
    "Peneliti merekam data kelembapan tanah untuk menilai efektivitas teknik penyiraman otomatis.",
]


def sample_report(document, sources, semantic=None):
    analysis = Analysis("<Makassar>.txt", document, analyze(document, sources), sources,
                        CheckSettings("Koleksi sumber", 10, False, False),
                        datetime(2026, 11, 19, 12, 0, tzinfo=ZoneInfo("Asia/Makassar")), [], 0, semantic)
    return Report(analysis)


class ReportExportsTest(unittest.TestCase):
    def test_all_formats_multiple_sources_and_long_unicode_document(self):
        sources = [
            {"id": str(index), "title": "=HYPERLINK " + ("Judul penelitian sangat panjang " * 15),
             "text_content": phrase, "doi": f"10.1234/{index}", "license": "cc-by"}
            for index, phrase in enumerate(PHRASES)
        ]
        document = "Catatan na?f dan caf?.\n" + "\n".join(
            f"Bagian {index} ? {PHRASES[index % 3]}" for index in range(110)
        )
        report = sample_report(document, sources)
        summary = json.loads(make_json(report))["summary"]
        self.assertEqual(summary["matched_sources"], 3)
        self.assertEqual(summary["checked_sources"], 3)
        output = list(csv.reader(io.StringIO(make_csv(report).decode("utf-8-sig"))))
        self.assertEqual(len(output), 4)
        self.assertTrue(output[1][1].startswith("'="))
        html = make_html(report)
        self.assertIn(b"&lt;Makassar&gt;", html)
        self.assertIn(b"<mark ", html)
        self.assertIn(b"https://doi.org/10.1234/0", html)
        with pymupdf.open(stream=make_pdf(report), filetype="pdf") as pdf:
            self.assertGreater(len(pdf), 3)
            for page in pdf:
                self.assertAlmostEqual(page.rect.width, 595.28, places=1)
                self.assertIn("Halaman", page.get_text())
                self.assertGreater(len(page.get_text()), 25)
            self.assertTrue(any("na?f" in page.get_text() for page in pdf))
            self.assertTrue(any(page.get_links() for page in pdf))

    def test_valid_zero_and_no_evidence(self):
        document = "Dokumen menguji perubahan topik yang berbeda serta hanya menggunakan data simulasi."
        report = sample_report(document, [dict(id="1", title="Jurnal", text_content=PHRASES[0])])
        self.assertEqual(report.summary["text_similarity_percent"], 0)
        self.assertEqual(report.evidence, [])
        self.assertEqual(report.summary["checked_sources"], 1)
        with pymupdf.open(stream=make_pdf(report), filetype="pdf") as pdf:
            self.assertEqual(len(pdf), 2)
            self.assertIn("0.0%", pdf[0].get_text())

    def test_semantic_only_does_not_increase_direct_percentage(self):
        text = "Curah hujan tinggi menyebabkan risiko banjir meningkat di sekitar sungai."
        source = dict(id="1", title="Jurnal", text_content=PHRASES[0])
        match = SemanticMatch(Segment(0, len(text), 10, text), Segment(0, 20, 10, PHRASES[0], "1", "Jurnal"), .91)
        report = sample_report(text, [source], SemanticResult([match], 1, 1, 1))
        data = json.loads(make_json(report))
        self.assertEqual(data["summary"]["text_similarity_percent"], 0)
        self.assertEqual(data["semantic"]["matched_words"], 10)
        self.assertIn(b"Indikasi parafrase", make_html(report))
