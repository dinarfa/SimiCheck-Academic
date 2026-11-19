"""Unggahan massal dan pengelolaan koleksi Streamlit."""

from hashlib import sha256
from html import escape
from threading import BoundedSemaphore
from uuid import uuid4

import streamlit as st

from fileparser import DocumentError, SUPPORTED_TYPES, read_document, validate_upload
from links import safe_url
from storage import SORTS, SourceStore

PAGE_SIZE = 8
MAX_BATCH_FILES = 12
MAX_BATCH_BYTES = 45 * 1024 * 1024
IMPORT_SLOT = BoundedSemaphore(1)


def _reset_page() -> None:
    st.session_state.library_page = 0


@st.cache_data(ttl=30, max_entries=24, show_spinner=False)
def _page(_store: SourceStore, session_scope: str, offset: int, query: str,
          origin: str, sort: str) -> list[dict]:
    # Scope acak per sesi. Hanya metadata yang dicache.
    return _store.page(limit=PAGE_SIZE + 1, offset=offset, query=query, origin=origin, sort=sort)


def _show_collection(store: SourceStore) -> None:
    st.header("Telusuri koleksi")
    query = st.text_input("Cari nama sumber", max_chars=120, on_change=_reset_page)
    origin_col, sort_col = st.columns(2)
    origin = origin_col.selectbox("Jenis sumber", ["Semua", "Unggahan", "OpenAlex"], on_change=_reset_page)
    sort = sort_col.selectbox("Urutkan menurut", list(SORTS), on_change=_reset_page)
    page = st.session_state.get("library_page", 0)
    try:
        with st.spinner("Memuat koleksi sumber"):
            rows = _page(store, st.session_state.library_cache_scope, page * PAGE_SIZE,
                         query, "" if origin == "Semua" else origin, sort)
    except Exception:
        st.error("Koleksi belum dapat dimuat. Coba kembali.")
        return
    if not rows:
        st.info("Belum ada sumber yang cocok. Ubah filter atau impor sumber baru.")
    for row in rows[:PAGE_SIZE]:
        with st.expander(row["title"]):
            st.html("<div style='overflow-wrap:anywhere'>" + escape(row["title"]) + "</div>")
            st.write(f"{row['word_count']:,} kata ? Diimpor {row['created_at'][:10]} ? Teks berhasil diekstrak")
            st.write("Asal sumber ? " + row["origin"])
            if row.get("license"):
                st.text("Lisensi ? " + row["license"])
            if row.get("doi"):
                st.text("DOI ? " + row["doi"])
            url = safe_url(row.get("source_url") or "")
            if url:
                st.link_button("Buka sumber", url, key=f"open_{row['id']}")
            confirmed = st.checkbox("Konfirmasi hapus sumber ini", key=f"confirm_{row['id']}")
            if st.button("Hapus sumber", key=f"delete_{row['id']}", disabled=not confirmed):
                try:
                    store.delete(row["id"])
                except Exception:
                    st.error("Sumber belum dapat dihapus. Coba kembali.")
                else:
                    _invalidate()
                    if len(rows) == 1 and page:
                        st.session_state.library_page = page - 1
                    st.session_state.library_notice = "Sumber berhasil dihapus."
                    st.rerun()
    prev, current, next_ = st.columns(3)
    if prev.button("Sebelumnya", disabled=page == 0):
        st.session_state.library_page = page - 1
        st.rerun()
    current.write(f"Halaman {page + 1}")
    if next_.button("Berikutnya", disabled=len(rows) <= PAGE_SIZE):
        st.session_state.library_page = page + 1
        st.rerun()


def _invalidate() -> None:
    st.session_state.library_cache_scope = uuid4().hex


def _show_upload(store: SourceStore) -> None:
    st.header("Impor jurnal")
    st.caption("PDF, DOCX, atau TXT. Maksimal 15 MB per file dan 12 file atau 45 MB sekali impor.")
    epoch = st.session_state.get("library_upload_epoch", 0)
    uploads = st.file_uploader("Pilih atau seret file jurnal", type=list(SUPPORTED_TYPES),
                               accept_multiple_files=True, key=f"library_files_{epoch}")
    previous = st.session_state.get("import_results", [])
    if previous:
        succeeded = sum(item["Tersedia"] for item in previous)
        if succeeded:
            st.success(f"{succeeded} dari {len(previous)} file tersedia dalam koleksi.")
        else:
            st.warning("Belum ada file yang berhasil diimpor.")
        st.dataframe([{k: v for k, v in item.items() if k != "Tersedia"} for item in previous],
                     hide_index=True)
    if not uploads:
        return
    if len(uploads) > MAX_BATCH_FILES or sum(file.size for file in uploads) > MAX_BATCH_BYTES:
        st.error("Kurangi jumlah atau ukuran file sebelum mengimpor.")
        return

    ready, statuses, seen = {}, [], set()
    for file in uploads:
        content = file.getvalue()
        digest = sha256(content).hexdigest()
        try:
            validate_upload(file.name, content)
            if digest in seen:
                raise DocumentError("Duplikat dalam unggahan ini.")
            seen.add(digest)
            ready[digest] = file
            message = "Format awal valid"
        except DocumentError as exc:
            message = str(exc)
        statuses.append({"File": file.name, "Ukuran": f"{file.size / 1024:,.1f} KB", "Status": message})
    st.caption(f"{len(ready)} dari {len(uploads)} file siap dipilih.")
    st.dataframe(statuses, hide_index=True)
    if not ready:
        return
    selected = st.multiselect("File yang akan diimpor", list(ready), default=list(ready),
                              format_func=lambda digest: ready[digest].name, key=f"import_selection_{epoch}")
    with st.form(f"confirm_import_{epoch}"):
        confirm = st.checkbox("Saya berhak menggunakan dan menyimpan file yang dipilih sebagai sumber.")
        run = st.form_submit_button("Konfirmasi dan impor", type="primary", disabled=not selected)
    if not run:
        return
    if not confirm:
        st.warning("Konfirmasi izin penggunaan sebelum mengimpor.")
        return

    if not IMPORT_SLOT.acquire(blocking=False):
        st.info("Impor lain sedang berlangsung. Coba lagi setelah selesai.")
        return
    try:
        results = _import_batch(store, ready, selected)
    finally:
        IMPORT_SLOT.release()
    st.session_state.import_results = results
    st.session_state.library_upload_epoch = epoch + 1
    _invalidate()
    st.rerun()


def _import_batch(store: SourceStore, ready: dict, selected: list[str]) -> list[dict]:
    progress = st.progress(0, text="Menyiapkan impor")
    results = []
    for index, digest in enumerate(selected, 1):
        file = ready[digest]
        try:
            text = read_document(file.name, file.getvalue())
            store.add(file.name, text, origin="unggahan pengguna")
            message, ok = "Tersedia dalam koleksi", True
        except DocumentError as exc:
            message, ok = str(exc), False
        except Exception:
            message, ok = "Penyimpanan gagal. Coba impor kembali.", False
        results.append({"File": file.name, "Status": message, "Tersedia": ok})
        progress.progress(index / len(selected), text=f"{index} dari {len(selected)} file diproses")
    return results


def library_page(store: SourceStore) -> None:
    st.title("Koleksi sumber")
    st.write("Tambahkan jurnal pembanding dan kelola artikel yang tersimpan.")
    if "library_cache_scope" not in st.session_state:
        _invalidate()
    notice = st.session_state.pop("library_notice", None)
    if notice:
        st.success(notice)
    _show_upload(store)
    st.divider()
    _show_collection(store)
