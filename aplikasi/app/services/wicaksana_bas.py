import hashlib
import json
from datetime import datetime
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from .. import db
from ..models import Document, DocumentStatus
from .sipp_readonly import SippReadOnly
from .uploader import mark_existing_bas


DOCUMENT_TYPE = "Berita Acara Sidang"


def _request_json(url: str, payload: dict | None = None) -> dict:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="GET" if payload is None else "POST",
    )
    try:
        with urlopen(request, timeout=10) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Koneksi draf BAS E-Kepaniteraan gagal: {exc}") from exc
    if not result.get("ok"):
        raise RuntimeError(result.get("message") or "Respons E-Kepaniteraan tidak valid.")
    return result


def notify_wicaksana(url: str, draft_id: int, status: str, message: str) -> None:
    _request_json(url, {"draft_id": draft_id, "status": status, "message": message})


def skip_existing_bas_in_sipp(config, ready_draft_ids: set[int]) -> int:
    if not ready_draft_ids:
        return 0
    documents = Document.query.filter(
        Document.source_draft_id.isnot(None),
        Document.source_draft_id.in_(ready_draft_ids),
        Document.document_type == DOCUMENT_TYPE,
        Document.status == DocumentStatus.READY_UPLOAD,
        Document.sipp_hearing_id.isnot(None),
    ).all()
    by_hearing = {}
    for document in documents:
        by_hearing.setdefault(document.sipp_hearing_id, []).append(document)
    hearing_ids = list(by_hearing)
    skipped = 0
    for start in range(0, len(hearing_ids), 200):
        batch = hearing_ids[start:start + 200]
        placeholders = ",".join(["%s"] * len(batch))
        rows = SippReadOnly(config).query(
            f"SELECT id,edoc_bas FROM perkara_jadwal_sidang WHERE id IN ({placeholders})",
            tuple(batch),
        )
        for row in rows:
            if str(row.get("edoc_bas") or "").strip() in ("", "0", "-"):
                continue
            for document in by_hearing[int(row["id"])]:
                mark_existing_bas(document, "Kolom edoc_bas pada jadwal sidang SIPP sudah terisi; perkara ini dilewati.")
                skipped += 1
    return skipped


def import_ready_bas(url: str) -> dict[str, int | list[int]]:
    items = _request_json(url).get("items") or []
    result = {"imported": 0, "updated": 0, "missing": 0, "ready_ids": []}
    for item in items:
        draft_id = int(item.get("draft_id") or 0)
        pdf_path = Path(str(item.get("pdf_path") or ""))
        if draft_id <= 0 or not pdf_path.is_file() or pdf_path.suffix.lower() != ".pdf":
            result["missing"] += 1
            continue
        result["ready_ids"].append(draft_id)
        source_path = f"wicaksana-bas:{draft_id}"
        document = Document.query.filter_by(source_path=source_path).first()
        created = document is None
        if created:
            document = Document(source_path=source_path, file_path=str(pdf_path), original_filename=pdf_path.name)
            db.session.add(document)
        document.file_path = str(pdf_path)
        document.original_filename = pdf_path.name
        document.new_filename = pdf_path.name
        document.file_size = pdf_path.stat().st_size
        document.file_sha256 = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
        document.case_number = str(item.get("nomor_perkara") or "")
        document.document_type = DOCUMENT_TYPE
        document.source_draft_id = draft_id
        document.sipp_hearing_id = int(item.get("sidang_id") or 0) or None
        document.hearing_order = int(item.get("sidang_ke") or 0) or None
        hearing_date = str(item.get("tanggal_sidang") or "")
        document.hearing_date = datetime.strptime(hearing_date, "%Y-%m-%d").date() if hearing_date else None
        document.assigned_clerk_id = int(item.get("pp_id") or 0) or None
        document.assigned_clerk_name = str(item.get("pp_nama") or "")
        document.ocr_engine = "e-kepaniteraan"
        document.ocr_text = "Draf BAS otomatis dari E-Kepaniteraan"
        document.is_verified = True
        if document.status not in (DocumentStatus.UPLOAD_SUCCESS, DocumentStatus.SKIPPED_EXISTING):
            document.status = DocumentStatus.READY_UPLOAD
            document.error_message = None
        db.session.commit()
        if document.status == DocumentStatus.READY_UPLOAD:
            notify_wicaksana(url, draft_id, "diantrekan", "PDF masuk antrean Auto PDF Uploader.")
        elif document.status == DocumentStatus.SKIPPED_EXISTING:
            notify_wicaksana(url, draft_id, "sudah_ada", "BAS sudah terisi di SIPP; upload dilewati.")
        result["imported" if created else "updated"] += 1
    return result
