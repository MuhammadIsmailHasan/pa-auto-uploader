import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "mysql+pymysql://root:password@127.0.0.1/perkara_pdf_manager?charset=utf8mb4",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 280,
        "pool_size": 10,
        "max_overflow": 20,
    }
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_UPLOAD_MB", "20480")) * 1024 * 1024
    MAX_FORM_MEMORY_SIZE = int(os.getenv("MAX_FORM_MEMORY_MB", "64")) * 1024 * 1024
    MAX_FORM_PARTS = int(os.getenv("MAX_FORM_PARTS", "20000"))

    IMPORT_SOURCE_DIR = Path(os.getenv("IMPORT_SOURCE_DIR", BASE_DIR / "uploads"))
    STORAGE_DIR = Path(os.getenv("STORAGE_DIR", BASE_DIR / "processed"))
    PREVIEW_DIR = Path(os.getenv("PREVIEW_DIR", BASE_DIR / "previews"))
    EXPORT_DIR = Path(os.getenv("EXPORT_DIR", BASE_DIR / "hasil_identifikasi"))
    UPLOADED_DIR = Path(os.getenv("UPLOADED_DIR", BASE_DIR / "uploaded"))
    LOG_DIR = Path(os.getenv("LOG_DIR", BASE_DIR / "logs"))
    REGISTRATION_TEMPLATE_DIR = Path(os.getenv("REGISTRATION_TEMPLATE_DIR", "/var/www/pmword/contoh daftr"))
    REGISTRATION_SIGNATURE_DIR = Path(os.getenv("REGISTRATION_SIGNATURE_DIR", "/home/panitera/e_kepaniteraan_integration_stage/assets/tte/bas"))
    SIPP_RO_HOST = os.getenv("SIPP_RO_HOST", "192.168.1.7")
    SIPP_RO_PORT = int(os.getenv("SIPP_RO_PORT", "3306"))
    SIPP_RO_DATABASE = os.getenv("SIPP_RO_DATABASE", "sipp")
    SIPP_RO_USER = os.getenv("SIPP_RO_USER", "panitera")
    SIPP_RO_PASSWORD = os.getenv("SIPP_RO_PASSWORD", "")
    WICAKSANA_BAS_API = os.getenv(
        "WICAKSANA_BAS_API", "http://127.0.0.1/wicaksana/api/bas_ready.php"
    )

    OCR_DPI = int(os.getenv("OCR_DPI", "200"))
    OCR_LANG = os.getenv("OCR_LANG", "ind")
    MAX_OCR_PAGES = int(os.getenv("MAX_OCR_PAGES", "3"))
    RENAME_APPLY = os.getenv("RENAME_APPLY", "false").lower() == "true"

    SELENIUM_BROWSER = os.getenv("SELENIUM_BROWSER", "chrome")
    SELENIUM_HEADLESS = os.getenv("SELENIUM_HEADLESS", "false").lower() == "true"
    SELENIUM_HUMAN_DELAY = os.getenv("SELENIUM_HUMAN_DELAY", "true").lower() == "true"
    # Browser otomatis harus ditutup setelah batch selesai. Membiarkannya hidup
    # akan menumpuk proses Chrome/ChromeDriver di service Gunicorn.
    SELENIUM_KEEP_BROWSER_OPEN = os.getenv("SELENIUM_KEEP_BROWSER_OPEN", "false").lower() == "true"
    TARGET_LOGIN_URL = os.getenv("TARGET_LOGIN_URL", "")
    TARGET_USERNAME = os.getenv("TARGET_USERNAME", "")
    TARGET_PASSWORD = os.getenv("TARGET_PASSWORD", "")
    TARGET_SELECTORS_FILE = Path(
        os.getenv("TARGET_SELECTORS_FILE", BASE_DIR / "config" / "selenium_selectors.example.json")
    )
