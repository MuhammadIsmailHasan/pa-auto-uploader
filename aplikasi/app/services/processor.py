from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from .. import db
from ..models import Document, DocumentStatus
from .exporter import export_document
from .identification import identify_document, identify_document_type_from_filename
from .ocr import create_first_page_preview, extract_text
from .splitter import is_combined_panitera_jurusita, split_document


def process_document(
    document: Document,
    lang: str,
    dpi: int,
    max_ocr_pages: int,
    preview_dir: Path,
    export_dir: Path,
) -> None:
    document_id = document.id
    document.process_started_at = datetime.utcnow()
    document.error_message = None
    db.session.commit()

    try:
        pdf_path = Path(document.file_path)
        text, engine = extract_text(pdf_path, lang=lang, dpi=dpi, max_ocr_pages=max_ocr_pages)
        result = identify_document(text)
        filename_document_type = identify_document_type_from_filename(document.original_filename or pdf_path.name)
        document_type = filename_document_type or result.document_type
        preview_path = None
        preview_error = None
        try:
            preview_path = create_first_page_preview(pdf_path, preview_dir, document.id)
        except Exception as exc:
            preview_error = f"Preview gagal dibuat: {exc}"

        document.ocr_text = text
        document.ocr_engine = engine
        document.case_number = result.case_number
        document.document_type = document_type
        document.preview_path = str(preview_path) if preview_path else None
        document.processed_at = datetime.utcnow()
        document.status = (
            DocumentStatus.READY_UPLOAD
            if result.case_number and document_type
            else DocumentStatus.NEEDS_VERIFICATION
        )
        document.is_verified = document.status == DocumentStatus.READY_UPLOAD
        document.error_message = preview_error if document.status == DocumentStatus.NEEDS_VERIFICATION else None
        db.session.commit()

        if document.case_number and is_combined_panitera_jurusita(document):
            split_document(document, preview_dir=preview_dir, export_dir=export_dir, lang=lang, dpi=dpi)
        elif document.status == DocumentStatus.READY_UPLOAD:
            export_document(document, export_dir)
    except Exception as exc:
        db.session.rollback()
        document = db.session.get(Document, document_id)
        if document is None:
            return
        document.error_message = str(exc)
        document.status = DocumentStatus.NEEDS_VERIFICATION
        document.processed_at = datetime.utcnow()

    db.session.commit()


def process_pending_documents(
    limit: int | None,
    lang: str,
    dpi: int,
    max_ocr_pages: int,
    preview_dir: Path,
    export_dir: Path,
    progress_callback=None,
) -> int:
    query = Document.query.filter_by(status=DocumentStatus.NEW)
    ordered_query = query.order_by(Document.created_at.asc())
    if limit is not None:
        ordered_query = ordered_query.limit(limit)
    document_ids = [document_id for (document_id,) in ordered_query.with_entities(Document.id).all()]
    total = len(document_ids)
    processed = 0
    for index, document_id in enumerate(document_ids, start=1):
        document = db.session.get(Document, document_id)
        if document is None:
            continue
        progress_document = SimpleNamespace(id=document.id, original_filename=document.original_filename)
        if progress_callback:
            progress_callback(index, total, progress_document)
        process_document(document, lang, dpi, max_ocr_pages, preview_dir, export_dir)
        processed += 1
    return processed


def process_documents_by_ids(
    document_ids: list[int],
    lang: str,
    dpi: int,
    max_ocr_pages: int,
    preview_dir: Path,
    export_dir: Path,
    progress_callback=None,
) -> int:
    existing_ids = {
        document_id
        for (document_id,) in Document.query.with_entities(Document.id)
        .filter(Document.id.in_(document_ids))
        .all()
    }
    queued_ids = [document_id for document_id in document_ids if document_id in existing_ids]
    total = len(queued_ids)
    processed = 0
    for index, document_id in enumerate(queued_ids, start=1):
        document = db.session.get(Document, document_id)
        if document is None:
            continue
        progress_document = SimpleNamespace(id=document.id, original_filename=document.original_filename)
        if progress_callback:
            progress_callback(index, total, progress_document)
        process_document(document, lang, dpi, max_ocr_pages, preview_dir, export_dir)
        processed += 1
    return processed
