"""Recover PJS pages from combined PDFs already uploaded as PPP."""

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app
from app.models import Document, DocumentStatus
from app.services.splitter import is_combined_panitera_jurusita, recover_jurusita_from_uploaded_combined


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", default="2026-09-01", help="Tanggal import paling awal (YYYY-MM-DD)")
    parser.add_argument("--apply", action="store_true", help="Buat record PJS yang hilang")
    args = parser.parse_args()
    since = datetime.strptime(args.since, "%Y-%m-%d")
    app = create_app()
    with app.app_context():
        candidates = (
            Document.query.filter(
                Document.created_at >= since,
                Document.document_type == "Penunjukan Panitera",
                Document.status == DocumentStatus.UPLOAD_SUCCESS,
                Document.ocr_text.like("%jurusita%"),
                ~Document.source_path.like("%#split-%"),
            )
            .order_by(Document.id)
            .all()
        )
        for document in candidates:
            if not is_combined_panitera_jurusita(document):
                continue
            existing = Document.query.filter_by(
                source_path=f"{document.source_path}#split-Penunjukan Jurusita"
            ).first()
            if existing:
                continue
            if args.apply:
                recovered = recover_jurusita_from_uploaded_combined(
                    document,
                    preview_dir=app.config["PREVIEW_DIR"],
                    export_dir=app.config["EXPORT_DIR"],
                    lang=app.config["OCR_LANG"],
                    dpi=app.config["OCR_DPI"],
                )
                print(f"{document.case_number}: PJS dibuat sebagai dokumen {recovered.id}")
            else:
                print(f"{document.case_number}: PJS perlu dipulihkan")


if __name__ == "__main__":
    main()
