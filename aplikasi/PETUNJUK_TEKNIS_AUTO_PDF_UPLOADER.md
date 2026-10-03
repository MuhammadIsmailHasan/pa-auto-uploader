# Petunjuk Teknis Auto PDF Uploader

## Lokasi Aplikasi

- Folder aplikasi: `/home/panitera/perkara_pdf_manager`
- Folder data dokumen: `/srv/perkara_pdf_manager`
- Folder arsip dokumen berhasil: `/srv/perkara_pdf_manager/uploaded`
- URL aplikasi lokal: `http://192.168.1.158:8000/`

## Mapping Akun Upload

Mapping final yang dipakai aplikasi:

| Tombol aplikasi | Jenis dokumen | Target SIPP | Akun |
| --- | --- | --- | --- |
| Upload PMH & PPP | Penetapan Majelis Hakim | Dokumen PMH / `dokpmh` | `mahfudin` |
| Upload PMH & PPP | Penunjukan Panitera | Dokumen PPP / `dokppp` | `mahfudin` |
| Upload JSP | Penunjukan Jurusita | Dokumen PJS / `dokpjs` | `tamaji` |
| Upload PHS | Penetapan Hari Sidang | Dokumen PHS / `dokphs` | akun hakim |

## Logika Pembeda Dokumen

Aplikasi membedakan dokumen dari dua sumber:

1. Hasil OCR isi PDF.
2. Nama file PDF, terutama jika nama file sudah jelas menyebut jenis dokumen.

Nama file dipakai sebagai koreksi kuat agar PMH dan PHS tidak tertukar.

### PMH

PMH adalah `Penetapan Majelis Hakim`.

Aplikasi mengenali sebagai PMH jika teks/nama file mengandung pola seperti:

- `Penetapan Majelis Hakim`
- `Penetapan Hakim`
- `Majelis Hakim`
- `Hakim Tunggal`

Target upload di SIPP:

- Tab `Penetapan`
- Area `Hakim/Majelis Hakim`
- Kolom `Dokumen PMH`
- URL tombol upload mengandung `dokpmh`

Akun upload:

- `mahfudin`

### PPP

PPP adalah `Penunjukan Panitera` atau `Penunjukan Panitera Pengganti`.

Aplikasi mengenali sebagai PPP jika teks/nama file mengandung pola seperti:

- `Penunjukan Panitera`
- `Panitera Pengganti`
- `Menunjuk Panitera Pengganti`

Target upload di SIPP:

- Tab `Penetapan`
- Area `Panitera/Panitera Pengganti`
- Kolom `Dokumen PPP`
- URL tombol upload mengandung `dokppp`

Akun upload:

- `mahfudin`

Catatan: pada akun `tamaji`, tombol PPP tidak muncul pada uji halaman SIPP. Karena itu PPP dipetakan ke akun `mahfudin`.

### JSP / PJS

JSP/PJS adalah dokumen `Penunjukan Jurusita` atau `Jurusita Pengganti`.

Aplikasi mengenali sebagai JSP/PJS jika teks/nama file mengandung pola seperti:

- `Penunjukan Jurusita`
- `Jurusita Pengganti`
- `Menunjuk Jurusita`

Target upload di SIPP:

- Tab `Penetapan`
- Area `Jurusita/Jurusita Pengganti`
- Kolom `Dokumen PJS`
- URL tombol upload mengandung `dokpjs`

Akun upload:

- `tamaji`

### PHS

PHS adalah `Penetapan Hari Sidang`.

Aplikasi mengenali sebagai PHS jika teks/nama file mengandung pola seperti:

- `Penetapan Hari Sidang`
- `Menetapkan Hari Sidang`
- `Hari Sidang Pertama`
- `Hari Sidang`

Target upload di SIPP:

- Tab `Penetapan`
- Area `Hari Sidang Pertama`
- Kolom `Dokumen PHS`
- URL tombol upload mengandung `dokphs`

Akun upload:

- akun hakim

### Urutan dan Aturan Skip

Pada nomor perkara yang sama, aplikasi memproses dokumen dalam urutan:

1. PMH
2. PPP
3. JSP/PJS
4. PHS

Jika tombol/link `Pdf` sudah muncul pada baris dokumen, upload dilewati agar tidak dobel.

Jika perlu upload ulang karena file sebelumnya salah, aplikasi bisa dijalankan dengan mode paksa secara teknis, tetapi mode normal tetap melakukan skip jika PDF sudah ada.

## Alur Upload

1. Aplikasi login ke SIPP sesuai tombol yang dipilih.
2. Aplikasi membuka register berdasarkan nomor perkara:
   - `Pdt.G` masuk Register Induk Perkara Gugatan.
   - `Pdt.P` masuk Register Induk Perkara Permohonan.
3. Aplikasi membuka detail perkara.
4. Aplikasi masuk tab `Penetapan`.
5. Aplikasi cek tombol/link PDF pada baris dokumen.
6. Kalau PDF sudah ada, dokumen dilewati dan ditandai berhasil di aplikasi.
7. Kalau PDF belum ada, aplikasi klik `Unggah`, pilih file PDF, klik `Simpan`, lalu menerima konfirmasi SIPP.
8. Setelah upload, aplikasi cek ulang apakah tombol `Pdf` sudah muncul.
9. Jika valid, file lokal disalin ke `/srv/perkara_pdf_manager/uploaded/<nomor perkara>/`.

## Aturan Nomor Perkara yang Sama

Untuk dokumen yang memakai akun sama dan nomor perkara sama, aplikasi membuka perkara satu kali.

Contoh PMH dan PPP:

1. Buka perkara.
2. Cek/upload PMH.
3. Langsung cek/upload PPP pada halaman yang sama.
4. Baru pindah ke nomor perkara berikutnya.

Jadi aplikasi tidak kembali ke halaman awal jika dokumen berikutnya masih dalam nomor perkara yang sama.

Untuk tombol `Upload Semua Dokumen Penetapan`, akun Mahfudin dipakai dalam satu sesi untuk semua jenis dokumen. Aplikasi membuka satu nomor perkara, lalu memproses dokumen dalam urutan:

1. PMH (`dokpmh`)
2. PPP (`dokppp`)
3. PJS/JSP (`dokpjs`)
4. PHS (`dokphs`)

Setelah keempat slot selesai diperiksa/diunggah, aplikasi kembali ke halaman utama dan mencari nomor perkara berikutnya tanpa login ulang.

## Progress, Pause, dan Jeda Otomatis

Panel progress upload di dashboard menampilkan:

- jumlah dokumen yang sedang diproses,
- pesan status terakhir,
- tombol `Jeda`,
- tombol `Lanjutkan`.

Catatan:

- Pause berlaku di batas aman antar dokumen, bukan di tengah proses kirim file ke SIPP.
- Jika tombol `Jeda` ditekan saat aplikasi sedang mengupload satu file, upload file tersebut diselesaikan dulu, lalu proses berhenti sebelum dokumen berikutnya.
- Setelah setiap 100 dokumen diproses, aplikasi berhenti otomatis selama 30 detik sebelum lanjut.
- Saat jeda otomatis berlangsung, progress menampilkan hitung mundur.

## Koreksi Salah Identifikasi PMH/PHS

Pernah ditemukan beberapa file `Penetapan_Hari_Sidang_*.pdf` teridentifikasi sebagai `Penetapan Majelis Hakim`, dan beberapa file `Penetapan_Majelis_Hakim_*.pdf` teridentifikasi sebagai `Penetapan Hari Sidang`.

Perbaikan yang sudah dilakukan:

- Identifikasi sekarang memakai nama file sebagai koreksi jika nama file jelas menyebut jenis dokumen.
- File dengan nama `Penetapan_Hari_Sidang` dipaksa menjadi `Penetapan Hari Sidang`.
- File dengan nama `Penetapan_Majelis_Hakim` dipaksa menjadi `Penetapan Majelis Hakim`.
- Data lama yang tertukar sudah dikoreksi di database aplikasi.

Catatan penting:

- Jika dokumen yang salah jenis sudah terlanjur masuk ke slot SIPP yang salah, aplikasi tidak otomatis menghapus file di SIPP.
- Perbaikan/hapus file di SIPP perlu dilakukan manual dari SIPP jika diperlukan.

## Menjalankan Ulang Aplikasi

Jika tampilan tombol atau perubahan kode belum muncul:

1. Restart proses Flask.
2. Buka ulang dashboard.
3. Jika browser masih menampilkan tampilan lama, tekan `Ctrl + F5`.

Perintah manual yang biasa dipakai:

```bash
cd /home/panitera/perkara_pdf_manager
.venv/bin/flask --app app run --host 0.0.0.0 --port 8000
```

## Tombol Dashboard

Tombol yang dipakai:

- `Pilih Folder PDF`: memilih folder PDF dari komputer.
- `Identifikasi Semua Dokumen`: membaca dan mengklasifikasi semua dokumen baru.
- `Upload PMH & PPP`: upload PMH dan PPP dengan akun `mahfudin`.
- `Upload JSP`: upload dokumen Jurusita dengan akun `tamaji`.
- `Upload PHS`: upload PHS dengan akun hakim.
