import shutil
from pathlib import Path

from .. import db
from ..models import Document
from .renamer import build_new_filename


def unique_target_path(directory: Path, filename: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / filename
    counter = 2
    while target.exists():
        target = directory / f"{target.stem} ({counter}){target.suffix}"
        counter += 1
    return target


def export_document(document: Document, export_dir: Path) -> Path | None:
    if not document.case_number or not document.document_type:
        return None

    target = unique_target_path(export_dir, build_new_filename(document))
    shutil.copy2(document.file_path, target)
    document.export_path = str(target)
    document.new_filename = target.name
    db.session.commit()
    return target
