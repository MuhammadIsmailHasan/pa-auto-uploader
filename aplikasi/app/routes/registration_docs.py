from io import BytesIO
from pathlib import Path

from flask import Blueprint, current_app, jsonify, render_template, request, send_file

from ..services.registration_docs import TEMPLATES, generate_registration_document
from ..services.sipp_readonly import SippReadOnly, number_to_words

registration_docs_bp = Blueprint("registration_docs", __name__, url_prefix="/registration-docs")


@registration_docs_bp.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        values = request.form.to_dict()
        # Data penetapan tidak boleh dipercaya dari state formulir/browser.
        # Baca ulang dari SIPP saat cetak agar perkara yang sebelumnya dipilih
        # tidak dapat meninggalkan nama hakim, PP, atau JS/JSP lama.
        number = values.get("nomor", "").strip()
        if number:
            live = SippReadOnly(current_app.config).find_case(number)
            if live:
                authoritative = (
                    "tanggal", "jenis_perkara", "pihak_1", "pihak_2", "nama_skum",
                    "biaya", "terbilang", "hakim_ketua", "hakim_anggota_1",
                    "hakim_anggota_2", "pp", "pp_role", "js", "sidang", "case_flow", "kuasa", "is_ghaib",
                    "pihak_1_email", "kuasa_email", "kuasa_alamat", "parties_1", "parties_2", "parties_4", "lawyers",
                )
                for key in authoritative:
                    values[key] = live.get(key, "")
                values["bailiffs"] = live.get("bailiffs", [])
                values["kind"] = live["template_kind"]
        if not values.get("terbilang", "").strip():
            amount = int("".join(character for character in values.get("biaya", "") if character.isdigit()) or 0)
            values["terbilang"] = (number_to_words(amount) + " rupiah") if amount else ""
        payload, filename = generate_registration_document(
            Path(current_app.config["REGISTRATION_TEMPLATE_DIR"]),
            values.get("kind", ""),
            values,
            Path(current_app.config["REGISTRATION_SIGNATURE_DIR"]),
        )
        return send_file(
            BytesIO(payload),
            as_attachment=True,
            download_name=filename,
            mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    return render_template("registration_docs/index.html", templates=TEMPLATES)


@registration_docs_bp.get("/lookup")
def lookup():
    number = request.args.get("number", "").strip()
    if not number:
        return jsonify({"ok": False, "message": "Masukkan nomor perkara."}), 400
    try:
        data = SippReadOnly(current_app.config).find_case(number)
    except Exception as exc:
        current_app.logger.exception("Lookup SIPP read-only gagal")
        return jsonify({"ok": False, "message": f"SIPP tidak dapat dibaca: {exc}"}), 503
    if not data:
        return jsonify({"ok": False, "message": "Nomor perkara tidak ditemukan di SIPP."}), 404
    return jsonify({"ok": True, "data": data})


@registration_docs_bp.get("/cases")
def cases():
    value = request.args.get("date", "").strip()
    try:
        rows = SippReadOnly(current_app.config).cases_on_date(value)
    except ValueError:
        return jsonify({"ok": False, "message": "Tanggal tidak valid."}), 400
    except Exception as exc:
        current_app.logger.exception("Daftar perkara SIPP read-only gagal")
        return jsonify({"ok": False, "message": f"SIPP tidak dapat dibaca: {exc}"}), 503
    return jsonify({"ok": True, "items": rows})
