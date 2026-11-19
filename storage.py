"""Persistent Supabase REST storage, with a local SQLite developer fallback."""
import hashlib
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
import requests

SCHEMA = '''CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, origin TEXT NOT NULL,
    doi TEXT, license TEXT, source_url TEXT,
    text_content TEXT NOT NULL, word_count INTEGER NOT NULL,
    created_at TEXT NOT NULL
)'''


class SourceStore:
    def __init__(self, url='', key='', local_path='local_sources.sqlite3'):
        self.url = url.rstrip('/')
        self.key = key
        self.local_path = local_path
        self.remote = bool(url and key)
        if not self.remote:
            with sqlite3.connect(self.local_path) as db:
                db.execute(SCHEMA)

    def _request(self, method, path, **kwargs):
        headers = {
            'apikey': self.key,
            'Content-Type': 'application/json',
            'Prefer': 'resolution=merge-duplicates,return=representation',
        }
        if not self.key.startswith('sb_secret_'):
            headers['Authorization'] = f'Bearer {self.key}'  # legacy service_role key only
        r = requests.request(method, f'{self.url}/rest/v1/sources{path}',
                             headers=headers, timeout=30, **kwargs)
        if r.status_code >= 400:
            raise RuntimeError(f'Supabase HTTP {r.status_code}: {r.text[:300]}')
        return r.json() if r.content else []

    @staticmethod
    def make_id(text):
        return hashlib.sha256(text.encode('utf8')).hexdigest()[:32]

    def add(self, title, text, origin='upload', doi='', license='', source_url=''):
        row = {'id': self.make_id(text), 'title': title[:300], 'origin': origin,
               'doi': doi or '', 'license': license or '', 'source_url': source_url or '',
               'text_content': text, 'word_count': len(text.split()),
               'created_at': datetime.now(timezone.utc).isoformat()}
        if self.remote:
            self._request('POST', '?on_conflict=id', json=row)
        else:
            with sqlite3.connect(self.local_path) as db:
                db.execute('''INSERT INTO sources (id,title,origin,doi,license,source_url,text_content,word_count,created_at)
                     VALUES (:id,:title,:origin,:doi,:license,:source_url,:text_content,:word_count,:created_at)
                     ON CONFLICT(id) DO UPDATE SET title=excluded.title, source_url=excluded.source_url''', row)
        return row['id']

    def list(self, include_text=False, limit=300):
        fields = '*' if include_text else 'id,title,origin,doi,license,source_url,word_count,created_at'
        if self.remote:
            return self._request('GET', f'?select={fields}&order=created_at.desc&limit={int(limit)}')
        with sqlite3.connect(self.local_path) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(f'SELECT {fields} FROM sources ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
        return [dict(r) for r in rows]

    def delete(self, sid):
        if self.remote:
            self._request('DELETE', f'?id=eq.{sid}')
        else:
            with sqlite3.connect(self.local_path) as db:
                db.execute('DELETE FROM sources WHERE id = ?', (sid,))
