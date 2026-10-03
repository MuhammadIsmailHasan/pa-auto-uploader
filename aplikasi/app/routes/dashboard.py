import json
from pathlib import Path, PurePath
import time
from threading import Lock, Thread

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for
from sqlalchemy import func, or_
from werkzeug.utils import secure_filename

from .. import db
from ..models import Document, DocumentStatus, UploadAccount
from ..services.importer import import_pdf_files, import_pdfs
from ..services.processor import process_documents_by_ids, process_pending_documents
from ..services.splitter import split_pending_combined_documents
from ..services.uploader import (
    ROLE_BAS,
    ROLE_HAKIM,
    ROLE_KETUA,
    ROLE_PANITERA,
    SeleniumConfig,
    is_bas_document,
    is_jsp_document,
    is_phs_document,
    is_pmh_document,
    is_ppp_document,
    upload_ready_documents,
    upload_role_for_document,
)

dashboard_bp = Blueprint("dashboard", __name__)
IMPORT_PROGRESS = {}
IMPORT_PROGRESS_LOCK = Lock()
PROCESS_PROGRESS = {}
PROCESS_PROGRESS_LOCK = Lock()
UPLOAD_PROGRESS = {}
UPLOAD_PROGRESS_LOCK = Lock()


def set_import_progress(import_id: str, **updates):
    if not import_id:
        return
    progress_path = import_progress_path(import_id)
    with IMPORT_PROGRESS_LOCK:
        current = IMPORT_PROGRESS.setdefault(import_id, {})
        current.update(updates)
        if progress_path:
            progress_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = progress_path.with_suffix(".tmp")
            temp_path.write_text(json.dumps(current, ensure_ascii=True), encoding="utf-8")
            temp_path.replace(progress_path)


def get_import_progress(import_id: str):
    with IMPORT_PROGRESS_LOCK:
        if import_id in IMPORT_PROGRESS:
            return dict(IMPORT_PROGRESS[import_id])
    progress_path = import_progress_path(import_id)
    if progress_path and progress_path.is_file():
        try:
            return json.loads(progress_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {"phase": "menunggu", "current": 0, "total": 0}


def import_progress_path(import_id: str) -> Path | None:
    safe_id = secure_filename(import_id or "")
    if not safe_id:
        return None
    return Path(current_app.config["LOG_DIR"]) / "import_progress" / f"{safe_id}.json"


def latest_import_progress() -> dict | None:
    progress_dir = Path(current_app.config["LOG_DIR"]) / "import_progress"
    if not progress_dir.is_dir():
        return None
    progress_files = sorted(
        progress_dir.glob("*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for progress_file in progress_files:
        try:
            data = json.loads(progress_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        data["updated_at"] = progress_file.stat().st_mtime
        return data
    return None


def set_process_progress(process_id: str, **updates):
    if not process_id:
        return
    with PROCESS_PROGRESS_LOCK:
        current = PROCESS_PROGRESS.setdefault(process_id, {})
        current.update(updates)


def get_process_progress(process_id: str):
    with PROCESS_PROGRESS_LOCK:
        return dict(PROCESS_PROGRESS.get(process_id, {"phase": "menunggu", "current": 0, "total": 0}))


def set_upload_progress(upload_id: str, **updates):
    if not upload_id:
        return
    with UPLOAD_PROGRESS_LOCK:
        current = UPLOAD_PROGRESS.setdefault(upload_id, {})
        current.update(updates)


def get_upload_progress(upload_id: str):
    with UPLOAD_PROGRESS_LOCK:
        return dict(UPLOAD_PROGRESS.get(upload_id, {"phase": "menunggu", "current": 0, "total": 0}))


def set_upload_paused(upload_id: str, paused: bool):
    set_upload_progress(
        upload_id,
        paused=paused,
        phase="pause" if paused else "upload",
        message="Upload dijeda. Klik Lanjutkan untuk meneruskan." if paused else "Upload dilanjutkan...",
    )


def is_upload_paused(upload_id: str) -> bool:
    with UPLOAD_PROGRESS_LOCK:
        return bool(UPLOAD_PROGRESS.get(upload_id, {}).get("paused"))


def safe_upload_relative_path(filename: str):
    parts = []
    for part in PurePath(filename).parts:
        if part in {"", ".", ".."}:
            continue
        safe_part = secure_filename(part)
        if safe_part:
            parts.append(safe_part)
    if not parts or not parts[-1].lower().endswith(".pdf"):
        return None
    return PurePath(*parts)


def folder_document_audit(paths) -> dict[str, int]:
    """Ringkas keadaan terkini semua record yang berasal dari folder terpilih."""
    source_paths = [str(Path(path).resolve()) for path in paths]
    documents = []
    seen_ids = set()
    for source_path in source_paths:
        matches = Document.query.filter(
            or_(
                Document.source_path == source_path,
                Document.source_path.like(f"{source_path}#split-%"),
                Document.source_path.like(f"{source_path}#sha256-%"),
            )
        ).all()
        for document in matches:
            if document.id not in seen_ids:
                seen_ids.add(document.id)
                documents.append(document)

    already_in_sipp = sum(
        document.status == DocumentStatus.UPLOAD_SUCCESS
        and (document.upload_response or "").startswith("Sudah ada tombol/icon PDF")
        for document in documents
    )
    uploaded_by_app = sum(
        document.status == DocumentStatus.UPLOAD_SUCCESS
        and not (document.upload_response or "").startswith("Sudah ada tombol/icon PDF")
        for document in documents
    )
    return {
        "records": len(documents),
        "identified": sum(bool(document.case_number and document.document_type) for document in documents),
        "needs_verification": sum(document.status == DocumentStatus.NEEDS_VERIFICATION for document in documents),
        "ready_upload": sum(document.status == DocumentStatus.READY_UPLOAD for document in documents),
        "upload_failed": sum(document.status == DocumentStatus.UPLOAD_FAILED for document in documents),
        "already_in_sipp": already_in_sipp,
        "uploaded_by_app": uploaded_by_app,
        "still_processing": sum(
            document.status in {DocumentStatus.NEW, DocumentStatus.IDENTIFIED, DocumentStatus.SPLIT}
            for document in documents
        ),
    }


def path_is_inside(path: Path, root: Path) -> bool:
    resolved_path = path.resolve()
    resolved_root = root.resolve()
    return resolved_path == resolved_root or resolved_root in resolved_path.parents


def remove_empty_parents(path: Path, root: Path) -> None:
    resolved_root = root.resolve()
    parent = path.resolve().parent
    while parent != resolved_root and resolved_root in parent.parents:
        try:
            parent.rmdir()
        except OSError:
            break
        parent = parent.parent


def clear_new_identified_documents() -> dict[str, int]:
    statuses = [DocumentStatus.NEW, DocumentStatus.IDENTIFIED]
    managed_file_roots = [
        Path(current_app.config["STORAGE_DIR"]),
        Path(current_app.config["PREVIEW_DIR"]),
        Path(current_app.config["EXPORT_DIR"]),
        Path(current_app.config["IMPORT_SOURCE_DIR"]),
    ]
    source_root = Path(current_app.config["IMPORT_SOURCE_DIR"])
    documents = Document.query.filter(Document.status.in_(statuses)).all()
    file_candidates = []
    for document in documents:
        for value in (document.file_path, document.preview_path, document.export_path, document.source_path):
            if value:
                file_candidates.append(Path(value))

    deleted_files = 0
    skipped_files = 0
    missing_files = 0
    errors = 0
    seen_paths = set()
    for file_path in file_candidates:
        try:
            resolved_path = file_path.resolve()
            if resolved_path in seen_paths:
                continue
            seen_paths.add(resolved_path)
            if not any(path_is_inside(resolved_path, root) for root in managed_file_roots):
                skipped_files += 1
                continue
            if not resolved_path.exists():
                missing_files += 1
                continue
            if not resolved_path.is_file():
                skipped_files += 1
                continue
            resolved_path.unlink()
            deleted_files += 1
            if path_is_inside(resolved_path, source_root):
                remove_empty_parents(resolved_path, source_root)
        except OSError:
            errors += 1

    deleted_records = len(documents)
    for document in documents:
        db.session.delete(document)
    db.session.commit()
    return {
        "deleted_records": deleted_records,
        "deleted_files": deleted_files,
        "missing_files": missing_files,
        "skipped_files": skipped_files,
        "errors": errors,
    }


@dashboard_bp.route("/")
def index():
    rows = db.session.query(Document.status, func.count(Document.id)).group_by(Document.status).all()
    counts = {status: 0 for status in DocumentStatus.ALL}
    counts.update({status: count for status, count in rows})

    # Dokumen yang hanya dikonfirmasi sudah ada di SIPP tidak perlu kembali
    # memenuhi daftar kerja. Record dan log tetap disimpan sebagai audit dan
    # untuk mencegah file yang sama diproses ulang.
    latest_documents = (
        Document.query.filter(
            or_(
                Document.upload_response.is_(None),
                ~Document.upload_response.like("Sudah ada tombol/icon PDF%"),
            )
        )
        .order_by(Document.updated_at.desc())
        .limit(10)
        .all()
    )
    return render_template(
        "dashboard.html",
        counts=counts,
        latest_documents=latest_documents,
        latest_import=latest_import_progress(),
    )


@dashboard_bp.route("/actions/import", methods=["POST"])
def import_action():
    result = import_pdfs(current_app.config["IMPORT_SOURCE_DIR"], current_app.config["STORAGE_DIR"])
    flash(
        f"Import selesai. Baru: {result['imported']}, dilewati: {result['skipped']}, gagal: {result['failed']}.",
        "success",
    )
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/actions/clear-new-identified", methods=["POST"])
def clear_new_identified_action():
    result = clear_new_identified_documents()
    category = "warning" if result["errors"] else "success"
    flash(
        "Clear selesai. "
        f"Record dihapus: {result['deleted_records']}, "
        f"file dihapus: {result['deleted_files']}, "
        f"file tidak ditemukan: {result['missing_files']}, "
        f"dilewati: {result['skipped_files']}, "
        f"error: {result['errors']}.",
        category,
    )
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/actions/retry-failed", methods=["POST"])
def retry_failed_action():
    documents = Document.query.filter_by(status=DocumentStatus.UPLOAD_FAILED).all()
    ready = 0
    skipped = 0
    for document in documents:
        if (
            document.is_verified
            and document.case_number
            and document.document_type
            and Path(document.file_path).is_file()
        ):
            document.status = DocumentStatus.READY_UPLOAD
            document.error_message = None
            document.upload_response = None
            ready += 1
        else:
            skipped += 1
    db.session.commit()
    flash(f"Upload ulang disiapkan: {ready} dokumen. Belum memenuhi syarat: {skipped}.", "success" if ready else "warning")
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/actions/import-folder", methods=["POST"])
def import_folder_action():
    files = request.files.getlist("pdf_folder")
    import_id = request.form.get("import_id", "").strip()
    source_dir = current_app.config["IMPORT_SOURCE_DIR"]
    source_dir.mkdir(parents=True, exist_ok=True)

    saved = 0
    saved_paths = []
    ignored = 0
    set_import_progress(import_id, phase="menyimpan", current=0, total=len(files), message="Menyimpan PDF ke folder aplikasi...")
    for uploaded in files:
        relative_path = safe_upload_relative_path(uploaded.filename)
        if not relative_path:
            ignored += 1
            continue

        target_path = source_dir / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        uploaded.save(target_path)
        saved_paths.append(target_path)
        saved += 1
        set_import_progress(import_id, phase="menyimpan", current=saved, total=len(files), message=f"Menyimpan PDF {saved} / {len(files)}")

    if saved == 0:
        flash("Tidak ada PDF yang dipilih untuk di-import.", "warning")
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"ok": False, "message": "Tidak ada PDF yang dipilih untuk di-import."}), 400
        return redirect(url_for("dashboard.index"))

    app = current_app._get_current_object()

    def run_import_job():
        with app.app_context():
            try:
                def report_import_progress(index, total, path):
                    set_import_progress(
                        import_id,
                        phase="import",
                        current=index,
                        total=total,
                        message=f"Import {index} / {total}: {path.name}",
                    )

                result = import_pdf_files(
                    saved_paths,
                    app.config["STORAGE_DIR"],
                    progress_callback=report_import_progress,
                )
                imported_ids = result["imported_ids"]

                def report_identification_progress(index, total, document):
                    set_import_progress(
                        import_id,
                        phase="identifikasi",
                        current=index,
                        total=total,
                        message=f"Identifikasi dan pemisahan {index} / {total}: {document.original_filename}",
                    )

                identified = process_documents_by_ids(
                    document_ids=imported_ids,
                    lang=app.config["OCR_LANG"],
                    dpi=app.config["OCR_DPI"],
                    max_ocr_pages=app.config["MAX_OCR_PAGES"],
                    preview_dir=app.config["PREVIEW_DIR"],
                    export_dir=app.config["EXPORT_DIR"],
                    progress_callback=report_identification_progress,
                )
                audit = folder_document_audit(saved_paths)
                message = (
                    f"Pemeriksaan folder selesai: {saved} PDF diterima; {result['imported']} baru dan "
                    f"{result['skipped']} sudah pernah diproses. "
                    f"Status saat ini: {audit['identified']} teridentifikasi, "
                    f"{audit['ready_upload']} siap upload, {audit['already_in_sipp']} sudah ada di SIPP, "
                    f"{audit['uploaded_by_app']} berhasil diupload aplikasi, "
                    f"{audit['needs_verification']} perlu verifikasi, {audit['upload_failed']} gagal upload."
                )
                set_import_progress(
                    import_id,
                    phase="selesai",
                    current=saved,
                    total=saved,
                    message=message,
                    audit={
                        "selected": saved,
                        "ignored": ignored,
                        "new": result["imported"],
                        "known": result["skipped"],
                        "import_failed": result["failed"],
                        **audit,
                    },
                )
            except Exception as exc:
                app.logger.exception("Import folder gagal")
                db.session.rollback()
                set_import_progress(
                    import_id,
                    phase="gagal",
                    current=0,
                    total=max(saved, 1),
                    message=f"Import folder gagal: {exc}",
                )
            finally:
                db.session.remove()

    set_import_progress(
        import_id,
        phase="mulai",
        current=0,
        total=saved,
        message=f"Upload selesai. Memulai import {saved} PDF...",
    )
    Thread(target=run_import_job, daemon=True).start()
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"ok": True, "phase": "mulai", "message": f"Upload selesai. Memulai import {saved} PDF..."})

    flash(f"Upload selesai. Import {saved} PDF berjalan di background.", "success")
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/actions/import-folder/status/<import_id>")
def import_folder_status(import_id):
    return jsonify(get_import_progress(import_id))


@dashboard_bp.route("/actions/process", methods=["POST"])
def process_action():
    process_id = request.form.get("process_id", "").strip()
    pending_count = Document.query.filter_by(status=DocumentStatus.NEW).count()
    set_process_progress(
        process_id,
        phase="identifikasi",
        current=0,
        total=pending_count,
        message=f"Menyiapkan identifikasi {pending_count} dokumen...",
    )

    def report_process_progress(index, total, document):
        set_process_progress(
            process_id,
            phase="identifikasi",
            current=index,
            total=total,
            message=f"Identifikasi {index} / {total}: {document.original_filename}",
        )

    count = process_pending_documents(
        limit=None,
        lang=current_app.config["OCR_LANG"],
        dpi=current_app.config["OCR_DPI"],
        max_ocr_pages=current_app.config["MAX_OCR_PAGES"],
        preview_dir=current_app.config["PREVIEW_DIR"],
        export_dir=current_app.config["EXPORT_DIR"],
        progress_callback=report_process_progress,
    )
    message = f"Identifikasi selesai untuk {count} dokumen."
    flash(message, "success")
    set_process_progress(process_id, phase="selesai", current=count, total=count, message=message)
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"ok": True, "message": message})
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/actions/process/status/<process_id>")
def process_status(process_id):
    return jsonify(get_process_progress(process_id))


@dashboard_bp.route("/actions/upload-ready", methods=["POST"])
def upload_ready_action():
    upload_id = request.form.get("upload_id", "").strip()
    mode = request.form.get("upload_mode", "").strip()
    mode_roles = {
        "pmh_ppp": {ROLE_KETUA},
        "jsp": {ROLE_PANITERA},
        "phs": {ROLE_HAKIM},
        "bas": {ROLE_BAS},
        "all_mahfudin": {ROLE_KETUA, ROLE_PANITERA, ROLE_HAKIM},
    }
    mode_labels = {
        "pmh_ppp": "PMH & PPP",
        "jsp": "JSP",
        "phs": "PHS",
        "bas": "BAS sesuai akun Panitera/PP",
        "all_mahfudin": "PMH, PPP, JSP & PHS pakai Mahfudin",
    }
    roles = mode_roles.get(mode)
    if not roles:
        message = "Mode upload tidak valid."
        flash(message, "danger")
        set_upload_progress(upload_id, phase="gagal", current=0, total=0, message=message)
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"ok": False, "message": message}), 400
        return redirect(url_for("dashboard.index"))

    missing = []
    accounts = UploadAccount.query.filter_by(is_active=True).all()
    accounts_by_role = {account.role.strip().lower(): account for account in accounts}
    accounts_by_clerk = {
        account.sipp_panitera_id: account for account in accounts if account.sipp_panitera_id
    }
    if mode == "all_mahfudin":
        mahfudin_account = next(
            (
                account
                for account in accounts
                if account.name.strip().lower() == "mahfudin"
                or account.username.strip().lower() == "mahfudin"
            ),
            None,
        )
        if mahfudin_account:
            accounts_by_role = {role: mahfudin_account for role in roles}
        else:
            missing.append("mahfudin")
    elif mode != "bas":
        for role in roles:
            if role not in accounts_by_role:
                missing.append(role)
    if missing:
        message = f"Akun upload belum lengkap. Isi akun aktif untuk peran: {', '.join(missing)}."
        flash(message, "danger")
        set_upload_progress(upload_id, phase="gagal", current=0, total=0, message=message)
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"ok": False, "message": message}), 400
        return redirect(url_for("dashboard.index"))

    def mode_matches(document):
        if mode == "pmh_ppp":
            return is_pmh_document(document) or is_ppp_document(document)
        if mode == "jsp":
            return is_jsp_document(document)
        if mode == "phs":
            return is_phs_document(document)
        if mode == "bas":
            return is_bas_document(document)
        if mode == "all_mahfudin":
            return (
                is_pmh_document(document)
                or is_ppp_document(document)
                or is_jsp_document(document)
                or is_phs_document(document)
            )
        return False

    ready_documents = [
        document
        for document in Document.query.filter_by(status=DocumentStatus.READY_UPLOAD).all()
        if upload_role_for_document(document) in roles and mode_matches(document)
    ]
    ready_document_ids = [document.id for document in ready_documents]
    ready_count = len(ready_document_ids)
    set_upload_progress(
        upload_id,
        phase="upload",
        current=0,
        total=ready_count,
        paused=False,
        message=f"Menyiapkan upload {mode_labels[mode]} untuk {ready_count} dokumen...",
    )

    config = SeleniumConfig(
        browser=current_app.config["SELENIUM_BROWSER"],
        headless=current_app.config["SELENIUM_HEADLESS"],
        login_url="",
        username="",
        password="",
        selectors_file=current_app.config["TARGET_SELECTORS_FILE"],
        uploaded_dir=current_app.config["UPLOADED_DIR"],
        slow_mode=current_app.config["SELENIUM_HUMAN_DELAY"],
        keep_browser_open=current_app.config["SELENIUM_KEEP_BROWSER_OPEN"],
    )

    def report_upload_progress(index, total, document):
        set_upload_progress(
            upload_id,
            phase="upload",
            current=index,
            total=total,
            paused=is_upload_paused(upload_id),
            message=f"Upload {mode_labels[mode]} {index} / {total}: {document.original_filename}",
        )

    def wait_while_paused(index, total, document):
        while is_upload_paused(upload_id):
            set_upload_progress(
                upload_id,
                phase="pause",
                current=index,
                total=total,
                paused=True,
                message=f"Dijeda pada {index} / {total}. Dokumen berikutnya: {document.original_filename}",
            )
            time.sleep(1)

    def wait_batch_pause(index, total, document):
        for remaining in range(30, 0, -1):
            wait_while_paused(index, total, document)
            set_upload_progress(
                upload_id,
                phase="istirahat",
                current=index,
                total=total,
                paused=False,
                message=f"Sudah upload {index} dokumen. Jeda otomatis {remaining} detik sebelum lanjut...",
            )
            time.sleep(1)
        set_upload_progress(
            upload_id,
            phase="upload",
            current=index,
            total=total,
            paused=False,
            message="Jeda otomatis selesai. Upload dilanjutkan...",
        )

    def upload_result_summary():
        if not ready_document_ids:
            return 0, 0, 0
        rows = Document.query.filter(Document.id.in_(ready_document_ids)).all()
        succeeded = sum(document.status == DocumentStatus.UPLOAD_SUCCESS for document in rows)
        failed = sum(document.status == DocumentStatus.UPLOAD_FAILED for document in rows)
        pending = len(rows) - succeeded - failed
        return succeeded, failed, pending

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        app_obj = current_app._get_current_object()

        def run_upload_job():
            with app_obj.app_context():
                try:
                    active_accounts = UploadAccount.query.filter_by(is_active=True).all()
                    active_accounts_by_role = {account.role.strip().lower(): account for account in active_accounts}
                    active_accounts_by_clerk = {
                        account.sipp_panitera_id: account
                        for account in active_accounts
                        if account.sipp_panitera_id
                    }
                    if mode == "all_mahfudin":
                        mahfudin_account = next(
                            (
                                account
                                for account in active_accounts
                                if account.name.strip().lower() == "mahfudin"
                                or account.username.strip().lower() == "mahfudin"
                            ),
                            None,
                        )
                        if mahfudin_account:
                            active_accounts_by_role = {role: mahfudin_account for role in roles}

                    count = upload_ready_documents(
                        limit=None,
                        config=config,
                        accounts_by_role=active_accounts_by_role,
                        accounts_by_clerk=active_accounts_by_clerk,
                        roles=roles,
                        document_filter=mode_matches,
                        progress_callback=report_upload_progress,
                        pause_callback=wait_while_paused,
                        batch_pause_callback=wait_batch_pause,
                        batch_pause_every=100,
                    )
                    succeeded, failed, pending = upload_result_summary()
                    message = (
                        f"Batch {mode_labels[mode]}: {succeeded} berhasil/sudah ada, "
                        f"{failed} gagal, {pending} masih tertunda."
                    )
                    set_upload_progress(
                        upload_id,
                        phase="gagal" if failed else "selesai",
                        current=count,
                        total=count,
                        message=message,
                    )
                except Exception as exc:
                    set_upload_progress(
                        upload_id,
                        phase="gagal",
                        current=0,
                        total=ready_count,
                        message=f"Upload gagal: {exc}",
                    )

        Thread(target=run_upload_job, daemon=True).start()
        return jsonify({"ok": True, "phase": "mulai", "message": "Upload dimulai di background."}), 202

    count = upload_ready_documents(
        limit=None,
        config=config,
        accounts_by_role=accounts_by_role,
        accounts_by_clerk=accounts_by_clerk,
        roles=roles,
        document_filter=mode_matches,
        progress_callback=report_upload_progress,
        pause_callback=wait_while_paused,
        batch_pause_callback=wait_batch_pause,
        batch_pause_every=100,
    )
    succeeded, failed, pending = upload_result_summary()
    message = (
        f"Batch {mode_labels[mode]}: {succeeded} berhasil/sudah ada, "
        f"{failed} gagal, {pending} masih tertunda."
    )
    flash(message, "danger" if failed else "success")
    set_upload_progress(
        upload_id,
        phase="gagal" if failed else "selesai",
        current=count,
        total=count,
        message=message,
    )
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/actions/upload-ready/status/<upload_id>")
def upload_ready_status(upload_id):
    return jsonify(get_upload_progress(upload_id))


@dashboard_bp.route("/actions/upload-ready/pause/<upload_id>", methods=["POST"])
def upload_ready_pause(upload_id):
    set_upload_paused(upload_id, True)
    return jsonify({"ok": True, "paused": True})


@dashboard_bp.route("/actions/upload-ready/resume/<upload_id>", methods=["POST"])
def upload_ready_resume(upload_id):
    set_upload_paused(upload_id, False)
    return jsonify({"ok": True, "paused": False})


@dashboard_bp.route("/actions/split-combined", methods=["POST"])
def split_combined_action():
    results = split_pending_combined_documents(
        limit=50,
        preview_dir=current_app.config["PREVIEW_DIR"],
        export_dir=current_app.config["EXPORT_DIR"],
        lang=current_app.config["OCR_LANG"],
        dpi=current_app.config["OCR_DPI"],
    )
    created = sum(len(result.created_ids) for result in results)
    flash(f"Pemisahan selesai. Dokumen gabungan dicek: {len(results)}, dokumen baru dibuat: {created}.", "success")
    return redirect(url_for("dashboard.index"))
