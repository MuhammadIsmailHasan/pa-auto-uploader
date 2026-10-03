"""Check SIPP and upload only the explicitly selected document IDs."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app, db
from app.models import Document, DocumentStatus, UploadAccount, UploadLog
from app.services.uploader import SeleniumConfig, upload_ready_documents


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ids", nargs="+", type=int)
    parser.add_argument("--apply", action="store_true", help="Check SIPP and upload missing PDFs")
    args = parser.parse_args()
    wanted = set(args.ids)
    app = create_app()
    with app.app_context():
        documents = Document.query.filter(Document.id.in_(wanted)).order_by(Document.id).all()
        if {document.id for document in documents} != wanted:
            raise SystemExit("Salah satu ID dokumen tidak ditemukan.")
        for document in documents:
            if document.status not in (DocumentStatus.READY_UPLOAD, DocumentStatus.UPLOAD_FAILED):
                raise SystemExit(f"Dokumen {document.id} berstatus {document.status}; upload dihentikan.")
            if not document.is_verified or not document.case_number or not document.document_type:
                raise SystemExit(f"Dokumen {document.id} belum terverifikasi.")
            if not Path(document.file_path).is_file():
                raise SystemExit(f"File dokumen {document.id} tidak ditemukan.")
            print(f"{document.id}: {document.case_number} {document.document_type} ({document.status})", flush=True)
        if not args.apply:
            return

        for document in documents:
            if document.status == DocumentStatus.UPLOAD_FAILED:
                document.status = DocumentStatus.READY_UPLOAD
                document.error_message = None
                db.session.add(UploadLog(
                    document_id=document.id,
                    status="ulang",
                    message="Disiapkan ulang untuk pengecekan PDF SIPP dan upload terpilih.",
                ))
        db.session.commit()

        accounts = UploadAccount.query.filter_by(is_active=True).all()
        accounts_by_role = {account.role.strip().lower(): account for account in accounts}
        config = SeleniumConfig(
            browser=app.config["SELENIUM_BROWSER"],
            headless=app.config["SELENIUM_HEADLESS"],
            login_url="",
            username="",
            password="",
            selectors_file=app.config["TARGET_SELECTORS_FILE"],
            uploaded_dir=app.config["UPLOADED_DIR"],
            slow_mode=app.config["SELENIUM_HUMAN_DELAY"],
            keep_browser_open=False,
        )
        upload_ready_documents(
            limit=None,
            config=config,
            accounts_by_role=accounts_by_role,
            roles={"panitera", "hakim"},
            document_filter=lambda document: document.id in wanted,
            progress_callback=lambda index, total, document: print(
                f"Proses {index}/{total}: {document.id} {document.case_number} {document.document_type}", flush=True
            ),
        )
        for document in documents:
            db.session.refresh(document)
            print(f"HASIL {document.id}: {document.status} {(document.error_message or '')[:180]}", flush=True)


if __name__ == "__main__":
    main()
