import unittest
from time import monotonic
from unittest.mock import patch

import numpy as np

from engine import analyze
from semantic import _compatible, find_paraphrases


class SemanticTests(unittest.TestCase):
    def test_opposite_claim_and_numeric_conflict(self):
        self.assertFalse(_compatible("Curah hujan meningkat.", "Curah hujan menurun."))
        self.assertFalse(_compatible("Tingkat kesalahan menjadi 25 persen.", "Tingkat kesalahan menjadi 50 persen."))
        self.assertTrue(_compatible("Risiko banjir makin tinggi.", "Kemungkinan banjir semakin tinggi."))

    def test_indications_exclude_direct_text_and_bibliography(self):
        exact = "Transparansi data penelitian dapat ditingkatkan dengan publikasi metode dan prosedur pengukuran yang lengkap."
        original = "Saat terjadi badai, peluang suatu daerah mengalami genangan menjadi lebih besar."
        paraphrase = "Daerah itu lebih rentan dilanda banjir ketika cuaca ekstrem terjadi."
        document = exact + "\n" + paraphrase + "\nDAFTAR PUSTAKA\n" + original
        source = {"id": "S1", "title": "Sumber uji", "text_content": exact + "\n" + original}
        result = analyze(document, [source], min_match_words=10)
        with patch("semantic._embed",
                   return_value=np.array([[1, 0], [0, 1], [1, 0]], dtype=np.float32)):
            found = find_paraphrases(document, result, [source], bibliography=True, quotes=False,
                                     deadline=monotonic() + 5)
        self.assertEqual(found.document_segments, 1)
        self.assertEqual(len(found.matches), 1)
        self.assertEqual(found.matches[0].document.text, paraphrase.rstrip("."))
        self.assertEqual(result.covered_words, len(exact.split()))
