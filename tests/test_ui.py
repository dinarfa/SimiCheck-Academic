import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest

from storage import SourceStore

DOCUMENT = ("Kajian ini mengukur perubahan kualitas air sungai melalui pengambilan sampel "
            "dan analisis laboratorium yang dilakukan secara konsisten selama satu tahun. ") * 4


def _button(view, label):
    return next(button for button in view.button if button.label == label)


def _route(view, path):
    # AppTest.switch_page supports file-based routes. This app registers callables.
    view._page_hash = next(page_hash for page_hash, info in view._registered_pages.items()
                           if info.get("url_pathname") == path)
    return view.run()


class StreamlitFlowTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = SourceStore(local_path=str(Path(folder.name) / "sources.db"))

    def test_login_batch_upload_check_report_and_clear(self):
        with patch.object(st, "secrets", {"APP_PASSWORD": "secret-for-test"}), \
                patch("storage.SourceStore", return_value=self.store) as create_store:
            view = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=10).run()
            self.assertFalse(view.exception)
            create_store.assert_not_called()
            view.text_input[0].set_value("incorrect")
            _button(view, "Masuk").click().run()
            self.assertIn("salah", view.error[0].value)
            create_store.assert_not_called()

            view.text_input[0].set_value("secret-for-test")
            _button(view, "Masuk").click().run()
            self.assertFalse(view.exception)
            self.assertEqual(view.title[0].value, "SimiCheck Academic")

            _route(view, "koleksi")
            view.file_uploader[0].set_value([
                ("sumber.txt", DOCUMENT.encode(), "text/plain"),
                ("duplikat.txt", DOCUMENT.encode(), "text/plain"),
                ("palsu.pdf", b"file rusak", "application/pdf"),
                ("pendek.txt", b"Terlalu pendek", "text/plain"),
            ]).run()
            view.checkbox[0].check()
            _button(view, "Konfirmasi dan impor").click().run()
            self.assertFalse(view.exception)
            self.assertEqual(len(self.store.list()), 1)
            self.assertEqual([item["Tersedia"] for item in view.session_state["import_results"]], [True, False])

            _route(view, "periksa")
            view.file_uploader[0].set_value(("proposal.txt", DOCUMENT.encode(), "text/plain")).run()
            _button(view, "Baca dokumen").click().run()
            view.multiselect[0].set_value([self.store.list()[0]["id"]]).run()
            _button(view, "Mulai pemeriksaan").click().run()
            self.assertFalse(view.exception)
            self.assertEqual(view.session_state["analysis"].result.percentage, 100)
            self.assertEqual(len(self.store.list()), 1)

            _route(view, "laporan")
            self.assertFalse(view.exception)
            self.assertEqual(view.metric[0].value, "100.0%")
            self.assertEqual(len(view.get("download_button")), 4)

            _route(view, "pengaturan")
            _button(view, "Hapus dokumen dan laporan dari sesi").click().run()
            self.assertNotIn("analysis", view.session_state)
            self.assertNotIn("prepared_document", view.session_state)
            view.sidebar.button[0].click().run()
            self.assertNotIn("authenticated", view.session_state)
            self.assertFalse(view.exception)
