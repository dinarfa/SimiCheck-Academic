import unittest
from engine import analyze


class SimilarityTests(unittest.TestCase):
    def setUp(self):
        self.phrase = 'analisis data hasil penelitian dengan metode yang transparan dan dapat direproduksi oleh peneliti lainnya'
        self.source = {'id': '1', 'title': 'Jurnal Uji', 'text_content': 'Pembuka: ' + self.phrase + '. Penutup.'}

    def test_identical_phrase(self):
        r = analyze('Pendahuluan. ' + self.phrase + '. Kesimpulan.', [self.source], min_match_words=10)
        self.assertGreater(r.percentage, 60)
        self.assertEqual(r.source_words.get('1'), len(self.phrase.split()))

    def test_irrelevant_text(self):
        r = analyze('saya suka menulis di pagi hari pada akhir pekan bersama teman', [self.source])
        self.assertEqual(r.percentage, 0)

    def test_bibliography_excluded(self):
        r = analyze('Tulisan orisinal singkat.\nDAFTAR PUSTAKA\n' + self.phrase,
                    [self.source], exclude_bibliography=True)
        self.assertEqual(r.percentage, 0)

    def test_quotation_excluded(self):
        r = analyze('Penelitian menjelaskan “' + self.phrase + '” sebagai kutipan langsung.',
                    [self.source], exclude_quotes=True)
        self.assertEqual(r.percentage, 0)

    def test_repeated_phrase_does_not_hide_exact_source(self):
        tokens = "alpha beta gamma delta epsilon zeta eta theta".split()
        fragment = " ".join(tokens)
        windows = [" ".join(tokens[index:index + 5]) for index in range(len(tokens) - 4)]
        boilerplate = " pemisah ".join(window for window in windows for _ in range(15))
        sources = [
            {"id": "a", "title": "A", "text_content": boilerplate},
            {"id": "b", "title": "B", "text_content": fragment},
        ]
        for corpus in (sources, list(reversed(sources))):
            with self.subTest(first=corpus[0]["id"]):
                result = analyze(fragment, corpus, min_match_words=5)
                self.assertEqual(result.covered_words, 8)
                self.assertEqual(result.source_words, {"b": 8})

    def test_no_double_count(self):
        r = analyze(self.phrase, [self.source, {**self.source, 'id': '2'}])
        self.assertEqual(r.covered_words, r.eligible_words)
        self.assertEqual(sum(r.source_words.values()), r.covered_words)


if __name__ == '__main__':
    unittest.main()
