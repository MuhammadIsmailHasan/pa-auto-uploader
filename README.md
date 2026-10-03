# Auto PDF Uploader — Panduan Instalasi (Dev & Prod)

Aplikasi Flask + MySQL/MariaDB untuk mengimpor, mengidentifikasi (OCR), memverifikasi, me-rename, dan mengunggah PDF perkara via Selenium. Source ada di `aplikasi/`.

> Target utama: **Ubuntu/Debian 64-bit**. Pengguna Windows disarankan memakai **WSL2 Ubuntu** untuk dev.

## Struktur repo

| Path | Isi |
|---|---|
| `aplikasi/` | Source code, template, config contoh, skrip |
| `database/` | Dump database aplikasi (data operasional, **sensitif**) |
| `KONFIGURASI.env.example` | Contoh `.env` untuk server produksi |
| `README-PINDAH-SERVER.md` | Panduan lengkap migrasi dari server lama |
| `aplikasi/PETUNJUK_TEKNIS_AUTO_PDF_UPLOADER.md` | Petunjuk teknis aplikasi |

## Prasyarat umum

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip python3-dev \
  default-libmysqlclient-dev mariadb-server mariadb-client \
  tesseract-ocr tesseract-ocr-ind poppler-utils \
  chromium-browser chromium-chromedriver
```

Versi Chrome/Chromium dan ChromeDriver harus cocok:

```bash
chromium --version; chromedriver --version
```

---

## 1. Instalasi DEV (lokal)

Tujuan: mencoba/mengembangkan aplikasi tanpa menyentuh data produksi.

### 1.1 Ambil kode & virtualenv

```bash
git clone git@github.com:MuhammadIsmailHasan/pa-auto-uploader.git
cd pa-auto-uploader/aplikasi
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip wheel setuptools
pip install -r requirements.txt
```

### 1.2 Database dev (kosong)

```bash
sudo mysql <<'SQL'
CREATE DATABASE IF NOT EXISTS perkara_pdf_manager_dev
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'perkara_dev'@'localhost' IDENTIFIED BY 'dev-password';
GRANT ALL PRIVILEGES ON perkara_pdf_manager_dev.* TO 'perkara_dev'@'localhost';
FLUSH PRIVILEGES;
SQL
```

> Disarankan **tidak** memuat dump produksi di dev karena berisi data perkara dan akun upload. Jika terpaksa, batasi aksesnya dan nonaktifkan akun upload setelah restore.

### 1.3 Folder data dev

Gunakan folder di dalam home, bukan `/srv`:

```bash
mkdir -p ~/pdf_dev/{dokumen_perkara,processed,previews,hasil_identifikasi,uploaded}
```

### 1.4 `.env` dev

```bash
cp .env.example .env
```

Isi minimal:

```ini
FLASK_ENV=development
SECRET_KEY=dev-secret-bebas
DATABASE_URL=mysql+pymysql://perkara_dev:dev-password@127.0.0.1/perkara_pdf_manager_dev?charset=utf8mb4

IMPORT_SOURCE_DIR=/home/USER/pdf_dev/dokumen_perkara
STORAGE_DIR=/home/USER/pdf_dev/processed
PREVIEW_DIR=/home/USER/pdf_dev/previews
EXPORT_DIR=/home/USER/pdf_dev/hasil_identifikasi
UPLOADED_DIR=/home/USER/pdf_dev/uploaded
LOG_DIR=/home/USER/pa-auto-uploader/aplikasi/logs

OCR_LANG=ind
RENAME_APPLY=false          # JANGAN true di dev
SELENIUM_BROWSER=chrome
SELENIUM_HEADLESS=false
TARGET_LOGIN_URL=           # kosongkan agar upload tidak bisa jalan tak sengaja
TARGET_USERNAME=
TARGET_PASSWORD=
TARGET_SELECTORS_FILE=/home/USER/pa-auto-uploader/aplikasi/config/selenium_selectors.example.json

# Hanya bila perlu daftar Panitera/PP; gunakan akun READ-ONLY
SIPP_RO_HOST=192.168.1.7
SIPP_RO_PORT=3306
SIPP_RO_DATABASE=sipp
SIPP_RO_USER=
SIPP_RO_PASSWORD=
```

Ganti `USER` dengan nama user Anda.

### 1.5 Jalankan

```bash
flask --app app init-db
python scripts/healthcheck.py
flask --app app run --debug --host 127.0.0.1 --port 8000
```

Buka <http://127.0.0.1:8000/>.

### 1.6 Tes & CLI

```bash
python -m pytest tests/            # jika pytest terpasang: pip install pytest

flask --app app import-pdfs
flask --app app process-documents --limit 5
flask --app app rename-documents --limit 5      # simulasi selama RENAME_APPLY=false
```

Hindari `upload-documents` di dev kecuali menunjuk ke SIPP uji.

---

## 2. Instalasi PROD

Detail lengkap dan skenario cutover dari server lama ada di [`README-PINDAH-SERVER.md`](README-PINDAH-SERVER.md). Ringkasannya:

### 2.1 Salin aplikasi

Pakai path bawaan agar service dan shortcut cocok.

```bash
sudo mkdir -p /home/panitera/perkara_pdf_manager
sudo rsync -a aplikasi/ /home/panitera/perkara_pdf_manager/
sudo chown -R panitera:panitera /home/panitera/perkara_pdf_manager
cd /home/panitera/perkara_pdf_manager

sudo -u panitera python3 -m venv .venv
sudo -u panitera .venv/bin/pip install --upgrade pip wheel setuptools
sudo -u panitera .venv/bin/pip install -r requirements-frozen.txt   # versi persis server lama
# alternatif: requirements.txt (versi mengikuti rentang)
```

### 2.2 Database

```bash
sudo mysql <<'SQL'
CREATE DATABASE IF NOT EXISTS perkara_pdf_manager
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'perkara_user'@'localhost' IDENTIFIED BY 'PASSWORD_KUAT';
GRANT ALL PRIVILEGES ON perkara_pdf_manager.* TO 'perkara_user'@'localhost';
FLUSH PRIVILEGES;
SQL

# Opsional: restore data
mysql -u perkara_user -p perkara_pdf_manager < database/perkara_pdf_manager_2026-10-03.sql
```

### 2.3 Folder data

Pertahankan path `/srv/perkara_pdf_manager` karena record database menyimpan path file.

```bash
sudo mkdir -p /srv/perkara_pdf_manager/{dokumen_perkara,processed,previews,hasil_identifikasi,uploaded,rekaman_upload}
sudo chown -R panitera:panitera /srv/perkara_pdf_manager
```

### 2.4 `.env` produksi

```bash
cd /home/panitera/perkara_pdf_manager
cp KONFIGURASI.env.example .env      # salin dari root paket
chmod 600 .env
nano .env
```

Wajib diisi: `SECRET_KEY` (`openssl rand -hex 32`), `DATABASE_URL`, `SIPP_RO_*`, `REGISTRATION_TEMPLATE_DIR`, `REGISTRATION_SIGNATURE_DIR`.
Biarkan `RENAME_APPLY=false` sampai hasil identifikasi dan simulasi rename terverifikasi.
Jangan pernah commit `.env` (sudah ada di `.gitignore`).

### 2.5 Inisialisasi & tes

```bash
. .venv/bin/activate
flask --app app init-db
python scripts/healthcheck.py
```

### 2.6 Service systemd (gunicorn)

```bash
sudo cp config/perkara-pdf-manager.migrasi.service.example \
  /etc/systemd/system/perkara-pdf-manager.service
sudo nano /etc/systemd/system/perkara-pdf-manager.service   # cek User, path
sudo systemctl daemon-reload
sudo systemctl enable --now perkara-pdf-manager
systemctl status perkara-pdf-manager
journalctl -u perkara-pdf-manager -n 100 --no-pager
```

Service menjalankan: `gunicorn --workers 2 --timeout 600 --bind 0.0.0.0:8000 wsgi:application`.

### 2.7 Reverse proxy Apache (opsional, disarankan)

```bash
sudo apt install -y apache2
sudo a2enmod proxy proxy_http
sudo cp config/apache-perkara-pdf-manager.conf.example \
  /etc/apache2/sites-available/perkara-pdf-manager.conf
sudo nano /etc/apache2/sites-available/perkara-pdf-manager.conf   # ganti ServerName
sudo a2ensite perkara-pdf-manager
sudo systemctl reload apache2
```

Jika memakai proxy, ubah `--bind` gunicorn menjadi `127.0.0.1:8000` agar port 8000 tidak terbuka langsung. Batasi akses dengan firewall; **jangan expose ke internet**.

### 2.8 Timer upload BAS (opsional)

```bash
sudo cp config/wicaksana-bas-upload.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now wicaksana-bas-upload.timer
```

Sesuaikan path, user, dan `DISPLAY=:0` sebelum dipasang.

### 2.9 Konfigurasi akun upload

Login ke dashboard, buka **Pengaturan Akun Upload**, lalu isi ulang URL login, username, password, peran, status aktif, dan mapping Panitera/PP. Uji upload pada **satu dokumen** sebelum batch besar.

---

## Perbedaan Dev vs Prod

| Aspek | Dev | Prod |
|---|---|---|
| Server | `flask run --debug` | gunicorn via systemd (+ Apache) |
| Bind | `127.0.0.1:8000` | `0.0.0.0:8000` atau `127.0.0.1` di belakang proxy |
| Database | `perkara_pdf_manager_dev`, kosong | `perkara_pdf_manager`, hasil restore |
| Data | `~/pdf_dev/...` | `/srv/perkara_pdf_manager/...` |
| `FLASK_ENV` | `development` | `production` |
| `RENAME_APPLY` | `false` | `false` dulu, `true` setelah verifikasi |
| Target upload | Kosong / SIPP uji | SIPP produksi |
| Dependency | `requirements.txt` | `requirements-frozen.txt` |

## Troubleshooting

| Gejala | Cek |
|---|---|
| Tidak bisa konek DB | `DATABASE_URL`, service MariaDB, hak user |
| Daftar Panitera/PP kosong | Jaringan ke `SIPP_RO_HOST:3306` dan akun read-only |
| OCR gagal | `tesseract-ocr-ind` terpasang, `OCR_LANG=ind` |
| Preview kosong | File PDF belum disalin atau path berbeda |
| Selenium gagal | Versi Chrome = ChromeDriver; cek `SELENIUM_HEADLESS` dan `DISPLAY` |
| Upload dobel | Pastikan service/timer server lama sudah dihentikan |
| Request timeout | Naikkan `--timeout` gunicorn dan `ProxyTimeout` Apache |

## Keamanan

- `.env`, dump database, dan akun upload bersifat sensitif; jangan di-commit atau dibagikan.
- Gunakan akun SIPP **read-only** untuk `SIPP_RO_*`.
- Jangan jalankan dua instance yang sama-sama mengunggah.
