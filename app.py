"""Entry point Streamlit dan pembatas akses SimiCheck Academic."""

import os
from sqlite3 import Error as SQLiteError

import streamlit as st

from storage import SourceStore, StorageError
from source_library import library_page
from ui_pages import check_page, discovery_page
from ui_reports import render_result
from ui_shell import dashboard, login, settings

st.set_page_config(page_title="SimiCheck Academic", layout="wide")


def conf(name: str) -> str:
    try:
        return str(st.secrets.get(name) or os.environ.get(name, ""))
    except (FileNotFoundError, KeyError):
        return os.environ.get(name, "")


password = conf("APP_PASSWORD")
supa_url = conf("SUPABASE_URL")
supa_key = conf("SUPABASE_SECRET_KEY") or conf("SUPABASE_SERVICE_ROLE_KEY")
openalex_key = conf("OPENALEX_API_KEY")
semantic_enabled = conf("SIMICHECK_SEMANTIC").lower() in {"1", "yes", "true"}

if password and not st.session_state.get("authenticated"):
    login(password)
    st.stop()

if bool(supa_url) != bool(supa_key) or (supa_url and not password):
    st.error("Konfigurasi aplikasi belum lengkap. Hubungi pengelola aplikasi.")
    st.stop()

if password and st.sidebar.button("Keluar"):
    st.session_state.clear()
    st.rerun()

try:
    store = SourceStore(supa_url, supa_key)
except (StorageError, SQLiteError, OSError):
    st.error("Penyimpanan belum siap digunakan. Hubungi pengelola aplikasi.")
    st.stop()


def reports():
    st.title("Laporan")
    st.caption("Tinjau hasil pemeriksaan yang tersedia dalam sesi ini.")
    if st.session_state.get("analysis"):
        render_result()
    else:
        st.info("Laporan akan muncul setelah pemeriksaan dokumen berhasil.")


dashboard_route = st.Page(
    lambda: dashboard(store, check_route, library_route, reports_route), title="Dasbor", icon=":material/dashboard:", default=True
)
check_route = st.Page(
    lambda: check_page(store, openalex_key, reports_route, semantic_enabled), title="Periksa kemiripan", icon=":material/fact_check:",
    url_path="periksa",
)
library_route = st.Page(
    lambda: library_page(store), title="Koleksi sumber", icon=":material/library_books:",
    url_path="koleksi",
)
discovery_route = st.Page(
    lambda: discovery_page(store, openalex_key), title="Jelajahi OpenAlex",
    icon=":material/search:", url_path="openalex",
)
reports_route = st.Page(reports, title="Laporan", icon=":material/description:", url_path="laporan")
settings_route = st.Page(
    lambda: settings(store, bool(password), bool(openalex_key)), title="Pengaturan",
    icon=":material/settings:", url_path="pengaturan",
)

page = st.navigation(
    [dashboard_route, check_route, library_route, discovery_route, reports_route, settings_route]
)
if not password:
    st.sidebar.caption("Mode lokal tanpa autentikasi")
page.run()
