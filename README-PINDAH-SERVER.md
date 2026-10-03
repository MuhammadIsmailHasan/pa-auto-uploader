# Panduan Pindah Server Auto PDF Uploader

Paket dibuat pada **3 Oktober 2026** dari instalasi aktif:

- aplikasi asal: `/home/panitera/perkara_pdf_manager`
- database aplikasi: `perkara_pdf_manager` (MySQL/MariaDB)
- folder data dokumen aktif: `/srv/perkara_pdf_manager`

## Isi paket

- `aplikasi/` — source code dan template dokumen aplikasi.
- `auto_pdf_uploader_source_2026-10-03.tar.gz` — arsip source yang sama; lebih aman untuk dipindah antar-filesystem.
- `database/perkara_pdf_manager_2026-10-03.sql` — dump database aplikasi.
- `KONFIGURASI.env.example` — contoh lengkap konfigurasi server baru tanpa kata sandi.
- `MANIFEST.txt` — ringkasan isi, versi, dan hal yang tidak disertakan.
- `SHA256SUMS` — checksum untuk memeriksa keutuhan file setelah disalin.

Virtual environment `.venv`, log, cache Python, dan `.env` aktif sengaja tidak disalin. Virtual environment harus dibuat ulang agar cocok dengan Python di server baru. `.env` aktif tidak disertakan karena berisi kata sandi database dan SIPP.

## Hal penting sebelum instalasi

1. Gunakan Ubuntu/Debian 64-bit dan akun Linux khusus, misalnya `panitera`.
2. Server baru harus dapat mengakses:
   - MySQL/MariaDB lokal untuk database aplikasi;
   - database SIPP `192.168.1.7:3306` secara **read-only**;
   - halaman login SIPP dari browser Chrome/Chromium;
   - share `/mnt/server_data_new_kepaniteraan` bila fitur dokumen pendaftaran memakai template dari share tersebut.
3. Jangan menjalankan aplikasi lama dan baru untuk upload pada saat bersamaan. Itu dapat membuat dua proses mengunggah dokumen yang sama.
4. Database dump memuat data operasional dan akun upload yang tersimpan oleh aplikasi. Batasi akses ke paket ini.

## 1. Salin aplikasi ke server baru

Contoh di bawah memakai lokasi yang sama seperti server lama agar service dan shortcut bawaan tetap cocok:

```bash
sudo mkdir -p /home/panitera/perkara_pdf_manager
sudo rsync -a "aplikasi/" /home/panitera/perkara_pdf_manager/
sudo chown -R panitera:panitera /home/panitera/perkara_pdf_manager
cd /home/panitera/perkara_pdf_manager
```

Sebagai alternatif, ekstrak arsip source:

```bash
sudo mkdir -p /home/panitera/perkara_pdf_manager
sudo tar -xzf auto_pdf_uploader_source_2026-10-03.tar.gz \
  -C /home/panitera/perkara_pdf_manager
sudo chown -R panitera:panitera /home/panitera/perkara_pdf_manager
```

Jika nama user atau lokasi aplikasi berbeda, sesuaikan seluruh path `/home/panitera/perkara_pdf_manager` pada `.env`, file service di `config/`, dan shortcut di `desktop_shortcuts/`.

## 2. Pasang paket sistem dan dependency Python

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip python3-dev \
  default-libmysqlclient-dev mariadb-client \
  tesseract-ocr tesseract-ocr-ind poppler-utils \
  chromium-browser chromium-chromedriver

cd /home/panitera/perkara_pdf_manager
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip wheel setuptools
pip install -r requirements.txt
```

Nama paket Chromium dapat berbeda menurut versi Ubuntu. Google Chrome juga dapat dipakai. Pastikan browser dan WebDriver kompatibel:

```bash
google-chrome --version 2>/dev/null || chromium --version
chromedriver --version
```

## 3. Buat dan pulihkan database

Buat user database khusus. Ganti `PASSWORD_DB_BARU` dengan password yang kuat:

```bash
sudo mysql <<'SQL'
CREATE DATABASE IF NOT EXISTS perkara_pdf_manager
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'perkara_user'@'localhost'
  IDENTIFIED BY 'PASSWORD_DB_BARU';
ALTER USER 'perkara_user'@'localhost'
  IDENTIFIED BY 'PASSWORD_DB_BARU';
GRANT ALL PRIVILEGES ON perkara_pdf_manager.*
  TO 'perkara_user'@'localhost';
FLUSH PRIVILEGES;
SQL
```

Pulihkan dump:

```bash
mysql -u perkara_user -p perkara_pdf_manager \
  < "/lokasi/paket/database/perkara_pdf_manager_2026-10-03.sql"
```

Periksa hasilnya:

```bash
mysql -u perkara_user -p -D perkara_pdf_manager -e \
  "SHOW TABLES; SELECT COUNT(*) AS jumlah_dokumen FROM documents;"
```

Database SIPP **tidak** termasuk dump ini. Aplikasi hanya membaca database SIPP melalui akun read-only yang diatur di `.env`.

## 4. Siapkan folder data

Paling aman gunakan path yang sama dengan server lama, karena record database menyimpan path file tersebut:

```bash
sudo mkdir -p /srv/perkara_pdf_manager/{dokumen_perkara,processed,previews,hasil_identifikasi,uploaded,rekaman_upload}
sudo chown -R panitera:panitera /srv/perkara_pdf_manager
```

Paket ini tidak menyertakan folder dokumen operasional `/srv/perkara_pdf_manager` yang berukuran sekitar 11 GB. Jika histori lama harus dapat dipreview atau diunggah kembali, salin data tersebut dari server lama dengan mempertahankan path:

```bash
rsync -aH --info=progress2 \
  SERVER_LAMA:/srv/perkara_pdf_manager/ \
  /srv/perkara_pdf_manager/
```

Jika folder data tidak disalin, aplikasi dan database tetap dapat dipasang, tetapi record lama yang menunjuk file PDF lama tidak dapat dibuka/diproses.

## 5. Buat `.env`

```bash
cd /home/panitera/perkara_pdf_manager
cp "/lokasi/paket/KONFIGURASI.env.example" .env
chmod 600 .env
nano .env
```

Wajib diisi atau diperiksa:

- `SECRET_KEY`: buat nilai acak, misalnya `openssl rand -hex 32`.
- `DATABASE_URL`: samakan user/password database yang dibuat pada langkah 3. Jika password mengandung karakter khusus, lakukan URL-encode.
- `SIPP_RO_HOST`, `SIPP_RO_DATABASE`, `SIPP_RO_USER`, dan `SIPP_RO_PASSWORD`: akun database SIPP khusus baca.
- `REGISTRATION_TEMPLATE_DIR`: lokasi template pendaftaran.
- `REGISTRATION_SIGNATURE_DIR`: lokasi gambar tanda tangan yang digunakan modul dokumen pendaftaran.
- `SELENIUM_BROWSER`: `chrome` atau browser yang tersedia.
- `SELENIUM_HEADLESS=false`: pertahankan `false` bila login/upload membutuhkan browser tampak atau interaksi desktop.
- `RENAME_APPLY=false`: pertahankan sampai hasil identifikasi dan simulasi rename diperiksa.

Akun upload SIPP utama disimpan di database aplikasi. Setelah login ke dashboard, buka menu **Pengaturan Akun Upload**, periksa URL login, username, password, peran, status aktif, dan mapping Panitera/PP. Jangan menganggap kredensial lama masih berlaku.

## 6. Tes sebelum dijadikan service

```bash
cd /home/panitera/perkara_pdf_manager
. .venv/bin/activate
flask --app app init-db
python scripts/healthcheck.py
flask --app app run --host 0.0.0.0 --port 8000
```

Buka `http://IP-SERVER-BARU:8000/`, kemudian periksa:

1. dashboard terbuka;
2. jumlah dokumen sesuai hasil restore;
3. daftar akun upload tampil;
4. koneksi daftar Panitera/PP dari SIPP berhasil;
5. preview satu PDF berhasil (bila data 11 GB ikut disalin);
6. identifikasi satu file uji berhasil;
7. upload diuji pada satu dokumen yang aman sebelum batch besar.

## 7. Jalankan dengan systemd

Salin template, lalu sesuaikan `User`, `Group`, `WorkingDirectory`, `Environment=PATH`, dan `ExecStart` jika lokasi/user berbeda:

```bash
sudo cp config/perkara-pdf-manager.migrasi.service.example \
  /etc/systemd/system/perkara-pdf-manager.service
sudo nano /etc/systemd/system/perkara-pdf-manager.service
sudo systemctl daemon-reload
sudo systemctl enable --now perkara-pdf-manager
sudo systemctl status perkara-pdf-manager
```

Lihat log service:

```bash
journalctl -u perkara-pdf-manager -n 100 --no-pager
```

Port default adalah TCP `8000`. Batasi akses dengan firewall atau reverse proxy; jangan membuka aplikasi langsung ke internet.

## 8. Timer upload BAS (opsional)

File berikut hanya diperlukan bila fitur upload BAS terjadwal dipakai:

- `config/wicaksana-bas-upload.service`
- `config/wicaksana-bas-upload.timer`

Keduanya masih memuat path `/home/panitera/perkara_pdf_manager`, user `panitera`, dan kebutuhan sesi desktop `DISPLAY=:0`. Sesuaikan sebelum dipasang:

```bash
sudo cp config/wicaksana-bas-upload.service /etc/systemd/system/
sudo cp config/wicaksana-bas-upload.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now wicaksana-bas-upload.timer
systemctl list-timers wicaksana-bas-upload.timer
```

## 9. Cutover dari server lama

Urutan yang disarankan:

1. Hentikan aktivitas upload di server lama.
2. Buat dump database terbaru lagi jika database berubah setelah tanggal paket ini.
3. Sinkronkan folder `/srv/perkara_pdf_manager` terakhir kali bila data lama ikut dipindah.
4. Restore dump terakhir di server baru.
5. Jalankan pengujian satu dokumen.
6. Aktifkan service server baru.
7. Setelah server baru stabil, nonaktifkan service/timer server lama.

## Troubleshooting singkat

- **Tidak bisa konek database aplikasi:** cek `DATABASE_URL`, service MariaDB, dan hak user database.
- **Daftar Panitera/PP kosong:** cek akses jaringan ke `SIPP_RO_HOST:3306` serta akun read-only.
- **OCR bahasa Indonesia gagal:** pastikan `tesseract-ocr-ind` terpasang dan `OCR_LANG=ind`.
- **Preview kosong:** cek apakah file PDF lama sudah disalin dan path `/srv/perkara_pdf_manager` sama.
- **Selenium gagal membuka browser:** cocokkan versi Chrome/Chromium dengan ChromeDriver dan cek mode `SELENIUM_HEADLESS`.
- **Upload dobel:** pastikan service/timer server lama sudah dihentikan sebelum server baru aktif.
