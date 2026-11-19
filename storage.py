"""Koleksi sumber di Supabase REST atau SQLite lokal."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from urllib.parse import urlsplit
from contextlib import closing
from datetime import datetime, timezone

import requests

SCHEMA = """CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, origin TEXT NOT NULL,
    doi TEXT, license TEXT, source_url TEXT, text_content TEXT NOT NULL,
    word_count INTEGER NOT NULL, created_at TEXT NOT NULL
)"""
META = "id,title,origin,doi,license,source_url,word_count,created_at"
SORTS = {
    "Terbaru": ("created_at.desc,id.asc", "created_at DESC, id ASC"),
    "Terlama": ("created_at.asc,id.asc", "created_at ASC, id ASC"),
    "Nama": ("title.asc,id.asc", "title ASC, id ASC"),
    "Jumlah kata": ("word_count.desc,id.asc", "word_count DESC, id ASC"),
}
SOURCE_ID = re.compile(r"[0-9a-f]{32}")


class StorageError(RuntimeError):
    """Kesalahan penyimpanan yang tidak menyertakan respons atau kredensial."""


class SourceStore:
    def __init__(self, url: str = "", key: str = "", local_path: str = "local_sources.sqlite3"):
        if bool(url) != bool(key):
            raise StorageError("Konfigurasi penyimpanan belum lengkap.")
        if url:
            try:
                parts = urlsplit(url)
                if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
                    raise ValueError
            except ValueError:
                raise StorageError("URL Supabase harus memakai HTTPS.") from None
        self.url = url.rstrip("/")
        self.key = key
        self.local_path = local_path
        self.remote = bool(url)
        if not self.remote:
            with closing(sqlite3.connect(self.local_path)) as db, db:
                db.execute(SCHEMA)

    def _request(self, method: str, params: dict, *, row: dict | None = None) -> list[dict]:
        headers = {"apikey": self.key, "Content-Type": "application/json"}
        if not self.key.startswith("sb_secret_"):
            headers["Authorization"] = f"Bearer {self.key}"
        if method == "POST":
            headers["Prefer"] = "resolution=ignore-duplicates,return=minimal"
        try:
            with requests.request(
                method, f"{self.url}/rest/v1/sources", headers=headers, params=params,
                json=row, timeout=(4, 12), allow_redirects=False,
            ) as response:
                if not 200 <= response.status_code < 300:
                    raise StorageError(f"Penyimpanan menolak permintaan (HTTP {response.status_code}).")
                return response.json() if response.content else []
        except (requests.RequestException, ValueError):
            raise StorageError("Penyimpanan belum dapat dihubungi.") from None

    @staticmethod
    def make_id(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]

    def add(self, title: str, text: str, origin: str = "upload", doi: str = "",
            license: str = "", source_url: str = "") -> str:
        """Simpan berdasarkan hash teks, dengan metadata impor pertama."""
        row = {
            "id": self.make_id(text), "title": title, "origin": origin,
            "doi": doi or "", "license": license or "", "source_url": source_url or "",
            "text_content": text, "word_count": len(text.split()),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if self.remote:
            self._request("POST", {"on_conflict": "id"}, row=row)
        else:
            with closing(sqlite3.connect(self.local_path)) as db, db:
                db.execute(
                    "INSERT INTO sources (id,title,origin,doi,license,source_url,text_content,word_count,created_at)"
                    " VALUES (:id,:title,:origin,:doi,:license,:source_url,:text_content,:word_count,:created_at)"
                    " ON CONFLICT(id) DO NOTHING", row,
                )
        return row["id"]

    def list(self, include_text: bool = False, limit: int = 300) -> list[dict]:
        return self.page(limit=limit, include_text=include_text)

    def page(self, *, limit: int, offset: int = 0, query: str = "", origin: str = "",
             sort: str = "Terbaru", include_text: bool = False) -> list[dict]:
        """Terapkan pencarian, filter, dan pagination pada penyimpanan."""
        fields = "*" if include_text else META
        remote_sort, local_sort = SORTS[sort]
        query = query.strip()[:120]
        pattern = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        if self.remote:
            params = {"select": fields, "limit": max(0, limit), "offset": max(0, offset), "order": remote_sort}
            if query:
                params["title"] = "ilike." + pattern.replace("*", "\\*")
            if origin:
                params["origin"] = "in.(upload,unggahan pengguna)" if origin == "Unggahan" else "eq.OpenAlex full-text"
            return self._request("GET", params)
        conditions, args = [], []
        if query:
            conditions.append("title LIKE ? ESCAPE '\\'")
            args.append(pattern)
        if origin == "Unggahan":
            conditions.append("origin IN ('upload', 'unggahan pengguna')")
        elif origin:
            conditions.append("origin = 'OpenAlex full-text'")
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        return self._local_rows(
            f"SELECT {fields} FROM sources{where} ORDER BY {local_sort} LIMIT ? OFFSET ?",
            (*args, max(0, limit), max(0, offset)),
        )

    def _local_rows(self, sql: str, args: tuple) -> list[dict]:
        with closing(sqlite3.connect(self.local_path)) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute(sql, args)]

    def get_selected(self, ids: list[str]) -> list[dict]:
        """Ambil teks sumber yang diminta dalam urutan pilihan pengguna."""
        ids = list(dict.fromkeys(ids))
        if not ids:
            return []
        if any(not SOURCE_ID.fullmatch(sid) for sid in ids):
            raise StorageError("Identitas sumber tidak valid.")
        found = {}
        for start in range(0, len(ids), 30):
            batch = ids[start:start + 30]
            if self.remote:
                rows = self._request("GET", {"select": "*", "id": "in.(" + ",".join(batch) + ")"})
            else:
                params = ",".join("?" for _ in batch)
                rows = self._local_rows(f"SELECT * FROM sources WHERE id IN ({params})", tuple(batch))
            found.update((row["id"], row) for row in rows)
        return [found[sid] for sid in ids if sid in found]

    def delete(self, sid: str) -> None:
        if not SOURCE_ID.fullmatch(sid):
            raise StorageError("Identitas sumber tidak valid.")
        if self.remote:
            self._request("DELETE", {"id": f"eq.{sid}"})
        else:
            with closing(sqlite3.connect(self.local_path)) as db, db:
                db.execute("DELETE FROM sources WHERE id = ?", (sid,))
