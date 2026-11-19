"""Halaman pemeriksaan dokumen dan penelusuran OpenAlex."""

import streamlit as st

from engine import AnalysisLimit
from fileparser import DocumentError, SUPPORTED_TYPES, read_document
from openalex import OpenAlexError, download_full_text, search_works
from links import safe_url
from storage import SourceStore
from workflow import MAX_LOCAL_SOURCES, CheckError, CheckSettings, keywords, queries, run_check


def discovery_page(store: SourceStore, api_key: str) -> None:
    st.title("Jelajahi OpenAlex")
    st.write("Cari artikel open-access untuk ditambahkan ke koleksi sumber.")
    if not api_key:
        st.info("OpenAlex belum dikonfigurasi. Hubungi pengelola aplikasi untuk mengaktifkannya.")
        return
    with st.form("openalex_search"):
        query = st.text_input("Kata kunci akademik", max_chars=180)
        search = st.form_submit_button("Cari artikel", type="primary")
    if search:
        st.session_state.pop("oa_results", None)
        if not query.strip():
            st.warning("Isi kata kunci terlebih dahulu.")
        else:
            with st.spinner("Mencari artikel dan memeriksa metadata lisensi"):
                try:
                    st.session_state.oa_results = search_works(query.strip(), api_key, 25)
                except OpenAlexError as exc:
                    st.error(str(exc))
    results = st.session_state.get("oa_results")
    if results is None:
        st.info("Masukkan topik untuk melihat kandidat artikel.")
        return
    if not results:
        st.info("Belum ada artikel dengan lisensi yang didukung. Coba kata kunci lain.")
        return
    st.caption(f"{len(results)} kandidat berlisensi ditemukan.")
    for item in results:
        with st.expander(item.title):
            st.text(item.title)
            st.write(f"{item.year or 'Tahun tidak tersedia'} ? {item.license} ? "
                     f"{'XML tersedia' if item.has_full_text else 'XML belum tersedia'}")
            url = safe_url(item.source_url)
            if url:
                st.link_button("Buka artikel", url, key=f"open_{item.id}")
    available = {item.id: item for item in results if item.has_full_text}
    chosen = st.multiselect("Artikel untuk diimpor", list(available),
                            format_func=lambda wid: available[wid].title, max_selections=5)
    if st.button("Impor artikel terpilih", disabled=not chosen, type="primary"):
        progress = st.progress(0, text="Menyiapkan impor")
        imported = 0
        for index, wid in enumerate(chosen, 1):
            item = available[wid]
            try:
                text = download_full_text(item, api_key)
                store.add(item.title, text, "OpenAlex full-text", item.doi, item.license, item.source_url)
                imported += 1
            except OpenAlexError as exc:
                st.error(f"Artikel {wid} ? {exc}")
            except Exception:
                st.error(f"Artikel {wid} belum dapat disimpan.")
            progress.progress(index / len(chosen), text=f"{index} dari {len(chosen)} artikel diproses")
        if imported:
            st.session_state.pop("library_cache_scope", None)
            st.success(f"{imported} artikel tersedia dalam koleksi.")


def _reset_upload() -> None:
    for key in ("prepared_document", "check_keywords", "check_consent"):
        st.session_state.pop(key, None)


def check_page(store: SourceStore, api_key: str, reports_route, semantic_enabled: bool = False) -> None:
    st.title("Periksa kemiripan")
    st.write("Unggah satu dokumen dan pilih sumber pembanding untuk pemeriksaan ini.")

    st.header("1. Unggah dokumen")
    uploaded = st.file_uploader("Proposal, skripsi, atau dokumen akademik",
                                type=list(SUPPORTED_TYPES), key="check_upload", on_change=_reset_upload,
                                help="PDF, DOCX, atau TXT ? Maksimal 15 MB.")
    if st.button("Baca dokumen", disabled=uploaded is None):
        with st.spinner("Mengekstrak teks"):
            try:
                document = read_document(uploaded.name, uploaded.getvalue())
            except DocumentError as exc:
                st.error(str(exc))
                _reset_upload()
            else:
                st.session_state.prepared_document = (uploaded.name, document)
                st.session_state.pop("check_keywords", None)
                st.session_state.pop("check_consent", None)
    prepared = st.session_state.get("prepared_document")
    if not prepared:
        st.info("Setelah memilih file, tekan Baca dokumen untuk memulai.")
        return
    filename, document = prepared
    st.text(filename)
    st.success(f"Teks siap diperiksa ? {len(document.split()):,} kata")

    st.header("2. Atur pemeriksaan")
    modes = ["Koleksi sumber"] + (["OpenAlex otomatis", "Gabungan"] if api_key else [])
    mode = st.radio("Sumber pembanding", modes)
    if not api_key:
        st.caption("Pemeriksaan OpenAlex tersedia setelah pengelola mengonfigurasi layanan.")
    selected = []
    if mode in ("Koleksi sumber", "Gabungan"):
        try:
            rows = store.list(limit=300)
        except Exception:
            rows = []
            st.error("Koleksi belum dapat dimuat. Gunakan OpenAlex otomatis atau coba kembali.")
        titles = {row["id"]: row["title"] for row in rows}
        if titles:
            selected = st.multiselect("Pilih hingga 12 sumber dari koleksi", list(titles),
                                      format_func=titles.__getitem__, max_selections=MAX_LOCAL_SOURCES)
        else:
            st.info("Belum ada sumber terpilih dari koleksi. Impor jurnal atau pilih OpenAlex otomatis.")
    with st.expander("Opsi pencocokan"):
        bibliography = st.checkbox("Kecualikan daftar pustaka", value=True)
        quotes = st.checkbox("Kecualikan teks dalam tanda kutip", value=False)
        minimum = st.slider("Minimum kata berurutan yang cocok", 5, 20, 10)
        semantic = semantic_enabled and st.checkbox(
            "Tinjau kemungkinan parafrase (eksperimental)",
            help="Model lokal membandingkan sampel kalimat dan menambahkan indikator terpisah.",
        )
    search_queries = []
    if mode != "Koleksi sumber":
        st.write("Tinjau kata kunci sebelum dikirim ke OpenAlex. Hapus istilah yang bersifat pribadi.")
        suggested = keywords(document, bibliography=bibliography, quotes=quotes)
        edited = st.text_input("Kata kunci untuk OpenAlex", value=suggested, max_chars=180, key="check_keywords")
        search_queries = queries(edited)
        if search_queries:
            st.caption("Kueri OpenAlex ? " + " / ".join(search_queries))
        allow = st.checkbox("Saya setuju kata kunci di atas dikirim ke OpenAlex.", key="check_consent")
    else:
        allow = True

    st.header("3. Jalankan pemeriksaan")
    disabled = (mode != "OpenAlex otomatis" and not selected) or (
        mode != "Koleksi sumber" and (not allow or not search_queries)
    )
    if st.button("Mulai pemeriksaan", type="primary", disabled=disabled):
        st.session_state.pop("analysis", None)
        progress = st.progress(0, text="Menyiapkan dokumen")
        try:
            st.session_state.analysis = run_check(
                filename, document, CheckSettings(mode, minimum, bibliography, quotes, semantic), store,
                selected=selected, api_key=api_key, search_queries=search_queries,
                progress=lambda amount, message: progress.progress(amount, text=message),
            )
        except (CheckError, AnalysisLimit) as exc:
            progress.empty()
            st.error(str(exc))
        except Exception:
            progress.empty()
            st.error("Pemeriksaan berhenti. Coba kembali dengan dokumen atau koleksi yang lebih kecil.")
        else:
            st.success("Laporan siap ditinjau.")
    st.header("4. Tinjau hasil")
    if st.session_state.get("analysis"):
        st.page_link(reports_route, label="Buka laporan sesi", icon=":material/description:")
    else:
        st.info("Laporan tampil setelah sumber berhasil dibandingkan.")
