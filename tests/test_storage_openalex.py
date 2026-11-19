import os
import tempfile
import unittest
from storage import SourceStore
from openalex import licensed


class StorageAndLicensingTests(unittest.TestCase):
    def test_sqlite_persistence(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, 'mydata.sqlite3')
            a = SourceStore(local_path=path)
            sid = a.add('Penelitian A', 'Isi artikel sebagai contoh penelitian ilmiah '*25)
            b = SourceStore(local_path=path)
            rows = b.list(include_text=True)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['id'], sid)
            b.delete(sid)
            self.assertEqual(b.list(), [])

    def test_open_access_is_not_always_reusable(self):
        def row(l):
            return {'best_oa_location': {'license': l}}
        self.assertTrue(licensed(row('cc-by')))
        self.assertTrue(licensed(row('cc-by-4.0')))
        self.assertTrue(licensed(row('cc-by-sa-4.0')))
        self.assertFalse(licensed(row('cc-by-nc')))
        self.assertFalse(licensed(row('cc-by-nc-nd')))
        self.assertFalse(licensed(row(None)))
        self.assertFalse(licensed({}))


if __name__ == '__main__':
    unittest.main()
