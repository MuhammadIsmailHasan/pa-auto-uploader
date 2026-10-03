import re
from pathlib import Path

from .. import db
from ..models import Document, DocumentStatus


def safe_filename(value: str) -> str:
    value = value.replace("/", "_")
    value = re.sub(r"[^A-Za-z0-9._ -]+", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def build_new_filename(document: Document) -> str:
    case_number = safe_filename(document.case_number or "tanpa_nomor")
    document_type = safe_filename(document.document_type or "tanpa_jenis")
    return f"{case_number} - {document_type}.pdf"


def rename_document(document: Document, apply_changes: bool) -> Path:
    current_path = Path(document.file_path)
    target_path = current_path.with_name(build_new_filename(document))

    counter = 2
    while target_path.exists() and target_path.resolve() != current_path.resolve():
        target_path = current_path.with_name(f"{target_path.stem} ({counter}){target_path.suffix}")
        counter += 1

    document.new_filename = target_path.name

    if apply_changes and target_path.resolve() != current_path.resolve():
        current_path.rename(target_path)
        document.file_path = str(target_path)

    document.status = DocumentStatus.READY_UPLOAD
    db.session.commit()
    return target_path


def rename_ready_documents(limit: int, apply_changes: bool) -> int:
    documents = (
        Document.query.filter_by(is_verified=True)
        .filter(Document.status.in_([DocumentStatus.IDENTIFIED, DocumentStatus.NEEDS_VERIFICATION]))
        .order_by(Document.updated_at.asc())
        .limit(limit)
        .all()
    )
    for document in documents:
        rename_document(document, apply_changes=apply_changes)
    return len(documents)
