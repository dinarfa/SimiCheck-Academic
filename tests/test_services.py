import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from openalex import OpenAlexError, Work, download_full_text, parse_tei, search_works
from storage import SourceStore, StorageError


class StorageTests(unittest.TestCase):
    def test_sqlite_pagination_sorting_filtering_and_id_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SourceStore(local_path=str(Path(tmp) / "sources.db"))
            sid = store.add("Judul 100% lengkap", "teks pertama", "unggahan pengguna")
            other = store.add("OpenAlex", "teks kedua panjang", "OpenAlex full-text")
            self.assertEqual(store.page(limit=1, query="100%", origin="Unggahan")[0]["id"], sid)
            self.assertEqual(store.page(limit=1, sort="Jumlah kata")[0]["id"], other)
            self.assertEqual(store.page(limit=1, offset=1, sort="Jumlah kata")[0]["id"], sid)
            self.assertEqual([row["id"] for row in store.get_selected([other, sid, other])], [other, sid])
            store.add("Duplikat", "teks pertama")
            self.assertEqual(len(store.list()), 2)
            self.assertEqual(store.get_selected([sid])[0]["title"], "Judul 100% lengkap")

    def test_supabase_secret_uses_apikey_and_limits_metadata(self):
        store = SourceStore("https://example.supabase.co", "sb_secret_dummy")
        with patch("storage.requests.request") as request:
            response = request.return_value.__enter__.return_value
            response.status_code = 200
            response.content = b"[]"
            response.json.return_value = []
            result = store.page(limit=9, offset=16, query="judul", sort="Nama")
        self.assertEqual(result, [])
        args = request.call_args.kwargs
        self.assertEqual(args["params"]["limit"], 9)
        self.assertEqual(args["params"]["offset"], 16)
        self.assertNotIn("text_content", args["params"]["select"])
        self.assertIn("apikey", args["headers"])
        self.assertNotIn("Authorization", args["headers"])

    def test_supabase_errors_discard_response_body(self):
        store = SourceStore("https://example.supabase.co", "sb_secret_dummy")
        with patch("storage.requests.request") as request:
            response = request.return_value.__enter__.return_value
            response.status_code = 401
            response.text = "SIMULATED_SECRET"
            with self.assertRaises(StorageError) as caught:
                store.list()
        self.assertNotIn("SIMULATED_SECRET", str(caught.exception))


class OpenAlexTests(unittest.TestCase):
    def setUp(self):
        self.work = Work("W123", "Artikel", 2024, "", "cc-by", "https://example.org", True, "https://example.org/text")
        self.body = "Kalimat dengan teks lengkap yang bisa diproses. " * 20

    def test_search_retains_work_with_explicit_location_license(self):
        item = {
            "id": "https://openalex.org/W123", "display_name": "Artikel",
            "best_oa_location": {"license": "cc-by", "is_oa": True, "landing_page_url": self.work.location_url},
            "content_urls": {"grobid_xml": "https://content.openalex.org/works/W123.grobid-xml"},
        }
        unsafe = {**item, "best_oa_location": {"license": "cc-by-nc", "is_oa": True}}
        with patch("openalex._get", return_value=json.dumps({"results": [unsafe, item]}).encode()) as get:
            works = search_works("uji", "dummy", full_text_only=True)
        self.assertEqual([work.id for work in works], ["W123"])
        self.assertTrue(works[0].has_full_text)
        self.assertIn("has_content.grobid_xml:true", get.call_args.args[2]["filter"])

    def test_xml_variants_and_conflicting_license(self):
        for body in (f"<TEI><text><body><p>{self.body}</p></body></text></TEI>",
                     f"<html><body><tei><text><div><p>{self.body}</p></div></text></tei></body></html>"):
            self.assertEqual(parse_tei(body.encode(), self.work), self.body.strip())
        conflict = (f'<TEI><licence target="https://creativecommons.org/licenses/by-nc/4.0/"/>'
                    f"<text><body><p>{self.body}</p></body></text></TEI>")
        with self.assertRaisesRegex(OpenAlexError, "Lisensi"):
            parse_tei(conflict.encode(), self.work)

    def test_unknown_license_rejected_before_network(self):
        bad = Work("W123", "Artikel", 2024, "", "", "https://example.org", True, "https://example.org/text")
        with patch("openalex._get") as get, self.assertRaises(OpenAlexError):
            download_full_text(bad, "dummy")
        get.assert_not_called()

    def test_timeout_cleans_request_error(self):
        with patch("openalex.requests.get", side_effect=requests.Timeout("SIMULATED_SECRET")), \
                patch("openalex.sleep"), patch("openalex._reserve"):
            with self.assertRaises(OpenAlexError) as caught:
                search_works("uji", "dummy")
        self.assertNotIn("SIMULATED_SECRET", str(caught.exception))
