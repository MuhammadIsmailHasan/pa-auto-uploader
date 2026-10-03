from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import hashlib

import pdfplumber
import pytesseract
from pdf2image import convert_from_path
from pypdf import PdfReader, PdfWriter

from .. import db
from ..models import Document, DocumentStatus
from .identification import extract_case_number, identify_document_type
from .exporter import unique_target_path
from .ocr import create_first_page_preview, resolve_poppler_path
from .renamer import build_new_filename


SPLIT_TYPES = ("Penunjukan Panitera", "Penunjukan Jurusita")


@dataclass
class SplitResult:
    original_id: int
    created_ids: list[int]
    message: str


def ocr_page_text(pdf_path: Path, page_number: int, lang: str, dpi: int) -> str:
    images = convert_from_path(
        str(pdf_path),
        dpi=dpi,
        first_page=page_number,
        last_page=page_number,
        thread_count=1,
        poppler_path=resolve_poppler_path(),
    )
    if not images:
        return ""
    image = images[0]
    try:
        return pytesseract.image_to_string(image, lang=lang)
    finally:
        image.close()


def page_texts(pdf_path: Path, lang: str = "ind", dpi: int = 200) -> list[str]:
    texts: list[str] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for index, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            if len(text.strip()) < 30:
                text = ocr_page_text(pdf_path, index, lang=lang, dpi=dpi)
            texts.append(text)
    return texts


def classify_split_pages(texts: list[str]) -> dict[str, list[int]]:
    groups = {doc_type: [] for doc_type in SPLIT_TYPES}
    last_type: str | None = None

    for index, text in enumerate(texts):
        doc_type = classify_pp_jurusita_page(text) or identify_document_type(text)
        if doc_type in SPLIT_TYPES:
            last_type = doc_type
            groups[doc_type].append(index)
        elif last_type:
            groups[last_type].append(index)

    return groups


def classify_pp_jurusita_page(text: str) -> str | None:
    normalized = " ".join((text or "").lower().split())
    jurusita_score = 0
    panitera_score = 0

    if "jurusita/jurusita pengganti" in normalized:
        jurusita_score += 40
    if "jurusita pengganti" in normalized:
        jurusita_score += 25
    if "sebagai jurusita" in normalized:
        jurusita_score += 20
    if "dibantu oleh seorang jurusita" in normalized:
        jurusita_score += 20

    if "panitera pengganti" in normalized:
        panitera_score += 35
    if "menunjuk panitera pengganti" in normalized:
        panitera_score += 25
    if "sebagai panitera pengganti" in normalized:
        panitera_score += 20

    if jurusita_score >= 20 and jurusita_score > panitera_score:
        return "Penunjukan Jurusita"
    if panitera_score >= 20 and panitera_score > jurusita_score:
        return "Penunjukan Panitera"
    return None


def is_combined_panitera_jurusita(document: Document) -> bool:
    text = " ".join((document.ocr_text or "").lower().split())
    return "panitera pengganti" in text and "jurusita" in text


def write_pdf_pages(source_pdf: Path, page_indexes: list[int], target_pdf: Path) -> None:
    reader = PdfReader(str(source_pdf))
    writer = PdfWriter()
    for page_index in page_indexes:
        writer.add_page(reader.pages[page_index])
    with target_pdf.open("wb") as handle:
        writer.write(handle)


def build_split_filename(document: Document, doc_type: str) -> str:
    case_number = (document.case_number or "tanpa_nomor").replace("/", "_")
    return f"{case_number} - {doc_type}.pdf"


def split_document(
    document: Document,
    preview_dir: Path,
    export_dir: Path | None = None,
    lang: str = "ind",
    dpi: int = 200,
) -> SplitResult:
    original_id = document.id
    if not is_combined_panitera_jurusita(document):
        return SplitResult(original_id, [], "Dokumen tidak terdeteksi sebagai gabungan Panitera/Jurusita.")

    source_pdf = Path(document.file_path)
    texts = page_texts(source_pdf, lang=lang, dpi=dpi)
    groups = classify_split_pages(texts)

    if not groups["Penunjukan Panitera"] or not groups["Penunjukan Jurusita"]:
        return SplitResult(original_id, [], "Halaman Panitera dan Jurusita belum bisa dipisahkan dengan yakin.")

    created_ids: list[int] = []
    for doc_type, pages in groups.items():
        split_source_path = f"{document.source_path}#split-{doc_type}"
        existing_split = Document.query.filter_by(source_path=split_source_path).first()
        if existing_split:
            if existing_split.case_number:
                existing_split.is_verified = True
            created_ids.append(existing_split.id)
            continue

        if export_dir:
            temp_doc = Document(case_number=document.case_number, document_type=doc_type)
            target_pdf = unique_target_path(export_dir, build_new_filename(temp_doc))
        else:
            target_pdf = source_pdf.with_name(build_split_filename(document, doc_type))
            counter = 2
            while target_pdf.exists():
                target_pdf = source_pdf.with_name(f"{target_pdf.stem} ({counter}){target_pdf.suffix}")
                counter += 1
        write_pdf_pages(source_pdf, pages, target_pdf)
        combined_text = "\n\n".join(texts[index] for index in pages).strip()
        case_number = extract_case_number(combined_text) or document.case_number

        split_doc = Document(
            source_path=split_source_path,
            file_path=str(target_pdf),
            export_path=str(target_pdf) if export_dir else None,
            original_filename=document.original_filename,
            new_filename=target_pdf.name,
            file_size=target_pdf.stat().st_size,
            case_number=case_number,
            document_type=doc_type,
            ocr_text=combined_text,
            ocr_engine=document.ocr_engine,
            status=DocumentStatus.READY_UPLOAD if case_number else DocumentStatus.NEEDS_VERIFICATION,
            is_verified=bool(case_number),
            processed_at=datetime.utcnow(),
        )
        db.session.add(split_doc)
        db.session.flush()

        preview_path = create_first_page_preview(target_pdf, preview_dir, split_doc.id)
        split_doc.preview_path = str(preview_path) if preview_path else None
        created_ids.append(split_doc.id)

    source_files = {
        Path(value)
        for value in (document.source_path, document.file_path, document.preview_path, document.export_path)
        if value
    }
    db.session.delete(document)
    db.session.commit()

    for source_file in source_files:
        try:
            if source_file.is_file():
                source_file.unlink()
        except OSError:
            pass
    return SplitResult(original_id, created_ids, "Dokumen berhasil dipisahkan.")


def recover_jurusita_from_uploaded_combined(
    document: Document,
    preview_dir: Path,
    export_dir: Path,
    lang: str = "ind",
    dpi: int = 200,
) -> Document:
    """Create a missing PJS record while preserving an uploaded combined PPP."""
    if document.document_type != "Penunjukan Panitera" or not is_combined_panitera_jurusita(document):
        raise ValueError("Dokumen bukan gabungan PP/Jurusita yang teridentifikasi.")
    split_source_path = f"{document.source_path}#split-Penunjukan Jurusita"
    existing = Document.query.filter_by(source_path=split_source_path).first()
    if existing:
        return existing

    texts = page_texts(Path(document.file_path), lang=lang, dpi=dpi)
    groups = classify_split_pages(texts)
    if not groups["Penunjukan Panitera"] or not groups["Penunjukan Jurusita"]:
        raise ValueError("Halaman PP dan Jurusita belum dapat dipisahkan dengan yakin.")
    pjs_text = "\n\n".join(texts[index] for index in groups["Penunjukan Jurusita"])
    case_number = extract_case_number(pjs_text)
    if not case_number or case_number != document.case_number:
        raise ValueError("Nomor perkara pada halaman Jurusita berbeda dari record asal.")

    temp_doc = Document(case_number=case_number, document_type="Penunjukan Jurusita")
    target_pdf = unique_target_path(export_dir, build_new_filename(temp_doc))
    try:
        write_pdf_pages(Path(document.file_path), groups["Penunjukan Jurusita"], target_pdf)
        file_hash = hashlib.sha256(target_pdf.read_bytes()).hexdigest()
        recovered = Document(
            source_path=split_source_path,
            file_path=str(target_pdf),
            export_path=str(target_pdf),
            original_filename=document.original_filename,
            new_filename=target_pdf.name,
            file_sha256=file_hash,
            file_size=target_pdf.stat().st_size,
            case_number=case_number,
            document_type="Penunjukan Jurusita",
            ocr_text=pjs_text,
            ocr_engine=document.ocr_engine,
            status=DocumentStatus.READY_UPLOAD,
            is_verified=True,
            processed_at=datetime.utcnow(),
        )
        db.session.add(recovered)
        db.session.flush()
        preview_path = create_first_page_preview(target_pdf, preview_dir, recovered.id)
        recovered.preview_path = str(preview_path) if preview_path else None
        db.session.commit()
        return recovered
    except Exception:
        db.session.rollback()
        target_pdf.unlink(missing_ok=True)
        raise


def split_pending_combined_documents(
    limit: int,
    preview_dir: Path,
    export_dir: Path | None = None,
    lang: str = "ind",
    dpi: int = 200,
) -> list[SplitResult]:
    candidates = (
        Document.query.filter(Document.ocr_text.isnot(None), Document.is_verified.is_(False))
        .filter(Document.ocr_text.like("%panitera%"))
        .filter(Document.ocr_text.like("%jurusita%"))
        .order_by(Document.id.asc())
        .limit(limit)
        .all()
    )
    results: list[SplitResult] = []
    for document in candidates:
        existing_split = Document.query.filter(Document.source_path.like(f"{document.source_path}#split-%")).first()
        if existing_split:
            continue
        results.append(split_document(document, preview_dir, export_dir=export_dir, lang=lang, dpi=dpi))
    return results
