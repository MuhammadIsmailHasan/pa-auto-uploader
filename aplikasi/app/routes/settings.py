from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from .. import db
from ..models import UploadAccount
from ..services.sipp_readonly import SippReadOnly

settings_bp = Blueprint("settings", __name__)
UPLOAD_ROLES = [
    ("ketua", "Ketua - Penetapan Hakim/Majelis Hakim"),
    ("panitera", "Panitera - Penunjukan Panitera/Jurusita"),
    ("hakim", "Hakim - Penetapan Hari Sidang"),
    ("bas", "BAS - akun Panitera/PP masing-masing"),
]


def active_sipp_clerks():
    try:
        return SippReadOnly(current_app.config).query(
            "SELECT id, nama FROM panitera_pn WHERE aktif='Y' ORDER BY nama"
        )
    except Exception:
        return []


@settings_bp.route("/upload-accounts", methods=["GET", "POST"])
def upload_accounts():
    clerks = active_sipp_clerks()
    clerks_by_id = {int(clerk["id"]): clerk for clerk in clerks}
    if request.method == "POST":
        account_id = request.form.get("account_id", type=int)
        account = UploadAccount.query.get(account_id) if account_id else UploadAccount()

        account.name = request.form.get("name", "").strip()
        account.role = request.form.get("role", "").strip().lower()
        account.login_url = request.form.get("login_url", "").strip()
        account.username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if password or not account.id:
            account.password = password
        account.is_active = request.form.get("is_active") == "on"
        clerk_id = request.form.get("sipp_panitera_id", type=int)
        if clerk_id:
            clerk = clerks_by_id.get(clerk_id)
            if not clerk:
                flash("Identitas Panitera/PP tidak ditemukan pada daftar aktif SIPP.", "danger")
                return redirect(url_for("settings.upload_accounts"))
            duplicate = UploadAccount.query.filter(
                UploadAccount.sipp_panitera_id == clerk_id,
                UploadAccount.id != (account.id or 0),
            ).first()
            if duplicate:
                flash(f"Panitera/PP tersebut sudah dipetakan ke akun {duplicate.name}.", "danger")
                return redirect(url_for("settings.upload_accounts"))
            account.sipp_panitera_id = clerk_id
            account.sipp_panitera_name = clerk["nama"]
        else:
            account.sipp_panitera_id = None
            account.sipp_panitera_name = None

        if not account.name or not account.role or not account.login_url or not account.username or not account.password:
            flash("Nama, peran, URL login, username, dan password wajib diisi.", "danger")
            return redirect(url_for("settings.upload_accounts"))

        db.session.add(account)
        db.session.commit()
        flash("Akun upload disimpan.", "success")
        return redirect(url_for("settings.upload_accounts"))

    accounts = UploadAccount.query.order_by(UploadAccount.role.asc(), UploadAccount.name.asc()).all()
    edit_id = request.args.get("edit", type=int)
    edit_account = UploadAccount.query.get(edit_id) if edit_id else None
    return render_template(
        "settings/upload_accounts.html",
        accounts=accounts,
        edit_account=edit_account,
        upload_roles=UPLOAD_ROLES,
        clerks=clerks,
    )


@settings_bp.route("/upload-accounts/<int:account_id>/delete", methods=["POST"])
def delete_upload_account(account_id):
    account = UploadAccount.query.get_or_404(account_id)
    db.session.delete(account)
    db.session.commit()
    flash("Akun upload dihapus.", "success")
    return redirect(url_for("settings.upload_accounts"))
