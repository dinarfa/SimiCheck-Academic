# SimiCheck Academic — pemeriksa kemiripan akademik berbasis korpus

Aplikasi web Streamlit dengan unggah PDF/DOCX/TXT, sumber jurnal berlisensi open-access via OpenAlex (full-text GROBID XML), database sumber permanen di Supabase, highlight kemiripan kata, kontribusi per sumber, dan ekspor laporan HTML. **Bukan Turnitin** dan **bukan mesin penentu plagiarisme**.

## 1. Jalankan secara lokal untuk uji

Python versi 3.10+ disarankan.

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
# source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Tanpa Secrets, aplikasi otomatis memakai SQLite lokal `local_sources.sqlite3`; file ini **tidak** cocok untuk penyimpanan permanen pada layanan cloud gratis.

Untuk menguji engine tanpa layanan luar:

```bash
python -m unittest discover -s tests -v
```

## 2. Buat database sumber persisten (Supabase)

1. Buat proyek gratis di https://supabase.com/.
2. Buka **SQL Editor**, salin seluruh isi `schema.sql`, lalu jalankan.
3. Dari **Project Settings → API Keys**, ambil `sb_secret_...` (**secret key, bukan publishable key**) dan **Project URL** yang formatnya `https://PROJECT.supabase.co`.
4. Jangan masukkan secret key ke repository, HTML, JavaScript frontend, atau file publik.
5. Database gratis bisa dijeda oleh Supabase jika tidak aktif cukup lama. Cadangkan data penting.

## 3. Daftar OpenAlex API key gratis

1. Daftar/login di https://openalex.org/ dan aktifkan API key.
2. Gunakan `OPENALEX_API_KEY` di Secrets. Free tier memiliki kuota harian.
3. Dalam aplikasi, cari topik. Pilih artikel yang **memiliki lisensi CC BY, CC BY-SA, atau CC0** dan GROBID XML lengkap, lalu impor (maks. lima per sekali impor).
4. Artikel open-access yang sekadar dapat dibaca gratis **tidak otomatis** boleh disalin atau diindeks; aplikasi memakai daftar lisensi konservatif. Metadata dan hasil parsing harus ditinjau untuk publikasi/layanan komersial.

## 4. Deploy gratis di Streamlit Community Cloud

1. Buat repository **privat** baru di GitHub https://github.com/new.
2. Upload seluruh isi folder proyek (struktur folder dipertahankan), **kecuali** file `.env`, `.streamlit/secrets.toml`, atau `*.sqlite3`.
3. Buka https://share.streamlit.io/, masuk dengan GitHub, pilih **Create app** → repository → branch `main` → main file `app.py`.
4. Masukkan Secrets berikut dalam Advanced settings / App settings. **Ganti semua placeholder.**

```toml
APP_PASSWORD = "GANTI_DENGAN_SANDI_YANG_PANJANG"
SUPABASE_URL = "https://NAMA-PROJEK.supabase.co"
SUPABASE_SECRET_KEY = "sb_secret_ISI_DARI_DASHBOARD"
OPENALEX_API_KEY = "ISI_API_KEY_OPENALEX"
```

5. Deploy. Website mendapat URL `https://nama-app.streamlit.app` sesuai nama yang tersedia.
6. Atur visibilitas app **private** di Streamlit App Settings bila tersedia, atau wajibkan `APP_PASSWORD`. Untuk penggunaan multiuser skala besar, tambahkan autentikasi masing-masing pengguna dan kebijakan isolasi data.

**Mengapa Streamlit, bukan Vercel?** Proses PDF dan pencocokan teks lebih sesuai pada aplikasi Python dengan sumber daya yang tetap hidup selama permintaan. Streamlit Community Cloud bisa tidur ketika tidak diakses; pengguna bisa membangunkannya melalui halaman aplikasi. Kamu tidak perlu menyalakan laptop. Supabase Free juga bisa mengalami jeda karena inaktivitas.

## 5. Alur pemakaian

1. Tab **Koleksi sumber**: unggah PDF/DOCX jurnal yang kamu gunakan atau punya hak pakai; di sini teks diekstrak dan disimpan.
2. Tab **Cari jurnal open-access**: cari topik, pilih hasil berlisensi kompatibel dan impor full-text (bukan abstrak saja).
3. Tab **Cek dokumen**: unggah proposal, pilih sumber, atur ambang minimum kesamaan kata, pilih pengecualian daftar pustaka/kutipan.
4. Lihat skor, daftar sumber dan bagian yang diberi highlight, lalu unduh laporan HTML. Di browser buka HTML → Print → Save as PDF.

## 6. Cara perhitungan dan keterbatasan

- Teks difragmentasi menjadi token kata Unicode dalam urutan semula.
- N-gram berurutan dari korpus jurnal diindeks untuk mencari frasa dokumen yang sama persis.
- Pasangan frasa diperpanjang sampai kata yang tidak lagi sama dan diprioritaskan dari yang terpanjang.
- Setiap kata dokumen hanya dihitung sekali. **Similarity % = jumlah kata cocok unik / jumlah kata dokumen yang ikut dihitung × 100**.
- Daftar pustaka dapat dikecualikan dari titik heading yang cocok; opsi kutipan mengabaikan teks dalam tanda kutip, tidak otomatis mengenali semua gaya sitasi.
- Sistem **tidak** mampu mencari seluruh internet atau database privat Turnitin. Skor dapat rendah karena kurangnya sumber, bukan karena pasti orisinal.
- Tidak mendeteksi parafrase atau plagiarisme lintas bahasa. Perlu modul semantik terpisah dan validasi agar tidak menghasilkan false positive.
- Batas awal: 15 MB per file, 400 halaman per PDF, 300 sumber ditampilkan/diambil, 1,5 juta token sumber per pemeriksaan agar ramah hosting gratis.
- Teks PDF hasil scan tidak dibaca tanpa OCR.

## 7. Proteksi data penting

- Repositori GitHub tidak boleh mengandung proposal pribadi, PDF sumber berhak cipta, database lokal, atau API key.
- `APP_PASSWORD` melindungi tampilan, tetapi hanya cocok untuk pemilik tunggal atau kelompok kecil yang saling percaya; belum ada pemisahan data antar pengguna.
- Kunci `sb_secret_*` di Secrets server; **jangan** gunakan kunci anon/publishable sebagai pengganti.
- Untuk data yang perlu kepatuhan institusional, gunakan pengaturan privasi/retensi dan infrastruktur yang lebih sesuai.
- Saat melakukan impor dari OpenAlex, baca lisensi setiap publikasi. Aplikasi hanya mempertahankan data teks pada private DB, tidak membuka endpoint publik untuk sumber utuh.

## 8. Roadmap agar lebih dekat ke sistem similarity komersial

1. **Tahap MVP (sudah ada)**: upload, ingestion OpenAlex CC, korpus persisten, n-gram exact match, sumber cocok, highlight, HTML report.
2. **Tahap berikutnya**: penelusuran kandidat dari banyak OA sumber secara otomatis, BM25/FTS5/pgvector, indeks persisten per paragraf; impor terjadwal berizin dengan antrean dan quota management.
3. **Tahap lanjut**: paraphrase detection multilingual yang telah dievaluasi, OCR PDF scan, deteksi kutipan/sitasi berbasis struktur, antarmuka review per halaman, ekspor PDF formal, audit log.
4. **Tahap produksi**: identitas masing-masing pengguna, row-level access per pengguna, kebijakan retensi dan penghapusan, pengujian precision/recall/F1 terhadap corpus berlabel, monitoring dan pembatasan abuse.

## Lisensi kode

Contoh aplikasi ini dapat disesuaikan untuk kebutuhan akademik pribadi. Penggunaan konten ilmiah mengikuti lisensi masing-masing publikasi, terpisah dari kode aplikasi.
