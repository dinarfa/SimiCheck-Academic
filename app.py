"""SimiCheck Academic — hosted, privately accessed academic similarity checker.
Run: streamlit run app.py
"""
import hmac
import os
import streamlit as st
from engine import analyze
from fileparser import read_document
from openalex import search_works, download_full_text
from report import make_html, highlighted
from storage import SourceStore

st.set_page_config(page_title='SimiCheck Academic', page_icon='🔎', layout='wide',
                   initial_sidebar_state='expanded')


def conf(name):
    try:
        return st.secrets.get(name, os.environ.get(name, ''))
    except Exception:
        return os.environ.get(name, '')


password = conf('APP_PASSWORD')
supa_url = conf('SUPABASE_URL')
supa_key = conf('SUPABASE_SECRET_KEY') or conf('SUPABASE_SERVICE_ROLE_KEY')
openalex_key = conf('OPENALEX_API_KEY')

st.markdown('''<style>
.block-container {padding-top:2rem;max-width:1240px}
[data-testid="stMetricValue"] {font-size:2.7rem}
.stButton button[kind="primary"] {border-radius:9px}
</style>''', unsafe_allow_html=True)

st.title('🔎 SimiCheck Academic')
st.caption('Pemeriksa kemiripan berbasis sumber yang diketahui · bukan Turnitin · bukan penentu plagiarisme')

if password:
    if not st.session_state.get('authenticated', False):
        with st.form('login'):
            st.subheader('Akses privat')
            entered = st.text_input('Masukkan kata sandi aplikasi', type='password')
            submitted = st.form_submit_button('Masuk', type='primary')
        if submitted:
            if hmac.compare_digest(entered, password):
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error('Kata sandi tidak benar.')
        st.stop()
elif supa_url or supa_key:
    st.error('Untuk deployment online, APP_PASSWORD wajib diatur agar koleksi dokumen tidak terbuka untuk umum.')
    st.stop()
else:
    st.warning('Mode lokal tanpa autentikasi. Untuk hosting online, isi Secrets APP_PASSWORD + Supabase.')

store = SourceStore(supa_url, supa_key)
with st.sidebar:
    st.header('Status sistem')
    st.success('Database Supabase terhubung' if store.remote else 'Mode lokal SQLite')
    st.write('OpenAlex:', 'Siap' if openalex_key else 'API key belum disetel')
    st.caption('File proposal hanya diproses dalam sesi aplikasi; teks sumber jurnal disimpan pada database sumber.')
    st.info('Skor SimiCheck = proporsi kata yang cocok secara berurutan pada sumber yang telah diindeks. Skor bukan persentase Turnitin.')
    if password and st.button('Keluar'):
        st.session_state.authenticated = False
        st.rerun()

tab_check, tab_sources, tab_openalex, tab_guide = st.tabs([
    '🧪 Cek dokumen', '📚 Koleksi sumber', '🌍 Cari jurnal open-access', 'ℹ️ Panduan'])

with tab_sources:
    st.subheader('Koleksi jurnal pembanding')
    try:
        current = store.list(limit=300)
    except Exception as exc:
        st.error(f'Gagal memuat sumber: {exc}')
        current = []
    st.metric('Total sumber tersedia (maks. 300 ditampilkan)', len(current))
    if current:
        st.dataframe([{'Judul': x['title'], 'Asal': x['origin'],
                       'Jumlah kata': x.get('word_count', 0), 'Lisensi': x.get('license', ''),
                       'URL sumber': x.get('source_url', '')} for x in current],
                     hide_index=True, use_container_width=True)
    st.divider()
    st.markdown('**Unggah jurnal sendiri**')
    with st.form('upload_sources'):
        files = st.file_uploader('Pilih satu atau banyak PDF/DOCX/TXT',
                                 type=['pdf', 'docx', 'txt'], accept_multiple_files=True)
        allowed_upload = st.checkbox('Saya berhak menggunakan file ini untuk penelitian pribadi dan penyimpanan privat.')
        submit_sources = st.form_submit_button('Impor ke database', type='primary')
    if submit_sources:
        if not allowed_upload:
            st.error('Centang konfirmasi penggunaan sumber terlebih dahulu.')
        elif not files:
            st.warning('Pilih paling sedikit satu jurnal.')
        else:
            imported = 0
            for f in files:
                try:
                    t = read_document(f.name, f.getvalue())
                    store.add(f.name, t, origin='unggahan pengguna')
                    imported += 1
                except Exception as exc:
                    st.error(f'{f.name}: {exc}')
            if imported:
                st.success(f'{imported} sumber berhasil disimpan. Buka tab ini lagi untuk melihat daftar terbaru.')
    if current:
        with st.expander('Hapus sumber dari database'):
            names = {x['id']: x['title'] for x in current}
            choice = st.selectbox('Pilih sumber', options=list(names), format_func=lambda v: names[v])
            delete_confirm = st.checkbox('Saya yakin ingin menghapus sumber terpilih')
            if st.button('Hapus sumber', disabled=not delete_confirm):
                store.delete(choice)
                st.success('Sumber dihapus. Muat ulang untuk memperbarui tabel.')

with tab_openalex:
    st.subheader('Temukan artikel ilmiah yang boleh diindeks')
    st.write('Pencarian dilakukan melalui **OpenAlex**. Hanya artikel dengan lisensi terbuka yang '
             'diizinkan (CC BY, CC BY-SA, CC0) yang ditampilkan. Tidak semua artikel memiliki XML full-text.')
    with st.form('search_openalex'):
        query = st.text_input('Topik artikel', placeholder='misalnya: disaster risk communication sentiment analysis')
        limit = st.slider('Jumlah hasil OpenAlex yang diperiksa', 5, 20, 15, 5)
        submitted = st.form_submit_button('Cari artikel', type='primary')
    if submitted:
        if not query.strip():
            st.warning('Masukkan topik pencarian.')
        else:
            try:
                st.session_state['oa_results'] = search_works(query.strip(), openalex_key, limit)
            except Exception as exc:
                st.error(f'Pencarian gagal: {exc}')
    results = st.session_state.get('oa_results', [])
    if results:
        st.caption(f'{len(results)} artikel dengan lisensi yang diterima ditemukan dalam hasil pencarian ini.')
        st.dataframe([{'ID': v['id'], 'Judul': v['title'], 'Tahun': v['year'],
                       'Lisensi': v['license'], 'Full-text XML': 'Ada' if v['has_full_text'] else 'Belum ada'}
                      for v in results], hide_index=True, use_container_width=True)
        available = [x for x in results if x['has_full_text']]
        ids = [x['id'] for x in available]
        labels = {x['id']: f"{x['title']} ({x['year']})" for x in available}
        chosen = st.multiselect('Pilih artikel full-text untuk diimpor (maksimal 5 sekali impor)',
                                ids, format_func=lambda x: labels[x], max_selections=5)
        if st.button('Unduh full-text berlisensi dan simpan ke database',
                     disabled=not chosen, type='primary'):
            imported = 0
            for wid in chosen:
                item = next(x for x in available if x['id'] == wid)
                try:
                    with st.spinner(f'Mengimpor {wid}...'):
                        text = download_full_text(wid, openalex_key)
                        store.add(item['title'], text, origin='OpenAlex full-text',
                                  doi=item['doi'], license=item['license'],
                                  source_url=item['source_url'])
                    imported += 1
                except Exception as exc:
                    st.error(f'{wid}: {exc}')
            if imported:
                st.success(f'{imported} artikel diindeks. Kembali ke tab Cek dokumen untuk menganalisis.')
    elif openalex_key:
        st.caption('Cari topik untuk mulai membangun korpusmu.')

with tab_check:
    st.subheader('Periksa kemiripan dokumen')
    st.write('Unggah proposal atau skripsi dan bandingkan dengan teks lengkap sumber yang telah kamu impor.')
    try:
        sources_meta = store.list(include_text=False, limit=300)
    except Exception as exc:
        st.error(f'Tidak bisa membaca database: {exc}')
        sources_meta = []
    if not sources_meta:
        st.info('Koleksi pembanding masih kosong. Upload jurnal pada tab Koleksi sumber atau impor dari OpenAlex.')
    else:
        map_titles = {s['id']: s['title'] for s in sources_meta}
        selected = st.multiselect('Sumber untuk dibandingkan', list(map_titles),
                                  default=list(map_titles),
                                  format_func=lambda sid: map_titles[sid],
                                  help='Batasi ke jurnal relevan agar waktu pemrosesan dan penggunaan memori tetap kecil.')
        with st.form('check_document'):
            f = st.file_uploader('Proposal/skripsi PDF, DOCX, atau TXT', type=['pdf', 'docx', 'txt'])
            threshold = st.slider('Minimal panjang teks cocok (kata berurutan)', 5, 20, 10)
            ex_bib = st.checkbox('Kecualikan daftar pustaka', value=True)
            ex_quotes = st.checkbox('Kecualikan teks dalam tanda kutip', value=False)
            run = st.form_submit_button('Jalankan similarity check', type='primary')
        if run:
            if not f:
                st.warning('Silakan unggah dokumen terlebih dahulu.')
            elif not selected:
                st.warning('Pilih minimal satu sumber pembanding.')
            else:
                try:
                    with st.spinner('Membaca dokumen dan membandingkan dengan sumber...'):
                        doc_text = read_document(f.name, f.getvalue())
                        all_sources = store.list(include_text=True, limit=300)
                        selected_sources = [s for s in all_sources if s['id'] in set(selected)]
                        res = analyze(doc_text, selected_sources, min_match_words=threshold,
                                      exclude_bibliography=ex_bib, exclude_quotes=ex_quotes)
                        st.session_state['analysis'] = {
                            'filename': f.name, 'document': doc_text,
                            'sources': selected_sources, 'result': res}
                except Exception as exc:
                    st.error(f'Gagal memproses dokumen: {exc}')
        data = st.session_state.get('analysis')
        if data:
            result = data['result']
            smap = {s['id']: s for s in data['sources']}
            st.divider()
            st.subheader(f"Hasil: {data['filename']}")
            a, b, c = st.columns(3)
            a.metric('Kemiripan dengan koleksi', f'{result.percentage:.1f}%')
            b.metric('Kata yang cocok', f'{result.covered_words:,}')
            c.metric('Kata yang dihitung', f'{result.eligible_words:,}')
            st.warning('Persentase ini dihitung terhadap korpus SimiCheck yang tersedia, bukan database Turnitin. '
                       'Kesamaan teks tidak otomatis berarti plagiarisme.')
            summary = sorted(result.source_words.items(), key=lambda v: -v[1])
            st.markdown('**Kontribusi sumber**')
            if summary:
                st.dataframe([{
                    'Sumber': smap[sid]['title'], 'Kata cocok': num,
                    'Kontribusi ke skor': f'{100*num/result.eligible_words:.2f}%' if result.eligible_words else '0%',
                    'Tautan': smap[sid].get('source_url') or ''}
                    for sid, num in summary], hide_index=True, use_container_width=True)
            else:
                st.info('Tidak ada frasa yang melewati ambang kecocokan pada sumber yang dipilih.')
            content = make_html(data['document'], result, data['sources'], data['filename'])
            st.download_button('⬇️ Unduh laporan HTML (bisa Print → Save as PDF)',
                               data=content.encode('utf8'), file_name='SimiCheck_report.html',
                               mime='text/html')
            with st.expander('Lihat highlight dokumen', expanded=True):
                st.markdown(f'<div style="max-height:600px;overflow:auto;line-height:1.9;'
                            f'padding:18px;border:1px solid #ddd;border-radius:8px;white-space:normal">'
                            f'{highlighted(data["document"], result, smap)}</div>',
                            unsafe_allow_html=True)
            with st.expander('Pasangan kecocokan terpanjang'):
                if not result.matches:
                    st.write('Tidak ada kecocokan yang lolos ambang.')
                for m in result.matches[:25]:
                    st.markdown(f'**{m.source_title}** · {m.length} kata berurutan')
                    st.text('Dokumen: ' + m.doc_excerpt[:280])
                    st.text('Sumber:   ' + m.source_excerpt[:280])
                    st.divider()

with tab_guide:
    st.subheader('Cara membaca hasil')
    st.markdown('''
**Yang terdeteksi:** potongan 5–20 kata (sesuai ambang yang kamu pilih) dengan urutan
kata sama, meskipun ada perbedaan kapitalisasi atau sebagian tanda baca. Skor dihitung
berdasarkan jumlah kata dokumen yang terdeteksi cocok, **tanpa menghitung kata yang sama dua kali**.

**Yang belum terdeteksi secara andal:** parafrase, kemiripan makna lintas bahasa,
teks dalam gambar/PDF scan, dokumen di internet yang belum diindeks, dan dokumen
privat milik sistem lain. Kemiripan merupakan petunjuk pemeriksaan, **bukan vonis plagiarisme**.

**Privasi:** file proposal dibaca di memori selama sesi. Teks jurnal yang diimpor
disimpan dalam database privat; hapus sumber jika sudah tidak diperlukan. Gunakan
kata sandi aplikasi yang kuat. Jangan unggah file rahasia ke aplikasi publik tanpa
autentikasi yang memadai.

**Keakuratan:** perlu diuji dengan dokumen uji yang diketahui sumbernya, disertai
pemeriksaan manual. Jangan menjanjikan hasil sama dengan Turnitin kepada pengguna lain.
''')
