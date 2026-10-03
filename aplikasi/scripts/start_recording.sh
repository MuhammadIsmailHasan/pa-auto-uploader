#!/usr/bin/env bash
set -euo pipefail

OUT_DIR="/srv/perkara_pdf_manager/rekaman_upload"
mkdir -p "$OUT_DIR"

TEMPLATE="$OUT_DIR/praktik-upload-%d-%t.webm"
LOG_FILE="$OUT_DIR/rekam.log"

{
  echo "Mulai rekam: $(date '+%Y-%m-%d %H:%M:%S')"
  gdbus call \
    --session \
    --dest org.gnome.Shell.Screencast \
    --object-path /org/gnome/Shell/Screencast \
    --method org.gnome.Shell.Screencast.Screencast \
    "$TEMPLATE" \
    "{'draw-cursor': <true>, 'framerate': <15>}"
} >> "$LOG_FILE" 2>&1

echo
echo "Rekaman dimulai."
echo "Praktikkan proses upload di browser."
echo "Jika sudah selesai, jalankan shortcut Stop Rekam Upload dari folder desktop_shortcuts."
echo
echo "Folder hasil: $OUT_DIR"
read -r -p "Tekan Enter untuk menutup jendela ini..."
