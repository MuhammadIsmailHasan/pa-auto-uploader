import hashlib
import shutil
from pathlib import Path

from sqlalchemy.exc import IntegrityError

from .. import db
from ..models import Document, DocumentStatus


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_pdf_files(source_dir: Path):
    yield from sorted(source_dir.rglob("*.pdf"))


def split_outputs_exist(source_path: str) -> bool:
    split_types = ("Penunjukan Panitera", "Penunjukan Jurusita")
    return all(
        Document.query.filter_by(source_path=f"{source_path}#split-{doc_type}").first() is not None
        for doc_type in split_types
    )


def import_pdf_files(pdf_files, storage_dir: Path, progress_callback=None) -> dict[str, int | list[int]]:
    storage_dir.mkdir(parents=True, exist_ok=True)
    result = {"imported": 0, "skipped": 0, "failed": 0, "imported_ids": []}
    pdf_files = list(pdf_files)
    total = len(pdf_files)

    for index, pdf_path in enumerate(pdf_files, start=1):
        if progress_callback:
            progress_callback(index, total, pdf_path)
        try:
            source_path = str(pdf_path.resolve())
            digest = sha256_file(pdf_path)
            existing = Document.query.filter_by(source_path=source_path).first()
            versioned_source_path = f"{source_path}#sha256-{digest}"
            existing_version = Document.query.filter_by(source_path=versioned_source_path).first()
            if existing_version or split_outputs_exist(versioned_source_path) or (existing and existing.file_sha256 == digest):
                result["skipped"] += 1
                continue
            if existing:
                # A file in the selected folder may have been corrected after its
                # first import. Keep the old record and import the new contents.
                source_path = versioned_source_path
            elif split_outputs_exist(source_path):
                result["skipped"] += 1
                continue
            stored_name = f"{digest[:16]}_{pdf_path.name}"
            stored_path = storage_dir / stored_name
            if not stored_path.exists():
                shutil.copy2(pdf_path, stored_path)

            document = Document(
                source_path=source_path,
                file_path=str(stored_path),
                original_filename=pdf_path.name,
                file_sha256=digest,
                file_size=pdf_path.stat().st_size,
                status=DocumentStatus.NEW,
            )
            db.session.add(document)
            db.session.commit()
            result["imported"] += 1
            result["imported_ids"].append(document.id)
        except IntegrityError:
            db.session.rollback()
            result["skipped"] += 1
        except Exception:
            db.session.rollback()
            result["failed"] += 1

    return result


def import_pdfs(source_dir: Path, storage_dir: Path, progress_callback=None) -> dict[str, int | list[int]]:
    return import_pdf_files(iter_pdf_files(source_dir), storage_dir, progress_callback=progress_callback)
