# Auto PDF Uploader

Aplikasi Flask untuk mengimpor, membaca, mengidentifikasi, memverifikasi, me-rename, dan mengunggah dokumen perkara PDF melalui alur resmi aplikasi perkara menggunakan Selenium.

## Fitur

- Import massal PDF dari folder tanpa mengulang dokumen yang sudah tercatat.
- Ekstraksi teks PDF digital memakai `pdfplumber`.
- OCR PDF scan memakai `pdf2image` dan Tesseract bahasa Indonesia.
- Regex nomor perkara fleksibel, misalnya `123/Pdt.G/2025/PA.Ngw` dan `123/Pdt.P/2025/PA.Ngw`.
- Identifikasi jenis dokumen berbasis kata kunci.
- Dashboard status: baru, teridentifikasi, perlu verifikasi, siap upload, berhasil upload, gagal upload.
- Verifikasi manual, koreksi nomor perkara/jenis dokumen, preview halaman pertama PDF.
- Rename file otomatis setelah verifikasi.
- Upload otomatis via Selenium dengan log proses, tanpa manipulasi database/storage aplikasi perkara.

## Prasyarat Ubuntu

```bash
sudo apt update
sudo apt install -y python3-venv python3-dev default-libmysqlclient-dev \
  tesseract-ocr tesseract-ocr-ind poppler-utils
```

Chrome/Edge dan WebDriver harus tersedia di server bila modul upload otomatis dipakai.

## Instalasi

```bash
cd /home/panitera/perkara_pdf_manager
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Buat database MySQL:

```sql
CREATE DATABASE perkara_pdf_manager CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'perkara_user'@'localhost' IDENTIFIED BY 'password-kuat';
GRANT ALL PRIVILEGES ON perkara_pdf_manager.* TO 'perkara_user'@'localhost';
FLUSH PRIVILEGES;
```

Sesuaikan `DATABASE_URL` dan path folder di `.env`, lalu inisialisasi tabel:

```bash
flask --app app init-db
```

Atau jalankan SQL manual:

```bash
mysql -u perkara_user -p perkara_pdf_manager < scripts/schema.sql
```

## Menjalankan

```bash
flask --app app run --host 0.0.0.0 --port 8000
```

Untuk Apache, gunakan `gunicorn` di belakang reverse proxy atau mod_wsgi sesuai standar server setempat.

## Perintah CLI

```bash
flask --app app import-pdfs
flask --app app process-documents --limit 50
flask --app app rename-documents --limit 50
flask --app app upload-documents --limit 10
```

`RENAME_APPLY=false` membuat rename berjalan mode simulasi. Ubah menjadi `true` setelah hasil verifikasi benar.

## Apache dan systemd

Contoh tersedia di:

- `config/perkara-pdf-manager.service.example`
- `config/apache-perkara-pdf-manager.conf.example`

Jalankan aplikasi dengan systemd/gunicorn pada port lokal, lalu aktifkan modul Apache `proxy` dan `proxy_http`.
