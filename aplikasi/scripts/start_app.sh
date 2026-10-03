#!/usr/bin/env bash
set -e

APP_DIR="/home/panitera/perkara_pdf_manager"
cd "$APP_DIR"

if [ ! -f ".env" ]; then
  cp ".env.example" ".env"
  echo "File .env dibuat dari .env.example."
  echo "Silakan cek DATABASE_URL dan IMPORT_SOURCE_DIR bila belum sesuai."
fi

if [ ! -d ".venv" ]; then
  echo "Virtual environment belum ada."
  echo
  echo "Jalankan shortcut Install Auto PDF Uploader dari folder desktop_shortcuts"
  echo "atau jalankan:"
  echo "  $APP_DIR/scripts/install_ready.sh"
  echo
  read -r -p "Tekan Enter untuk menutup..."
  exit 1
fi

source ".venv/bin/activate"
mkdir -p "/srv/perkara_pdf_manager/hasil_identifikasi"
mkdir -p "/srv/perkara_pdf_manager/uploaded"

python - <<'PY'
try:
    import flask
    import flask_sqlalchemy
    import pymysql
except Exception as exc:
    raise SystemExit(f"Dependency Python belum lengkap: {exc}\nJalankan shortcut Install Auto PDF Uploader dari folder desktop_shortcuts")
PY

echo "Menjalankan Auto PDF Uploader..."
echo "Buka di browser: http://127.0.0.1:8000"
echo
flask --app app run --host 0.0.0.0 --port 8000
