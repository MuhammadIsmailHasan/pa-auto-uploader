import json
import glob
import os
import random
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.common.exceptions import InvalidSessionIdException, TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

from .. import db
from ..models import Document, DocumentStatus, UploadAccount, UploadLog

ROLE_KETUA = "ketua"
ROLE_PANITERA = "panitera"
ROLE_HAKIM = "hakim"
ROLE_BAS = "bas"
HUMAN_DELAY_ENABLED = True


@dataclass
class SeleniumConfig:
    browser: str
    headless: bool
    login_url: str
    username: str
    password: str
    selectors_file: Path
    uploaded_dir: Path | None = None
    slow_mode: bool = True
    keep_browser_open: bool = True


def normalized_document_type(document: Document) -> str:
    return (document.document_type or "").lower()


def is_pmh_document(document: Document) -> bool:
    document_type = normalized_document_type(document)
    return (
        "majelis hakim" in document_type
        or "hakim tunggal" in document_type
        or document_type == "penetapan hakim"
    )


def is_ppp_document(document: Document) -> bool:
    document_type = normalized_document_type(document)
    return (
        "penunjukan panitera" in document_type
        or "panitera pengganti" in document_type
        or document_type in {"ppp", "penunjukan pp"}
    )


def is_jsp_document(document: Document) -> bool:
    document_type = normalized_document_type(document)
    return (
        "penunjukan jurusita" in document_type
        or "jurusita pengganti" in document_type
        or "gabungan pp/jurusita" in document_type
    )


def is_phs_document(document: Document) -> bool:
    return "hari sidang" in normalized_document_type(document)


def is_bas_document(document: Document) -> bool:
    return "berita acara sidang" in normalized_document_type(document)


def upload_role_for_document(document: Document) -> str | None:
    if is_bas_document(document):
        return ROLE_BAS
    if is_pmh_document(document):
        return ROLE_KETUA
    if is_ppp_document(document):
        return ROLE_KETUA
    if is_jsp_document(document):
        return ROLE_PANITERA
    if is_phs_document(document):
        return ROLE_HAKIM
    return None


def build_config_for_account(base_config: SeleniumConfig, account: UploadAccount) -> SeleniumConfig:
    return SeleniumConfig(
        browser=base_config.browser,
        headless=base_config.headless,
        login_url=account.login_url,
        username=account.username,
        password=account.password,
        selectors_file=base_config.selectors_file,
        uploaded_dir=base_config.uploaded_dir,
        slow_mode=base_config.slow_mode,
        keep_browser_open=base_config.keep_browser_open,
    )


def safe_folder_name(value: str) -> str:
    value = value.replace("/", "_")
    value = re.sub(r"[^A-Za-z0-9._ -]+", "", value)
    return re.sub(r"\s+", " ", value).strip() or "tanpa_nomor"


def archive_uploaded_document(document: Document, uploaded_dir: Path | None) -> Path | None:
    if not uploaded_dir:
        return None
    case_dir = uploaded_dir / safe_folder_name(document.case_number or "tanpa_nomor")
    case_dir.mkdir(parents=True, exist_ok=True)
    source_path = Path(document.file_path)
    target_path = case_dir / (document.new_filename or source_path.name)
    counter = 2
    while target_path.exists():
        target_path = case_dir / f"{target_path.stem} ({counter}){target_path.suffix}"
        counter += 1
    shutil.copy2(source_path, target_path)
    return target_path


def load_selectors(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def ensure_gui_environment() -> None:
    path_parts = os.environ.get("PATH", "").split(":")
    for path in ("/usr/local/bin", "/usr/bin", "/bin"):
        if path not in path_parts:
            path_parts.append(path)
    os.environ["PATH"] = ":".join(part for part in path_parts if part)

    if not os.environ.get("DISPLAY"):
        os.environ["DISPLAY"] = ":0"
    if not os.environ.get("XAUTHORITY"):
        uid = os.getuid()
        candidates = sorted(
            glob.glob(f"/run/user/{uid}/.mutter-Xwaylandauth.*"),
            key=os.path.getmtime,
            reverse=True,
        )
        if candidates:
            os.environ["XAUTHORITY"] = candidates[0]


def resolve_chrome_binary() -> str | None:
    configured_path = os.getenv("CHROME_BINARY_PATH")
    if configured_path and Path(configured_path).exists():
        return configured_path
    for candidate in ("/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "/usr/bin/chromium"):
        if Path(candidate).exists():
            return candidate
    return shutil.which("google-chrome") or shutil.which("chromium")


def chrome_major_version(chrome_binary: str | None) -> str | None:
    if not chrome_binary:
        return None
    try:
        output = subprocess.check_output([chrome_binary, "--version"], text=True, timeout=5)
    except Exception:
        return None
    match = re.search(r"(\d+)\.", output)
    return match.group(1) if match else None


def resolve_chromedriver_path(chrome_binary: str | None) -> str | None:
    configured_path = os.getenv("CHROMEDRIVER_PATH")
    if configured_path and Path(configured_path).exists():
        return configured_path

    major = chrome_major_version(chrome_binary)
    cache_patterns = []
    if major:
        cache_patterns.append(f"/home/panitera/.cache/selenium/chromedriver/linux64/{major}.*/*chromedriver")
    cache_patterns.append("/home/panitera/.cache/selenium/chromedriver/linux64/*/*chromedriver")

    for pattern in cache_patterns:
        candidates = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
        for candidate in candidates:
            if Path(candidate).is_file():
                return candidate

    return shutil.which("chromedriver")


def build_driver(config: SeleniumConfig):
    global HUMAN_DELAY_ENABLED
    HUMAN_DELAY_ENABLED = config.slow_mode

    if config.browser.lower() == "edge":
        options = EdgeOptions()
        if config.headless:
            options.add_argument("--headless=new")
        return webdriver.Edge(options=options)

    ensure_gui_environment()
    chrome_binary = resolve_chrome_binary()
    chromedriver_path = resolve_chromedriver_path(chrome_binary)

    options = ChromeOptions()
    if chrome_binary:
        options.binary_location = chrome_binary
    if config.headless:
        options.add_argument("--headless=new")
    elif config.keep_browser_open:
        options.add_experimental_option("detach", True)
    options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-infobars")
    options.add_argument("--window-position=80,60")
    options.add_argument("--window-size=1280,900")
    service = ChromeService(executable_path=chromedriver_path) if chromedriver_path else None
    return webdriver.Chrome(service=service, options=options)


def find(wait: WebDriverWait, selector: str):
    return wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))


def human_pause(min_seconds: float = 0.8, max_seconds: float = 1.2) -> None:
    if not HUMAN_DELAY_ENABLED:
        return
    time.sleep(random.uniform(min_seconds, max_seconds))


def type_like_human(element, value: str) -> None:
    if not HUMAN_DELAY_ENABLED:
        element.send_keys(value)
        return
    for character in value:
        element.send_keys(character)
        time.sleep(random.uniform(0.04, 0.10))


def click(wait: WebDriverWait, selector: str):
    element = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
    element.click()
    human_pause()
    return element


def click_element(driver, element):
    driver.execute_script("arguments[0].scrollIntoView({block:'center', behavior:'smooth'});", element)
    human_pause(0.5, 1.0)
    driver.execute_script("arguments[0].click();", element)
    human_pause()
    return element


def click_text(driver, wait: WebDriverWait, text: str):
    xpath = f"//a[normalize-space()={json.dumps(text)}]"
    element = wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
    return click_element(driver, element)


def submit_or_click(driver, wait: WebDriverWait, selector: str):
    element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
    try:
        click_element(driver, element)
    except Exception:
        driver.execute_script(
            "var el = arguments[0]; var form = el.form || el.closest('form');"
            "if (form && form.requestSubmit) { form.requestSubmit(el); }"
            "else if (form) { form.submit(); }"
            "else { el.click(); }",
            element,
        )
        human_pause()
    return element


def accept_optional_alert(driver, timeout: int = 5) -> str | None:
    try:
        alert = WebDriverWait(driver, timeout).until(lambda current_driver: current_driver.switch_to.alert)
    except TimeoutException:
        return None
    text = alert.text
    alert.accept()
    return text


def case_register_link_text(case_number: str | None) -> str:
    value = case_number or ""
    if "pdt.p" in value.lower():
        return "Register Induk Perkara Permohonan"
    return "Register Induk Perkara Gugatan"


def current_sipp_main_url(driver) -> str | None:
    current_url = driver.current_url
    if "/sipp/" not in current_url:
        return None
    return f"{current_url.split('/sipp/', 1)[0]}/sipp/main"


def upload_target_code(document: Document) -> str | None:
    if is_bas_document(document):
        return "bas"
    if is_pmh_document(document):
        return "dokpmh"
    if is_ppp_document(document):
        return "dokppp"
    if is_jsp_document(document):
        return "dokpjs"
    if is_phs_document(document):
        return "dokphs"
    return None


def upload_order(document: Document) -> int:
    target_code = upload_target_code(document)
    orders = {
        "dokpmh": 10,
        "dokppp": 20,
        "dokpjs": 30,
        "dokphs": 40,
        "bas": 50,
    }
    return orders.get(target_code or "", 99)


def row_has_pdf_button(row) -> bool:
    # Pada beberapa versi/tema SIPP, tombol PDF hanya berupa <img> di dalam
    # sebuah tautan. Teks dan href tautannya sendiri tidak selalu memuat "pdf".
    for element in row.find_elements(By.CSS_SELECTOR, "a, button, input, img"):
        text = element.text or ""
        attrs = " ".join(
            str(element.get_attribute(name) or "")
            for name in ("href", "src", "onclick", "class", "title", "alt", "value", "outerHTML")
        )
        haystack = f"{text} {attrs}".lower()
        if any(marker in haystack for marker in ("pdf", "application/pdf", "fa-file", "icon-file")):
            return True
    return False


TARGET_ROW_LABELS = {
    "dokpmh": ("penetapan majelis hakim", "penetapan hakim"),
    "dokppp": ("penunjukan panitera", "panitera pengganti"),
    "dokpjs": ("penunjukan jurusita", "jurusita pengganti"),
    "dokphs": ("penetapan hari sidang", "hari sidang"),
}


def row_matches_upload_target(row, target_code: str) -> bool:
    row_text = " ".join((row.text or "").lower().split())
    if any(label in row_text for label in TARGET_ROW_LABELS.get(target_code, ())):
        return True
    for element in row.find_elements(By.CSS_SELECTOR, "a, button, input"):
        attrs = " ".join(
            str(element.get_attribute(name) or "")
            for name in ("href", "onclick", "id", "name", "class", "title", "value")
        ).lower()
        if target_code.lower() in attrs:
            return True
    return False


def row_upload_link(row, target_code: str):
    links = row.find_elements(
        By.XPATH,
        ".//a[contains(@onclick, '/fileupload/') and contains(@onclick, "
        f"'/{target_code}/') and normalize-space()='Unggah']",
    )
    return links[0] if links else None


def find_upload_link_and_state(driver, wait: WebDriverWait, target_code: str):
    # Ketika PDF sudah ada, beberapa versi SIPP menyembunyikan tombol Unggah.
    # Karena itu seluruh baris kandidat harus diperiksa. Khusus PHS, tulisan
    # "Hari Sidang" juga muncul pada baris informasi tanggal yang bukan baris
    # dokumen, sehingga tidak boleh berhenti pada kecocokan pertama.
    matched_row_found = False
    for row in driver.find_elements(By.CSS_SELECTOR, "tr"):
        if not row_matches_upload_target(row, target_code):
            continue
        matched_row_found = True
        upload_link = row_upload_link(row, target_code)
        has_pdf = row_has_pdf_button(row)
        if upload_link is not None or has_pdf:
            return upload_link, has_pdf

    if matched_row_found:
        return None, False

    xpath = (
        "//a[contains(@onclick, '/fileupload/') "
        f"and contains(@onclick, '/{target_code}/') "
        "and normalize-space()='Unggah']"
    )
    upload_link = wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
    row = upload_link.find_element(By.XPATH, "./ancestor::tr[1]")
    return upload_link, row_has_pdf_button(row)


def open_document_section(driver, wait: WebDriverWait, document: Document) -> None:
    if is_bas_document(document):
        tab = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "a[href$='#tabs4']")))
        click_element(driver, tab)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#tabs4 tr")))
        return
    click_text(driver, wait, "Penetapan")


def find_bas_upload_link_and_state(driver, wait: WebDriverWait, document: Document):
    if not document.hearing_order:
        raise ValueError("Urutan sidang BAS belum tersedia.")

    expected_order = str(document.hearing_order)
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#tabs4 tr")))
    matched_row = None
    for row in driver.find_elements(By.CSS_SELECTOR, "#tabs4 tr"):
        cells = row.find_elements(By.CSS_SELECTOR, "td")
        if not cells or (cells[0].text or "").strip() != expected_order:
            continue
        matched_row = row
        break

    if matched_row is None:
        raise RuntimeError(f"Jadwal sidang ke-{expected_order} tidak ditemukan pada tab Jadwal Sidang.")

    links = matched_row.find_elements(
        By.XPATH,
        ".//a[contains(@onclick, '/fileupload/') and contains(@onclick, '/bas/') "
        "and contains(normalize-space(), 'Unggah BAS')]",
    )
    upload_link = links[0] if links else None
    existing_links = matched_row.find_elements(
        By.XPATH,
        ".//a[contains(normalize-space(), 'Unduh Dokumen BAS') "
        "or (contains(@href, '/resources/file/doc/') and contains(@href, '_bas_'))]",
    )
    return upload_link, bool(existing_links)


def login(driver, wait: WebDriverWait, selectors: dict, config: SeleniumConfig) -> None:
    driver.get(config.login_url)
    human_pause(0.8, 1.2)
    type_like_human(find(wait, selectors["login"]["username"]), config.username)
    human_pause(0.5, 1.0)
    type_like_human(find(wait, selectors["login"]["password"]), config.password)
    human_pause(0.5, 1.0)
    submit_or_click(driver, wait, selectors["login"]["submit"])


def open_case_detail(driver, wait: WebDriverWait, selectors: dict, document: Document) -> None:
    main_url = current_sipp_main_url(driver)
    if main_url:
        human_pause(0.8, 1.2)
        driver.get(main_url)
        human_pause(0.8, 1.2)
    click_text(driver, wait, case_register_link_text(document.case_number))
    click(wait, selectors["search"]["detail_search_button"])
    Select(find(wait, selectors["search"]["case_operator_select"])).select_by_value("1")
    case_input = find(wait, selectors["search"]["case_input"])
    case_input.clear()
    human_pause(0.5, 1.0)
    type_like_human(case_input, document.case_number)
    human_pause(0.8, 1.2)
    submit_or_click(driver, wait, selectors["search"]["submit"])
    click(wait, selectors["search"]["open_result"])


def mark_uploaded(document: Document, message: str, response_text: str | None = None, uploaded_dir: Path | None = None):
    document.status = DocumentStatus.UPLOAD_SUCCESS
    document.uploaded_at = datetime.utcnow()
    document.upload_response = response_text or message
    document.error_message = None
    add_log(document, "berhasil", message, response_text=response_text)
    archive_path = archive_uploaded_document(document, uploaded_dir)
    if archive_path:
        add_log(document, "arsip", f"File disimpan ke {archive_path}")


def mark_existing_bas(document: Document, message: str) -> None:
    document.status = DocumentStatus.SKIPPED_EXISTING
    document.uploaded_at = None
    document.upload_response = message
    document.error_message = None
    add_log(document, "dilewati", message)


def add_log(document: Document, status: str, message: str, response_text: str | None = None):
    db.session.add(
        UploadLog(
            document_id=document.id,
            status=status,
            message=message,
            response_text=response_text,
        )
    )
    db.session.commit()


def mark_upload_failed(document: Document, message: str) -> None:
    document.status = DocumentStatus.UPLOAD_FAILED
    document.error_message = message
    add_log(document, "gagal", message)
    db.session.commit()


def log_upload_interrupted(document: Document, message: str) -> None:
    # Tetap siap upload agar dapat diulang, tetapi tampilkan penyebab gangguan.
    document.error_message = message
    add_log(document, "gagal", message)
    db.session.commit()


def browser_session_lost(exc: WebDriverException) -> bool:
    if isinstance(exc, InvalidSessionIdException):
        return True
    message = str(exc).lower()
    return any(marker in message for marker in (
        "invalid session id", "not connected to devtools", "chrome not reachable",
        "disconnected: unable to receive message",
    ))


def upload_document_on_current_case(
    document: Document,
    driver,
    wait: WebDriverWait,
    selectors: dict,
    config: SeleniumConfig,
    force_upload: bool = False,
) -> bool:
    try:
        target_code = upload_target_code(document)
        if not target_code:
            raise ValueError(f"Jenis dokumen belum punya target upload SIPP: {document.document_type or '-'}")

        section_name = "Jadwal Sidang" if is_bas_document(document) else "Penetapan"
        add_log(document, "detail", f"Membuka tab {section_name}")
        open_document_section(driver, wait, document)
        add_log(document, "cek", f"Mengecek tombol upload {target_code}")
        if is_bas_document(document):
            upload_link, already_has_pdf = find_bas_upload_link_and_state(driver, wait, document)
        else:
            upload_link, already_has_pdf = find_upload_link_and_state(driver, wait, target_code)
        if already_has_pdf and not force_upload:
            if is_bas_document(document):
                mark_existing_bas(document, "BAS sudah ada pada baris sidang SIPP; perkara ini dilewati.")
            else:
                mark_uploaded(
                    document,
                    "Dokumen sudah ada di SIPP, upload dilewati supaya tidak dobel.",
                    response_text="Sudah ada tombol/icon PDF di baris dokumen.",
                    uploaded_dir=config.uploaded_dir,
                )
            return True
        if upload_link is None:
            raise RuntimeError(
                "Baris dokumen ditemukan, tetapi tombol Unggah tidak tersedia dan PDF belum terdeteksi."
            )
        if already_has_pdf and force_upload:
            add_log(document, "paksa", "PDF sudah ada di SIPP, tetapi upload tetap dipaksa karena file sebelumnya salah.")

        add_log(document, "form", "Membuka form unggah dan memilih file PDF")
        click_element(driver, upload_link)
        find(wait, selectors["upload"]["file_input"]).send_keys(document.file_path)
        submit_or_click(driver, wait, selectors["upload"]["submit"])
        alert_text = accept_optional_alert(driver)
        if alert_text:
            add_log(document, "konfirmasi", f"Konfirmasi SIPP diterima: {alert_text}")

        response_element = find(wait, selectors["upload"]["response"])
        response_text = response_element.text.strip()
        human_pause(1.0, 1.5)
        add_log(document, "verifikasi", "Mengecek ulang apakah tombol Pdf sudah muncul di SIPP")
        open_document_section(driver, wait, document)
        if is_bas_document(document):
            _, uploaded_pdf_exists = find_bas_upload_link_and_state(driver, wait, document)
        else:
            _, uploaded_pdf_exists = find_upload_link_and_state(driver, wait, target_code)
        if not uploaded_pdf_exists:
            raise RuntimeError("Upload dikirim, tetapi tombol Pdf belum muncul di baris dokumen SIPP.")
        mark_uploaded(document, "Upload berhasil", response_text=response_text, uploaded_dir=config.uploaded_dir)
        return True
    except WebDriverException as exc:
        if browser_session_lost(exc):
            log_upload_interrupted(document, f"Sesi browser terputus; status PDF di SIPP perlu dicek ulang: {exc}")
            return False
        mark_upload_failed(document, str(exc))
        return True
    except Exception as exc:
        mark_upload_failed(document, str(exc))
        return True
    finally:
        db.session.commit()


def upload_document_in_session(
    document: Document,
    driver,
    wait: WebDriverWait,
    selectors: dict,
    config: SeleniumConfig,
) -> None:
    add_log(document, "cari", "Membuka register dan mencari nomor perkara")
    open_case_detail(driver, wait, selectors, document)
    upload_document_on_current_case(document, driver, wait, selectors, config)


def upload_document(document: Document, config: SeleniumConfig) -> None:
    selectors = load_selectors(config.selectors_file)
    driver = build_driver(config)
    wait = WebDriverWait(driver, 30)

    try:
        add_log(document, "mulai", "Membuka halaman login")
        login(driver, wait, selectors, config)
        add_log(document, "login", "Login berhasil")
        upload_document_in_session(document, driver, wait, selectors, config)
    finally:
        if not config.keep_browser_open:
            driver.quit()


def upload_ready_documents(
    limit: int | None,
    config: SeleniumConfig,
    accounts_by_role: dict[str, UploadAccount],
    accounts_by_clerk: dict[int, UploadAccount] | None = None,
    roles: set[str] | None = None,
    document_filter=None,
    progress_callback=None,
    pause_callback=None,
    batch_pause_callback=None,
    batch_pause_every: int = 100,
) -> int:
    query = Document.query.filter_by(status=DocumentStatus.READY_UPLOAD).order_by(Document.updated_at.asc())
    if limit is not None:
        query = query.limit(limit)
    documents = query.all()
    if roles is not None:
        documents = [
            document
            for document in documents
            if upload_role_for_document(document) in roles
        ]
    if document_filter is not None:
        documents = [document for document in documents if document_filter(document)]
    total = len(documents)
    jobs_by_account: dict[int | str, tuple[UploadAccount, list[Document]]] = {}
    documents_without_account: list[tuple[Document, str]] = []
    accounts_by_clerk = accounts_by_clerk or {}
    for document in documents:
        role = upload_role_for_document(document)
        if not role:
            documents_without_account.append((document, f"Jenis dokumen '{document.document_type or '-'}' belum memiliki aturan akun."))
            continue
        if role == ROLE_BAS:
            account = accounts_by_clerk.get(document.assigned_clerk_id or 0)
            missing_message = (
                f"Akun SIPP milik {document.assigned_clerk_name or 'Panitera/Panitera Pengganti'} "
                f"(ID {document.assigned_clerk_id or '-'}) belum disetting. BAS tetap ditahan dan tidak dialihkan ke akun lain."
            )
        else:
            account = accounts_by_role.get(role)
            missing_message = f"Akun upload untuk jenis dokumen '{document.document_type or '-'}' belum disetting."
        if not account:
            documents_without_account.append((document, missing_message))
            continue
        account_key = account.id if account.id is not None else f"{role}:{id(account)}"
        if account_key not in jobs_by_account:
            jobs_by_account[account_key] = (account, [])
        jobs_by_account[account_key][1].append(document)

    processed = 0
    for document, missing_message in documents_without_account:
        processed += 1
        if progress_callback:
            progress_callback(processed, total, document)
        if is_bas_document(document):
            document.status = DocumentStatus.READY_UPLOAD
            document.error_message = missing_message
            add_log(document, "tertunda", missing_message)
        else:
            document.status = DocumentStatus.UPLOAD_FAILED
            document.error_message = missing_message
            add_log(document, "gagal", missing_message)
        db.session.commit()

    for account, account_documents in jobs_by_account.values():
        account_config = build_config_for_account(config, account)
        selectors = load_selectors(account_config.selectors_file)
        driver = None
        try:
            driver = build_driver(account_config)
            wait = WebDriverWait(driver, 30)
            add_log(account_documents[0], "mulai", f"Membuka halaman login untuk akun {account.name} ({account.role})")
            login(driver, wait, selectors, account_config)
            add_log(account_documents[0], "login", "Login berhasil; sesi dipakai untuk dokumen berikutnya")
            case_groups: dict[str, list[Document]] = {}
            for document in account_documents:
                case_groups.setdefault(document.case_number or "", []).append(document)

            for _, case_documents in case_groups.items():
                case_documents.sort(key=upload_order)
                first_document = case_documents[0]
                if pause_callback:
                    pause_callback(processed, total, first_document)
                try:
                    add_log(first_document, "cari", "Membuka register dan mencari nomor perkara")
                    open_case_detail(driver, wait, selectors, first_document)
                except WebDriverException as exc:
                    message = f"Sesi browser Selenium terputus saat membuka perkara {first_document.case_number}: {exc}"
                    for document in case_documents:
                        processed += 1
                        if progress_callback:
                            progress_callback(processed, total, document)
                        log_upload_interrupted(document, message)
                    break

                for document in case_documents:
                    if pause_callback:
                        pause_callback(processed, total, document)
                    processed += 1
                    if progress_callback:
                        progress_callback(processed, total, document)
                    add_log(document, "akun", f"Memakai akun {account.name} ({account.role})")
                    session_ok = upload_document_on_current_case(document, driver, wait, selectors, account_config)
                    if not session_ok:
                        # A submit may already have reached SIPP. Reopen the case
                        # in a fresh browser; the normal PDF check prevents a
                        # duplicate upload when SIPP accepted the first attempt.
                        try:
                            driver.quit()
                        except WebDriverException:
                            pass
                        driver = build_driver(account_config)
                        wait = WebDriverWait(driver, 30)
                        add_log(document, "sesi", "Membuka ulang browser setelah sesi terputus")
                        login(driver, wait, selectors, account_config)
                        open_case_detail(driver, wait, selectors, document)
                        session_ok = upload_document_on_current_case(document, driver, wait, selectors, account_config)
                        if not session_ok:
                            break
                    if batch_pause_every and processed % batch_pause_every == 0 and processed < total:
                        if batch_pause_callback:
                            batch_pause_callback(processed, total, document)
        except WebDriverException as exc:
            message = f"Sesi browser Selenium gagal untuk akun {account.name} ({account.role}): {exc}"
            for document in account_documents:
                if document.status != DocumentStatus.READY_UPLOAD:
                    continue
                processed += 1
                if progress_callback:
                    progress_callback(processed, total, document)
                log_upload_interrupted(document, message)
        finally:
            if driver is not None and not account_config.keep_browser_open:
                try:
                    driver.quit()
                except WebDriverException:
                    pass

    return len(documents)
