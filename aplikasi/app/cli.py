import click
from sqlalchemy import inspect, text

from . import db
from .config import Config
from .models import Document, DocumentStatus, UploadAccount
from .services.importer import import_pdfs
from .services.processor import process_pending_documents
from .services.renamer import rename_ready_documents
from .services.splitter import split_pending_combined_documents
from .services.uploader import ROLE_BAS, SeleniumConfig, is_bas_document, upload_ready_documents
from .services.wicaksana_bas import import_ready_bas, notify_wicaksana, skip_existing_bas_in_sipp


def register_cli(app):
    @app.cli.command("upgrade-bas-automation")
    def upgrade_bas_automation_command():
        migrations = {
            "documents": {
                "source_draft_id": "INT NULL",
                "sipp_hearing_id": "BIGINT NULL",
                "hearing_order": "INT NULL",
                "hearing_date": "DATE NULL",
                "assigned_clerk_id": "INT NULL",
                "assigned_clerk_name": "VARCHAR(255) NULL",
            },
            "upload_accounts": {
                "sipp_panitera_id": "INT NULL",
                "sipp_panitera_name": "VARCHAR(255) NULL",
            },
        }
        schema = inspect(db.engine)
        changed = 0
        for table_name, columns in migrations.items():
            existing = {column["name"] for column in schema.get_columns(table_name)}
            for column_name, definition in columns.items():
                if column_name in existing:
                    continue
                db.session.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"))
                changed += 1
        db.session.commit()
        click.echo(f"Migrasi BAS lokal selesai. Kolom ditambahkan: {changed}.")

    @app.cli.command("init-db")
    def init_db():
        db.create_all()
        click.echo("Tabel database sudah dibuat/diperbarui.")

    @app.cli.command("import-pdfs")
    def import_pdfs_command():
        result = import_pdfs(app.config["IMPORT_SOURCE_DIR"], app.config["STORAGE_DIR"])
        click.echo(
            f"Import selesai. Baru: {result['imported']}, dilewati: {result['skipped']}, gagal: {result['failed']}."
        )

    @app.cli.command("process-documents")
    @click.option("--limit", default=25, show_default=True, type=int)
    def process_documents_command(limit):
        count = process_pending_documents(
            limit=limit,
            lang=app.config["OCR_LANG"],
            dpi=app.config["OCR_DPI"],
            max_ocr_pages=app.config["MAX_OCR_PAGES"],
            preview_dir=app.config["PREVIEW_DIR"],
            export_dir=app.config["EXPORT_DIR"],
        )
        click.echo(f"Memproses {count} dokumen.")

    @app.cli.command("rename-documents")
    @click.option("--limit", default=50, show_default=True, type=int)
    def rename_documents_command(limit):
        count = rename_ready_documents(limit=limit, apply_changes=app.config["RENAME_APPLY"])
        mode = "apply" if app.config["RENAME_APPLY"] else "simulasi"
        click.echo(f"Rename {count} dokumen dalam mode {mode}.")

    @app.cli.command("split-combined-documents")
    @click.option("--limit", default=50, show_default=True, type=int)
    def split_combined_documents_command(limit):
        results = split_pending_combined_documents(
            limit=limit,
            preview_dir=app.config["PREVIEW_DIR"],
            export_dir=app.config["EXPORT_DIR"],
            lang=app.config["OCR_LANG"],
            dpi=app.config["OCR_DPI"],
        )
        created = sum(len(result.created_ids) for result in results)
        click.echo(f"Memeriksa {len(results)} dokumen gabungan. Dokumen baru dibuat: {created}.")

    @app.cli.command("upload-documents")
    @click.option("--limit", default=10, show_default=True, type=int)
    def upload_documents_command(limit):
        config = SeleniumConfig(
            browser=app.config["SELENIUM_BROWSER"],
            headless=app.config["SELENIUM_HEADLESS"],
            login_url="",
            username="",
            password="",
            selectors_file=app.config["TARGET_SELECTORS_FILE"],
            uploaded_dir=app.config["UPLOADED_DIR"],
            slow_mode=app.config["SELENIUM_HUMAN_DELAY"],
            keep_browser_open=app.config["SELENIUM_KEEP_BROWSER_OPEN"],
        )
        accounts_by_role = {
            account.role.strip().lower(): account
            for account in UploadAccount.query.filter_by(is_active=True).all()
        }
        accounts_by_clerk = {
            account.sipp_panitera_id: account
            for account in UploadAccount.query.filter_by(is_active=True).all()
            if account.sipp_panitera_id
        }
        count = upload_ready_documents(
            limit=limit,
            config=config,
            accounts_by_role=accounts_by_role,
            accounts_by_clerk=accounts_by_clerk,
        )
        click.echo(f"Upload diproses untuk {count} dokumen status {DocumentStatus.READY_UPLOAD}.")

    @app.cli.command("import-wicaksana-bas")
    def import_wicaksana_bas_command():
        result = import_ready_bas(app.config["WICAKSANA_BAS_API"])
        click.echo(
            f"BAS: {result['imported']} baru, {result['updated']} diperbarui, {result['missing']} file tidak tersedia."
        )

    @app.cli.command("upload-wicaksana-bas")
    @click.option("--show-browser", is_flag=True, help="Tampilkan Chrome selama upload BAS.")
    def upload_wicaksana_bas_command(show_browser):
        result = import_ready_bas(app.config["WICAKSANA_BAS_API"])
        ready_draft_ids = set(result["ready_ids"])
        click.echo(
            f"Sinkronisasi BAS: {result['imported']} baru, {result['updated']} diperbarui, "
            f"{result['missing']} file tidak tersedia."
        )
        try:
            skipped = skip_existing_bas_in_sipp(app.config, ready_draft_ids)
            click.echo(f"BAS yang sudah terisi di SIPP dilewati: {skipped}.")
        except Exception as exc:
            click.echo(f"Pemeriksaan awal SIPP gagal; akan diperiksa pada halaman sidang: {exc}", err=True)

        accounts = UploadAccount.query.filter_by(is_active=True).all()
        accounts_by_role = {account.role.strip().lower(): account for account in accounts}
        accounts_by_clerk = {
            account.sipp_panitera_id: account
            for account in accounts
            if account.sipp_panitera_id
        }
        config = SeleniumConfig(
            browser=app.config["SELENIUM_BROWSER"],
            headless=not show_browser,
            login_url="",
            username="",
            password="",
            selectors_file=app.config["TARGET_SELECTORS_FILE"],
            uploaded_dir=app.config["UPLOADED_DIR"],
            slow_mode=app.config["SELENIUM_HUMAN_DELAY"],
            keep_browser_open=False,
        )
        count = upload_ready_documents(
            limit=None,
            config=config,
            accounts_by_role=accounts_by_role,
            accounts_by_clerk=accounts_by_clerk,
            roles={ROLE_BAS},
            document_filter=lambda document: is_bas_document(document) and document.source_draft_id in ready_draft_ids,
        )

        bas_documents = Document.query.filter(
            Document.source_draft_id.in_(ready_draft_ids),
            Document.document_type == "Berita Acara Sidang",
        ).all()
        notified = 0
        for document in bas_documents:
            if document.status == DocumentStatus.UPLOAD_SUCCESS:
                status = "terunggah"
                message = document.upload_response or "BAS berhasil diunggah melalui antarmuka resmi SIPP."
            elif document.status == DocumentStatus.UPLOAD_FAILED:
                status = "gagal_upload"
                message = document.error_message or "Upload BAS gagal."
            elif document.status == DocumentStatus.SKIPPED_EXISTING:
                status = "sudah_ada"
                message = document.upload_response or "BAS sudah ada di SIPP; upload dilewati."
            else:
                continue
            try:
                notify_wicaksana(app.config["WICAKSANA_BAS_API"], document.source_draft_id, status, message)
                notified += 1
            except RuntimeError as exc:
                click.echo(f"Peringatan notifikasi draf #{document.source_draft_id}: {exc}", err=True)
        click.echo(f"Upload BAS diproses: {count}; status dikirim ke E-Kepaniteraan: {notified}.")
