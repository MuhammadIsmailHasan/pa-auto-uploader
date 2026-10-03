from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import create_app, db
from app.models import Document
from app.services.identification import identify_document


def main():
    app = create_app()
    with app.app_context():
        db.session.query(Document.id).limit(1).all()

    result = identify_document(
        "Nomor 123/Pdt.G/2025/PA.Ngw Penetapan Majelis Hakim menetapkan majelis hakim"
    )
    assert result.case_number == "123/Pdt.G/2025/PA.Ngw"
    assert result.document_type == "Penetapan Majelis Hakim"

    for path in [
        app.config["STORAGE_DIR"],
        app.config["PREVIEW_DIR"],
        app.config["EXPORT_DIR"],
        app.config["LOG_DIR"],
        Path(app.config["IMPORT_SOURCE_DIR"]),
    ]:
        path.mkdir(parents=True, exist_ok=True)

    print("Healthcheck OK: database, konfigurasi, dan identifikasi dasar berfungsi.")


if __name__ == "__main__":
    main()
