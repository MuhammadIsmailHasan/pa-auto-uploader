import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from selenium.common.exceptions import InvalidSessionIdException

from app import create_app, db
from app.models import Document, DocumentStatus, UploadAccount
from app.services.uploader import (
    SeleniumConfig,
    find_bas_upload_link_and_state,
    find_upload_link_and_state,
    upload_ready_documents,
    upload_document_on_current_case,
)
from app.services.processor import process_documents_by_ids
from app.services.importer import import_pdf_files
from app.services.splitter import is_combined_panitera_jurusita, recover_jurusita_from_uploaded_combined
from app.routes.dashboard import folder_document_audit


class TestConfig:
    TESTING = True
    SECRET_KEY = "test"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024
    MAX_FORM_MEMORY_SIZE = 1024 * 1024
    MAX_FORM_PARTS = 100
    OCR_LANG = "ind"
    OCR_DPI = 100
    MAX_OCR_PAGES = 1
    RENAME_APPLY = False
    SELENIUM_BROWSER = "chrome"
    SELENIUM_HEADLESS = True
    SELENIUM_HUMAN_DELAY = False
    SELENIUM_KEEP_BROWSER_OPEN = False
    TARGET_SELECTORS_FILE = Path("config/selenium_selectors.example.json")


class FakeElement:
    def __init__(self, text="", attrs=None):
        self.text = text
        self.attrs = attrs or {}

    def get_attribute(self, name):
        return self.attrs.get(name)


class FakeRow(FakeElement):
    def __init__(self, text, controls):
        super().__init__(text=text)
        self.controls = controls

    def find_elements(self, by, selector):
        if "fileupload" in selector:
            return [item for item in self.controls if "fileupload" in (item.get_attribute("onclick") or "")]
        return self.controls


class FakeDriver:
    def __init__(self, rows):
        self.rows = rows

    def find_elements(self, by, selector):
        return self.rows if selector == "tr" else []


class FakeWait:
    def until(self, condition):
        return True


class FakeBasRow:
    def __init__(self, order, upload_link=None, existing_link=None):
        self.order = order
        self.upload_link = upload_link
        self.existing_link = existing_link

    def find_elements(self, by, selector):
        if selector == "td":
            return [FakeElement(text=str(self.order))]
        if "fileupload" in selector:
            return [self.upload_link] if self.upload_link else []
        if "Unduh Dokumen BAS" in selector:
            return [self.existing_link] if self.existing_link else []
        return []


class FakeBasDriver:
    def __init__(self, rows):
        self.rows = rows

    def find_elements(self, by, selector):
        return self.rows if selector == "#tabs4 tr" else []


class RecoveryControlsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        for key, folder in (
            ("IMPORT_SOURCE_DIR", "uploads"),
            ("STORAGE_DIR", "processed"),
            ("PREVIEW_DIR", "previews"),
            ("EXPORT_DIR", "exports"),
            ("UPLOADED_DIR", "uploaded"),
            ("LOG_DIR", "logs"),
        ):
            path = root / folder
            path.mkdir()
            setattr(TestConfig, key, path)
        self.app = create_app(TestConfig)
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()
        self.temp.cleanup()

    def make_document(self, status, filename="sample.pdf"):
        path = TestConfig.STORAGE_DIR / filename
        path.write_bytes(b"%PDF-test")
        document = Document(
            source_path=str(TestConfig.IMPORT_SOURCE_DIR / filename),
            file_path=str(path),
            original_filename=filename,
            case_number="1/Pdt.G/2026/PA.Ngw",
            document_type="Penetapan Majelis Hakim",
            status=status,
            is_verified=True,
            error_message="Kesalahan uji",
        )
        db.session.add(document)
        db.session.commit()
        return document

    def test_failed_document_can_be_prepared_again(self):
        document = self.make_document(DocumentStatus.UPLOAD_FAILED)
        response = self.client.post(f"/documents/{document.id}/retry-upload")
        self.assertEqual(response.status_code, 302)
        db.session.refresh(document)
        self.assertEqual(document.status, DocumentStatus.READY_UPLOAD)
        self.assertIsNone(document.error_message)

    def test_imports_changed_contents_under_the_same_filename(self):
        source = TestConfig.IMPORT_SOURCE_DIR / "Penetapan-Hari-Sidang-1636.pdf"
        source.write_bytes(b"%PDF-first-version")
        first = import_pdf_files([source], TestConfig.STORAGE_DIR)
        self.assertEqual(first["imported"], 1)

        source.write_bytes(b"%PDF-corrected-version")
        second = import_pdf_files([source], TestConfig.STORAGE_DIR)
        self.assertEqual(second["imported"], 1)
        self.assertEqual(import_pdf_files([source], TestConfig.STORAGE_DIR)["skipped"], 1)
        self.assertEqual(Document.query.count(), 2)
        self.assertIn("#sha256-", db.session.get(Document, second["imported_ids"][0]).source_path)

    def test_combined_detection_accepts_line_break_between_panitera_and_pengganti(self):
        document = self.make_document(DocumentStatus.UPLOAD_SUCCESS)
        document.document_type = "Penunjukan Panitera"
        document.ocr_text = "Menunjuk Panitera\nPengganti; menunjuk Jurusita Pengganti"
        self.assertTrue(is_combined_panitera_jurusita(document))

    def test_closed_browser_keeps_document_ready_for_safe_recheck(self):
        document = self.make_document(DocumentStatus.READY_UPLOAD)
        config = SeleniumConfig("chrome", True, "", "", "", Path("config/selenium_selectors.example.json"))
        with patch("app.services.uploader.open_document_section", side_effect=InvalidSessionIdException("invalid session id")):
            session_ok = upload_document_on_current_case(document, object(), object(), {}, config)
        self.assertFalse(session_ok)
        db.session.refresh(document)
        self.assertEqual(document.status, DocumentStatus.READY_UPLOAD)
        self.assertIn("Sesi browser terputus", document.error_message)

    def test_recover_pjs_preserves_uploaded_combined_document(self):
        document = self.make_document(DocumentStatus.UPLOAD_SUCCESS, "combined.pdf")
        document.case_number = "1633/Pdt.G/2026/PA.Ngw"
        document.document_type = "Penunjukan Panitera"
        document.ocr_text = "Panitera\nPengganti dan Jurusita Pengganti"
        db.session.commit()
        pages = ["1633/Pdt.G/2026/PA.Ngw Panitera Pengganti", "1633/Pdt.G/2026/PA.Ngw Jurusita Pengganti"]

        def write_sample(_source, _pages, target):
            target.write_bytes(b"%PDF-jurusita-page")

        with patch("app.services.splitter.page_texts", return_value=pages), patch(
            "app.services.splitter.write_pdf_pages", side_effect=write_sample
        ), patch("app.services.splitter.create_first_page_preview", return_value=None):
            recovered = recover_jurusita_from_uploaded_combined(
                document, TestConfig.PREVIEW_DIR, TestConfig.EXPORT_DIR
            )
        self.assertEqual(recovered.document_type, "Penunjukan Jurusita")
        self.assertEqual(recovered.status, DocumentStatus.READY_UPLOAD)
        self.assertTrue(Path(recovered.file_path).exists())
        self.assertEqual(db.session.get(Document, document.id).status, DocumentStatus.UPLOAD_SUCCESS)
        self.assertTrue(Path(document.file_path).exists())

    def test_needs_verification_document_can_be_deleted(self):
        document = self.make_document(DocumentStatus.NEEDS_VERIFICATION)
        file_path = Path(document.file_path)
        response = self.client.post(f"/documents/{document.id}/delete")
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(db.session.get(Document, document.id))
        self.assertFalse(file_path.exists())

    def test_dashboard_exposes_recovery_and_folder_readiness_controls(self):
        self.make_document(DocumentStatus.UPLOAD_FAILED)
        response = self.client.get("/")
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Mulai Import Folder", body)
        self.assertIn("Belum ada folder dipilih", body)
        self.assertIn("Siapkan Ulang", body)
        self.assertIn("Error terakhir", body)
        self.assertIn("polling = null;", body)

    def test_dashboard_hides_documents_confirmed_already_in_sipp(self):
        document = self.make_document(DocumentStatus.UPLOAD_SUCCESS, "already-there.pdf")
        document.upload_response = "Sudah ada tombol/icon PDF di baris dokumen."
        db.session.commit()

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("already-there.pdf", response.get_data(as_text=True))

    def test_folder_audit_reports_known_document_state(self):
        document = self.make_document(DocumentStatus.UPLOAD_SUCCESS, "known.pdf")
        document.upload_response = "Sudah ada tombol/icon PDF di baris dokumen."
        db.session.commit()

        audit = folder_document_audit([Path(document.source_path)])

        self.assertEqual(audit["records"], 1)
        self.assertEqual(audit["identified"], 1)
        self.assertEqual(audit["already_in_sipp"], 1)
        self.assertEqual(audit["upload_failed"], 0)

    def test_existing_pdf_is_success_state_even_without_upload_button(self):
        pdf = FakeElement(attrs={"href": "/document/pmh.pdf", "title": "Pdf"})
        row = FakeRow("Penetapan Majelis Hakim Pdf", [pdf])
        upload_link, already_has_pdf = find_upload_link_and_state(FakeDriver([row]), None, "dokpmh")
        self.assertIsNone(upload_link)
        self.assertTrue(already_has_pdf)

    def test_pdf_image_inside_link_is_detected(self):
        pdf_icon_link = FakeElement(
            attrs={
                "href": "/perkara/dokumen/lihat/123",
                "outerHTML": '<a href="/perkara/dokumen/lihat/123"><img src="/images/pdf-icon.png"></a>',
            }
        )
        row = FakeRow("Penetapan Hari Sidang", [pdf_icon_link])
        upload_link, already_has_pdf = find_upload_link_and_state(FakeDriver([row]), None, "dokphs")
        self.assertIsNone(upload_link)
        self.assertTrue(already_has_pdf)

    def test_phs_skips_generic_hari_sidang_row_and_finds_document_row(self):
        information_row = FakeRow("Hari Sidang Pertama Senin, 10 Agustus 2026", [])
        document_link = FakeElement(
            attrs={
                "href": "/perkara/dokumen/lihat/456",
                "outerHTML": '<a href="/perkara/dokumen/lihat/456"><img src="/images/pdf-icon.png"></a>',
            }
        )
        document_row = FakeRow("Penetapan Hari Sidang", [document_link])

        upload_link, already_has_pdf = find_upload_link_and_state(
            FakeDriver([information_row, document_row]), None, "dokphs"
        )

        self.assertIsNone(upload_link)
        self.assertTrue(already_has_pdf)

    def test_bas_finds_exact_hearing_order(self):
        upload = FakeElement(text="Unggah BAS", attrs={"onclick": "/fileupload/1/bas/3"})
        document = self.make_document(DocumentStatus.READY_UPLOAD, "bas.pdf")
        document.document_type = "Berita Acara Sidang"
        document.hearing_order = 3
        db.session.commit()

        upload_link, already_has_pdf = find_bas_upload_link_and_state(
            FakeBasDriver([FakeBasRow(2), FakeBasRow(3, upload_link=upload)]),
            FakeWait(),
            document,
        )

        self.assertIs(upload_link, upload)
        self.assertFalse(already_has_pdf)

    def test_bas_without_own_clerk_account_stays_queued(self):
        document = self.make_document(DocumentStatus.READY_UPLOAD, "bas-queued.pdf")
        document.document_type = "Berita Acara Sidang"
        document.assigned_clerk_id = 29
        document.assigned_clerk_name = "Panitera Pengganti Uji"
        fallback = UploadAccount(
            name="Akun orang lain",
            role="panitera",
            login_url="http://example.test/login",
            username="other",
            password="secret",
            is_active=True,
        )
        db.session.add(fallback)
        db.session.commit()
        config = SeleniumConfig(
            browser="chrome",
            headless=True,
            login_url="",
            username="",
            password="",
            selectors_file=TestConfig.TARGET_SELECTORS_FILE,
            uploaded_dir=TestConfig.UPLOADED_DIR,
            slow_mode=False,
            keep_browser_open=False,
        )

        upload_ready_documents(
            limit=None,
            config=config,
            accounts_by_role={"panitera": fallback},
            accounts_by_clerk={},
        )

        db.session.refresh(document)
        self.assertEqual(document.status, DocumentStatus.READY_UPLOAD)
        self.assertIn("tidak dialihkan", document.error_message)

    def test_processing_skips_document_removed_while_batch_is_running(self):
        first = self.make_document(DocumentStatus.NEW, "first.pdf")
        second = self.make_document(DocumentStatus.NEW, "second.pdf")
        seen = []

        def remove_next_document(document, *args):
            if document.id == first.id:
                db.session.delete(db.session.get(Document, second.id))
                db.session.commit()

        with patch("app.services.processor.process_document", side_effect=remove_next_document):
            processed = process_documents_by_ids(
                [first.id, second.id],
                "ind",
                100,
                1,
                TestConfig.PREVIEW_DIR,
                TestConfig.EXPORT_DIR,
                progress_callback=lambda index, total, document: seen.append(document.original_filename),
            )

        self.assertEqual(processed, 1)
        self.assertEqual(seen, ["first.pdf"])


if __name__ == "__main__":
    unittest.main()
