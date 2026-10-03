#!/usr/bin/env bash
set -euo pipefail

OUT_DIR="/srv/perkara_pdf_manager/rekaman_upload"
mkdir -p "$OUT_DIR"
LOG_FILE="$OUT_DIR/rekam.log"

{
  echo "Stop rekam: $(date '+%Y-%m-%d %H:%M:%S')"
  gdbus call \
    --session \
    --dest org.gnome.Shell.Screencast \
    --object-path /org/gnome/Shell/Screencast \
    --method org.gnome.Shell.Screencast.StopScreencast
} >> "$LOG_FILE" 2>&1 || true

echo
echo "Rekaman dihentikan."
echo "File video ada di: $OUT_DIR"
echo
ls -lh "$OUT_DIR" || true
echo
read -r -p "Tekan Enter untuk menutup jendela ini..."
