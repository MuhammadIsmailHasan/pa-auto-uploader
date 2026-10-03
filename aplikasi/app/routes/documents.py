from pathlib import Path

from flask import Blueprint, current_app, flash, redirect, render_template, request, send_file, url_for
from sqlalchemy import or_

from .. import db
from ..models import Document, DocumentStatus, UploadLog
from ..services.renamer import rename_document
from ..services.splitter import split_document

documents_bp = Blueprint("documents", __name__)


def path_is_inside(path: Path, root: Path) -> bool:
    resolved_path = path.resolve()
    resolved_root = root.resolve()
    return resolved_path == resolved_root or resolved_root in resolved_path.parents


def delete_managed_document_files(document: Document) -> tuple[int, int]:
    roots = [
        Path(current_app.config["STORAGE_DIR"]),
        Path(current_app.config["PREVIEW_DIR"]),
        Path(current_app.config["EXPORT_DIR"]),
        Path(current_app.config["IMPORT_SOURCE_DIR"]),
    ]
    deleted = 0
    skipped = 0
    seen = set()
    for value in (document.file_path, document.preview_path, document.export_path, document.source_path):
        if not value:
            continue
        path = Path(value).resolve()
        if path in seen:
            continue
        seen.add(path)
        if not any(path_is_inside(path, root) for root in roots):
            skipped += 1
            continue
        try:
            if path.is_file():
                path.unlink()
                deleted += 1
        except OSError:
            skipped += 1
    return deleted, skipped


@documents_bp.route("/")
def index():
    status = request.args.get("status", "")
    search = request.args.get("q", "").strip()
    page = request.args.get("page", 1, type=int)

    query = Document.query
    if status:
        query = query.filter_by(status=status)
    if search:
        like = f"%{search}%"
        query = query.filter(
            or_(
                Document.case_number.like(like),
                Document.document_type.like(like),
                Document.original_filename.like(like),
                Document.new_filename.like(like),
            )
        )

    documents = query.order_by(Document.updated_at.desc()).paginate(page=page, per_page=25, error_out=False)
    return render_template("documents/index.html", documents=documents, statuses=DocumentStatus.ALL)


@documents_bp.route("/<int:document_id>", methods=["GET", "POST"])
def detail(document_id):
    document = Document.query.get_or_404(document_id)

    if request.method == "POST":
        document.case_number = request.form.get("case_number", "").strip() or None
        document.document_type = request.form.get("document_type", "").strip() or None
        document.is_verified = request.form.get("is_verified") == "on"
        document.error_message = None
        if document.is_verified and document.case_number and document.document_type:
            document.status = DocumentStatus.IDENTIFIED
        else:
            document.status = DocumentStatus.NEEDS_VERIFICATION
        db.session.commit()
        return redirect(url_for("documents.detail", document_id=document.id))

    return render_template("documents/detail.html", document=document)


@documents_bp.route("/<int:document_id>/rename", methods=["POST"])
def rename(document_id):
    document = Document.query.get_or_404(document_id)
    rename_document(document, apply_changes=current_app.config["RENAME_APPLY"])
    return redirect(url_for("documents.detail", document_id=document.id))


@documents_bp.route("/<int:document_id>/split", methods=["POST"])
def split(document_id):
    document = Document.query.get_or_404(document_id)
    split_document(
        document,
        preview_dir=current_app.config["PREVIEW_DIR"],
        export_dir=current_app.config["EXPORT_DIR"],
        lang=current_app.config["OCR_LANG"],
        dpi=current_app.config["OCR_DPI"],
    )
    return redirect(url_for("documents.detail", document_id=document.id))


@documents_bp.route("/<int:document_id>/retry-upload", methods=["POST"])
def retry_upload(document_id):
    document = Document.query.get_or_404(document_id)
    if document.status != DocumentStatus.UPLOAD_FAILED:
        flash("Hanya dokumen gagal upload yang dapat disiapkan ulang.", "warning")
    elif not document.is_verified or not document.case_number or not document.document_type:
        flash("Lengkapi dan verifikasi nomor perkara serta jenis dokumen terlebih dahulu.", "danger")
    elif not Path(document.file_path).is_file():
        flash("File PDF tidak ditemukan; dokumen tidak dapat diulang.", "danger")
    else:
        document.status = DocumentStatus.READY_UPLOAD
        document.error_message = None
        document.upload_response = None
        db.session.add(UploadLog(document_id=document.id, status="ulang", message="Dokumen disiapkan untuk upload ulang."))
        db.session.commit()
        flash("Dokumen sudah masuk antrean siap upload kembali.", "success")
    return redirect(request.referrer or url_for("documents.index", status=DocumentStatus.UPLOAD_FAILED))


@documents_bp.route("/<int:document_id>/delete", methods=["POST"])
def delete(document_id):
    document = Document.query.get_or_404(document_id)
    if document.status != DocumentStatus.NEEDS_VERIFICATION:
        flash("Penghapusan per dokumen hanya diizinkan untuk status perlu verifikasi.", "danger")
        return redirect(request.referrer or url_for("documents.index"))
    deleted, skipped = delete_managed_document_files(document)
    name = document.original_filename
    db.session.delete(document)
    db.session.commit()
    flash(f"Dokumen {name} dihapus. File terhapus: {deleted}, dilewati: {skipped}.", "success")
    return redirect(url_for("documents.index", status=DocumentStatus.NEEDS_VERIFICATION))


@documents_bp.route("/<int:document_id>/preview")
def preview(document_id):
    document = Document.query.get_or_404(document_id)
    if not document.preview_path or not Path(document.preview_path).exists():
        return "", 404
    return send_file(document.preview_path, mimetype="image/jpeg")


@documents_bp.route("/<int:document_id>/pdf")
def pdf(document_id):
    document = Document.query.get_or_404(document_id)
    return send_file(document.file_path, mimetype="application/pdf", as_attachment=False)
