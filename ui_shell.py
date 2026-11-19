"""Tampilan akses, dasbor, dan pengaturan."""

import hmac
from time import monotonic

import streamlit as st

from storage import SourceStore

APP_VERSION = "1.1.0"


def login(password: str) -> None:
    """Verifikasi akses sebelum membuat penyimpanan atau navigasi."""
    with st.container(width=480, border=True):
        st.markdown(
            '<svg aria-hidden="true" width="42" height="42" viewBox="0 0 24 24" '
            'fill="#0F766E"><path d="M4 3h10l5 5v5h-2V9h-5V5H6v14h6v2H4z"/>'
            '<path d="M19 13a3 3 0 1 0 0 6c.5 0 .96-.12 1.38-.33l2.2 2.2 1.4-1.42-2.2-2.2'
            'c.15-.39.22-.81.22-1.25a3 3 0 0 0-3-3zm0 2a1 1 0 1 1 0 2 1 1 0 0 1 0-2z"/>'
            '</svg>',
            unsafe_allow_html=True,
        )
        st.title("SimiCheck Academic")
        st.write("Periksa kemiripan dokumen akademik dan telusuri sumber yang cocok.")
        with st.form("login"):
            entered = st.text_input("Kata sandi", type="password")
            submitted = st.form_submit_button("Masuk", type="primary")
        if submitted:
            now = monotonic()
            if now < st.session_state.get("login_retry_at", 0):
                st.warning("Tunggu beberapa detik sebelum mencoba lagi.")
            else:
                with st.spinner("Memverifikasi akses"):
                    if hmac.compare_digest(entered.encode(), password.encode()):
                        for key in ("login_attempts", "login_retry_at"):
                            st.session_state.pop(key, None)
                        st.session_state.authenticated = True
                        st.rerun()
                attempts = st.session_state.get("login_attempts", 0) + 1
                st.session_state.login_attempts = attempts
                if attempts >= 3:
                    st.session_state.login_retry_at = now + min(30, 2 ** min(attempts - 3, 5))
                st.error("Kata sandi salah. Periksa dan coba lagi.")
        st.caption("Dokumen yang diperiksa diproses selama sesi. Koleksi sumber disimpan terpisah.")
    st.caption(f"SimiCheck Academic ? Versi {APP_VERSION}")


def dashboard(store: SourceStore, check_route, library_route, reports_route) -> None:
    st.title("SimiCheck Academic")
    st.write("Periksa kemiripan dokumen akademik dan tinjau bukti pencocokan per sumber.")
    primary, secondary = st.columns(2)
    primary.page_link(check_route, label="Periksa dokumen", icon=":material/fact_check:")
    secondary.page_link(library_route, label="Kelola koleksi", icon=":material/library_books:")
    with st.container(border=True):
        st.subheader("Koleksi sumber")
        try:
            rows = store.list(limit=1)
        except Exception:
            st.error("Koleksi belum dapat dimuat. Coba kembali nanti.")
        else:
            if rows:
                st.write(f"Sumber terbaru ? {rows[0]['title']}")
            else:
                st.info("Koleksi masih kosong. Impor sumber dari perangkat atau OpenAlex.")
    with st.container(border=True):
        st.subheader("Pemeriksaan dalam sesi ini")
        analysis = st.session_state.get("analysis")
        if analysis:
            st.write(analysis.filename)
            st.page_link(reports_route, label="Buka laporan", icon=":material/description:")
        else:
            st.info("Mulai pemeriksaan untuk melihat laporan di sini.")


def settings(store: SourceStore, private: bool, discovery_ready: bool) -> None:
    st.title("Pengaturan")
    st.write("Lihat konfigurasi penyimpanan dan akses aplikasi.")
    with st.container(border=True):
        st.subheader("Status konfigurasi")
        st.write("Penyimpanan ? " + ("Supabase" if store.remote else "SQLite lokal"))
        st.write("OpenAlex ? " + ("Dikonfigurasi" if discovery_ready else "Belum dikonfigurasi"))
        st.write("Akses ? " + ("Kata sandi aplikasi" if private else "Mode lokal"))
        st.caption(f"Versi {APP_VERSION}")
    with st.container(border=True):
        st.subheader("Privasi dokumen")
        st.write("Dokumen pemeriksaan dan laporannya tersedia selama sesi. Koleksi sumber memakai penyimpanan aplikasi.")
        if st.button("Hapus dokumen dan laporan dari sesi"):
            for key in ("analysis", "prepared_document", "check_keywords", "check_consent", "check_upload"):
                st.session_state.pop(key, None)
            st.success("Dokumen dan laporan sesi telah dihapus.")
        if private:
            st.caption("Kata sandi bersama memberi akses yang sama kepada semua pemegangnya.")
