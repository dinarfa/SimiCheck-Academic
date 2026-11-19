# SimiCheck Academic

Pemeriksa kemiripan dokumen akademik berbasis Streamlit. Bandingkan proposal, skripsi, atau dokumen lain dengan koleksi privat, artikel open-access yang ditemukan melalui OpenAlex, atau gabungan kedua sumber.

## Jalankan secara lokal

Gunakan Python 3.12 atau 3.13.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m streamlit run app.py
```

Pada macOS atau Linux, gunakan `.venv/bin/python`. Mode lokal memakai `local_sources.sqlite3` saat konfigurasi Supabase kosong. Tanpa kata sandi aplikasi, pakai mode ini hanya pada perangkat sendiri.

## Konfigurasi Supabase dan Streamlit Community Cloud

1. Untuk database baru, jalankan [schema.sql](schema.sql) di Supabase SQL Editor. Aplikasi memakai tabel `public.sources` dengan Row Level Security.
2. Pada instalasi yang sudah berjalan, pertahankan tabel dan data jurnal yang ada. [Skrip izin opsional](migrations/001_sources_access.sql) menghapus hak langsung untuk peran `anon` dan `authenticated` pada tabel sumber dan memberi backend operasi baca, tambah, dan hapus. Tinjau pemakai tabel lain sebelum menjalankannya. Skrip hanya mengubah hak akses.
3. Gunakan entry point `app.py` dan Python 3.12 atau 3.13 di Streamlit Community Cloud. `requirements.txt` berisi paket Python. `packages.txt` memasang font DejaVu untuk PDF.
4. Masukkan konfigurasi di **Streamlit Secrets** untuk deployment. Untuk pengembangan lokal, gunakan variabel lingkungan atau `.streamlit/secrets.toml` yang diabaikan Git.

| Nama konfigurasi | Kegunaan |
|---|---|
| `APP_PASSWORD` | Wajib bersama Supabase. Gunakan kata sandi kuat yang disimpan pada server. |
| `SUPABASE_URL` | URL proyek Supabase melalui HTTPS. |
| `SUPABASE_SECRET_KEY` | Kunci rahasia backend. Instalasi lama juga dapat memakai `SUPABASE_SERVICE_ROLE_KEY`. |
| `OPENALEX_API_KEY` | Aktifkan pencarian dan unduhan XML dari OpenAlex. |
| `SIMICHECK_SEMANTIC` | Opsional. Nilai `true` menampilkan pilihan parafrase eksperimental. |

Simpan API key dan kata sandi di pengaturan server. Hindari memasukkan laporan, file sumber privat, database lokal, dan model unduhan ke Git. Aktifkan visibilitas privat di Community Cloud untuk membatasi siapa yang dapat menjangkau aplikasi. Kata sandi bersama memberi akses koleksi yang sama kepada pemegangnya. Untuk penggunaan kampus dengan pemisahan per pengguna, gunakan rancangan Supabase Auth, identitas pengguna, dan kebijakan akses per baris.

## Alur penggunaan

- **Dasbor** menampilkan sumber terbaru dan hasil pemeriksaan yang tersedia pada sesi aktif.
- **Koleksi sumber** menerima PDF, DOCX, dan TXT. Tinjau nama, ukuran, status, serta duplikat SHA-256, lalu pilih file yang akan diimpor. Batasnya 15 MB per file dan 12 file atau 45 MB per batch. Hasil impor ditampilkan per file. Koleksi dapat dicari, diurutkan, difilter, dan dihapus dengan konfirmasi.
- **Jelajahi OpenAlex** mencari artikel untuk diimpor ke koleksi. Mode **OpenAlex otomatis** di halaman **Periksa kemiripan** mengambil XML berlisensi langsung untuk satu pemeriksaan. Tinjau kata kunci hasil ekstraksi lokal dan setujui pengirimannya sebelum menjalankan pencarian otomatis. Teks dokumen dan embedding tetap diproses di server aplikasi.
- **Periksa kemiripan** menerima satu dokumen, kemudian meminta pengguna memilih mode dan ambang pencocokan. Pilihan koleksi memuat hingga 300 metadata terbaru dan hanya mengambil teks dari maksimal 12 sumber terpilih. Sejumlah kandidat dapat dilewati berdasarkan lisensi, ketersediaan isi, atau batas pemrosesan. Hasil mencantumkan jumlah sumber yang diperiksa dan pesan cakupan.
- **Laporan** menampilkan skor, jumlah kata, pengecualian, waktu WITA, daftar sumber, dan bukti yang bisa ditinjau. PDF A4 dan HTML memuat teks dokumen dengan sorotan. CSV berisi daftar sumber dan JSON berisi ringkasan serta pasangan bukti. Untuk laporan besar, PDF menampilkan hingga 150 pasangan detail. Teks dan sorotan tetap lengkap. HTML dan JSON mencantumkan semua pasangan.
- **Pengaturan** menampilkan status konfigurasi dan menyediakan penghapusan dokumen serta laporan dari sesi. Keluar juga membersihkan state sesi. Pemeriksaan tidak menulis dokumen ke database. Impor ke koleksi menyimpan teks sumber setelah dikonfirmasi.

## Cara membaca hasil

**Kemiripan teks langsung (%) = token dokumen yang tercakup oleh kecocokan valid ? token yang dianalisis ? 100.** N-gram membandingkan urutan kata Unicode dan memprioritaskan rentang yang lebih panjang. Setiap token memperoleh paling banyak satu atribusi. Ambang dan pengecualian pada laporan membantu menjelaskan perbedaan antarpemeriksaan.

Indikasi parafrase menggunakan model multibahasa E5 Small terkuantisasi. Bobot model publik diunduh pertama kali, diperiksa dengan SHA-256, dan disimpan dalam `.simicheck-models/`. Dokumen tidak dikirim ke penyedia model. Fitur mengambil paling banyak 64 segmen dokumen dan 120 segmen sumber. Laporan mencantumkan jumlah segmen yang disampel dan skor kosinus untuk setiap pasangan. Temuan semantik dihitung terpisah dari persentase teks langsung. Fitur ini tetap eksperimental karena kalimat bertopik sama dapat melebihi ambang.

Skor berlaku untuk sumber yang benar-benar diperiksa. Turnitin memiliki korpus dan metode penilaian sendiri. Gunakan bukti pencocokan, konteks, dan sitasi untuk menilai temuan. PDF hasil pindai memerlukan OCR terlebih dahulu. SimiCheck menyampaikan kondisi tanpa sumber yang dapat dibandingkan melalui status pemeriksaan.

## Lisensi dan batas pemrosesan

- OpenAlex menyediakan metadata lisensi dan lokasi. Pemeriksaan memilih CC BY, CC BY-SA, CC0, atau penanda domain publik yang tercantum. XML yang menyatakan lisensi Creative Commons yang bertentangan dilewati. Laporan menyertakan judul, tautan, lisensi, dan atribut lain sejauh tersedia. Izin penggunaan mengikuti lisensi artikel. [OpenAlex Fulltext](https://help.openalex.org/access/fulltext/) dan [Creative Commons](https://creativecommons.org/share-your-work/use-remix/cc-licenses/).
- Setiap pemeriksaan otomatis menggunakan hingga tiga kueri dan tiga kandidat unduhan. Percobaan ulang HTTP dibatasi. Aplikasi memiliki batas proses harian 150 percobaan kueri dan 75 percobaan unduhan UTC, dengan kuota akun tetap ditegakkan oleh OpenAlex. Batas lokal dimulai ulang bersama proses server. [Biaya dan kuota OpenAlex](https://help.openalex.org/access/example-costs/).
- Batas pemeriksaan adalah 40.000 token dokumen dan 250.000 token sumber. PDF dibatasi 400 halaman. Satu pemeriksaan berjalan per proses agar penggunaan RAM tetap terkendali. Cache artikel publik dibatasi 16 entri dan 30 menit. Cache metadata koleksi dibatasi per sesi. Model semantik dimuat hanya ketika dijalankan.
- Periksa performa dengan dokumen dan tingkat penggunaan yang mewakili kondisi Anda. Resource Community Cloud dapat berubah. [Batas Streamlit Community Cloud](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app).

## Pengujian

```powershell
.venv\Scripts\python -B -m unittest discover -s tests -v
```

GitHub Actions menjalankan pengujian pada Python 3.12 dan 3.13 tanpa kredensial. Tes mencakup N-gram dan pengecualian, format file, SQLite, respons tiruan Supabase dan OpenAlex, alur Streamlit, serta ekspor. Model dapat disiapkan untuk pengujian lokal dengan `python -m semantic`.

| Fase | Cara menguji manual |
|---|---|
| Audit dan arsitektur | Jalankan aplikasi dengan SQLite sementara. Periksa login, koleksi, pemeriksaan, dan hasil ekspor pada dokumen uji. |
| Fondasi UI | Gunakan Tab dan Enter untuk login, pindah halaman, dan keluar. Coba kata sandi yang salah. Uji pada lebar ponsel, pembesaran browser, dan pembaca layar sebelum publikasi. |
| Unggahan dan koleksi | Pilih satu TXT valid, satu salinan, dan satu file rusak. Keluarkan satu file dari pilihan, konfirmasi impor, lalu periksa hasil, filter, pagination, dan konfirmasi hapus. |
| Pemeriksaan | Unggah dokumen yang diketahui ada kecocokannya. Uji masing-masing mode, opsi daftar pustaka dan kutipan, serta kasus koleksi kosong atau OpenAlex gagal. |
| Laporan dan ekspor | Pilih beberapa pasangan bukti dari sumber berbeda. Unduh keempat format. Buka PDF multi-halaman dan PDF 0%, lalu cocokkan statistik, tautan, dan sorotan dengan tampilan. |
| Privasi dan performa | Hapus dokumen dari sesi dan masuk kembali. Pada deployment uji, ukur waktu dan memori dengan beberapa sesi, cek hak akses Supabase, kuota OpenAlex, dan kondisi setelah app mulai ulang. |

Struktur proyek dipisah antara antarmuka (`app.py`, `ui_*.py`, `source_library.py`), alur dan mesin (`workflow.py`, `engine.py`, `semantic.py`), sumber data (`storage.py`, `openalex.py`, `fileparser.py`), dan laporan (`report.py`, `pdf_report.py`).

## Lisensi kode

Contoh aplikasi ini dapat disesuaikan untuk kebutuhan akademik pribadi. Penggunaan konten ilmiah mengikuti lisensi masing-masing publikasi, terpisah dari kode aplikasi.
