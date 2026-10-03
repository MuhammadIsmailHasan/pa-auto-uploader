from datetime import datetime

from . import db


class DocumentStatus:
    NEW = "baru"
    IDENTIFIED = "teridentifikasi"
    SPLIT = "dipisahkan"
    NEEDS_VERIFICATION = "perlu_verifikasi"
    READY_UPLOAD = "siap_upload"
    UPLOAD_SUCCESS = "berhasil_upload"
    UPLOAD_FAILED = "gagal_upload"
    SKIPPED_EXISTING = "sudah_ada_di_sipp"

    ALL = [
        NEW,
        IDENTIFIED,
        SPLIT,
        NEEDS_VERIFICATION,
        READY_UPLOAD,
        UPLOAD_SUCCESS,
        UPLOAD_FAILED,
        SKIPPED_EXISTING,
    ]


class Document(db.Model):
    __tablename__ = "documents"

    id = db.Column(db.Integer, primary_key=True)
    source_path = db.Column(db.String(512), nullable=False, unique=True, index=True)
    file_path = db.Column(db.String(1024), nullable=False)
    export_path = db.Column(db.String(1024))
    original_filename = db.Column(db.String(255), nullable=False)
    new_filename = db.Column(db.String(255))
    file_sha256 = db.Column(db.String(64), index=True)
    file_size = db.Column(db.BigInteger)

    case_number = db.Column(db.String(128), index=True)
    document_type = db.Column(db.String(128), index=True)
    source_draft_id = db.Column(db.Integer, index=True)
    sipp_hearing_id = db.Column(db.BigInteger, index=True)
    hearing_order = db.Column(db.Integer)
    hearing_date = db.Column(db.Date)
    assigned_clerk_id = db.Column(db.Integer, index=True)
    assigned_clerk_name = db.Column(db.String(255))
    ocr_text = db.Column(db.Text(length=16_777_215))
    ocr_engine = db.Column(db.String(64))
    preview_path = db.Column(db.String(1024))

    status = db.Column(db.String(32), nullable=False, default=DocumentStatus.NEW, index=True)
    process_started_at = db.Column(db.DateTime)
    processed_at = db.Column(db.DateTime)
    uploaded_at = db.Column(db.DateTime)
    upload_response = db.Column(db.Text)
    error_message = db.Column(db.Text)

    is_verified = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    upload_logs = db.relationship("UploadLog", back_populates="document", cascade="all, delete-orphan")


class UploadLog(db.Model):
    __tablename__ = "upload_logs"

    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey("documents.id"), nullable=False, index=True)
    status = db.Column(db.String(32), nullable=False)
    message = db.Column(db.Text)
    response_text = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    document = db.relationship("Document", back_populates="upload_logs")


class UploadAccount(db.Model):
    __tablename__ = "upload_accounts"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(128), nullable=False, index=True)
    login_url = db.Column(db.String(1024), nullable=False)
    username = db.Column(db.String(255), nullable=False)
    password = db.Column(db.String(255), nullable=False)
    sipp_panitera_id = db.Column(db.Integer, index=True)
    sipp_panitera_name = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
