#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/home/panitera/perkara_pdf_manager"
cd "$APP_DIR"

echo "== Auto PDF Uploader: instalasi siap pakai =="
echo

echo "1/6 Memasang paket Ubuntu yang dibutuhkan..."
sudo apt-get update
sudo apt-get install -y \
  python3-venv \
  python3-pip \
  python3-dev \
  default-libmysqlclient-dev \
  tesseract-ocr \
  tesseract-ocr-ind \
  poppler-utils

echo
echo "2/6 Membuat virtual environment Python..."
rm -rf .venv
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip wheel setuptools

echo
echo "3/6 Menginstall dependency Python aplikasi..."
pip install -r requirements.txt

echo
echo "4/6 Menyiapkan konfigurasi .env..."
if [ ! -f ".env" ]; then
  cp ".env.example" ".env"
fi

read -r -p "Folder sumber PDF [/srv/perkara_pdf_manager/dokumen_perkara]: " SOURCE_DIR
SOURCE_DIR="${SOURCE_DIR:-/srv/perkara_pdf_manager/dokumen_perkara}"
mkdir -p "$SOURCE_DIR"

read -r -p "Nama database MySQL [perkara_pdf_manager]: " DB_NAME
DB_NAME="${DB_NAME:-perkara_pdf_manager}"
read -r -p "User database aplikasi [perkara_user]: " DB_USER
DB_USER="${DB_USER:-perkara_user}"
read -r -s -p "Password database aplikasi [kosongkan untuk perkara123]: " DB_PASS
echo
DB_PASS="${DB_PASS:-perkara123}"

python - <<PY
from pathlib import Path

env = Path(".env")
text = env.read_text()
updates = {
    "DATABASE_URL": "mysql+pymysql://${DB_USER}:${DB_PASS}@127.0.0.1/${DB_NAME}?charset=utf8mb4",
    "IMPORT_SOURCE_DIR": "${SOURCE_DIR}",
    "STORAGE_DIR": "/srv/perkara_pdf_manager/processed",
    "PREVIEW_DIR": "/srv/perkara_pdf_manager/previews",
    "EXPORT_DIR": "/srv/perkara_pdf_manager/hasil_identifikasi",
    "UPLOADED_DIR": "/srv/perkara_pdf_manager/uploaded",
    "LOG_DIR": "${APP_DIR}/logs",
    "RENAME_APPLY": "false",
}
lines = []
seen = set()
for line in text.splitlines():
    if "=" in line and not line.lstrip().startswith("#"):
        key = line.split("=", 1)[0]
        if key in updates:
            lines.append(f"{key}={updates[key]}")
            seen.add(key)
            continue
    lines.append(line)
for key, value in updates.items():
    if key not in seen:
        lines.append(f"{key}={value}")
env.write_text("\\n".join(lines) + "\\n")
PY

echo
echo "5/6 Membuat database dan tabel MySQL."
echo "Installer akan mencoba sudo mysql. Jika gagal, masukkan password root/admin MySQL."
if sudo mysql <<SQL
CREATE DATABASE IF NOT EXISTS ${DB_NAME} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '${DB_USER}'@'localhost' IDENTIFIED BY '${DB_PASS}';
ALTER USER '${DB_USER}'@'localhost' IDENTIFIED BY '${DB_PASS}';
GRANT ALL PRIVILEGES ON ${DB_NAME}.* TO '${DB_USER}'@'localhost';
FLUSH PRIVILEGES;
SQL
then
  echo "Database dibuat lewat sudo mysql."
else
  mysql -uroot -p <<SQL
CREATE DATABASE IF NOT EXISTS ${DB_NAME} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '${DB_USER}'@'localhost' IDENTIFIED BY '${DB_PASS}';
ALTER USER '${DB_USER}'@'localhost' IDENTIFIED BY '${DB_PASS}';
GRANT ALL PRIVILEGES ON ${DB_NAME}.* TO '${DB_USER}'@'localhost';
FLUSH PRIVILEGES;
SQL
fi

mysql -u"${DB_USER}" -p"${DB_PASS}" "${DB_NAME}" < scripts/schema.sql

echo
echo "6/6 Menjalankan healthcheck aplikasi..."
flask --app app init-db
python scripts/healthcheck.py

echo
echo "Instalasi selesai."
echo "Jalankan shortcut Auto PDF Uploader dari folder desktop_shortcuts"
echo "Buka browser: http://127.0.0.1:8000"
read -r -p "Tekan Enter untuk menutup..."
