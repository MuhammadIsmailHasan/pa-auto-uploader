from flask import Blueprint, render_template

from ..models import UploadLog

upload_bp = Blueprint("upload", __name__)


@upload_bp.route("/logs")
def logs():
    entries = UploadLog.query.order_by(UploadLog.created_at.desc()).limit(200).all()
    return render_template("upload/logs.html", entries=entries)
