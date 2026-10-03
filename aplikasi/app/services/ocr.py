from pathlib import Path
import os
import shutil

import pdfplumber
import pytesseract
from pdf2image import convert_from_path


def resolve_poppler_path() -> str | None:
    configured_path = os.getenv("POPPLER_PATH")
    if configured_path:
        return configured_path

    pdfinfo_path = shutil.which("pdfinfo")
    if pdfinfo_path:
        return str(Path(pdfinfo_path).parent)

    for directory in (Path("/usr/bin"), Path("/usr/local/bin")):
        if (directory / "pdfinfo").is_file() and (directory / "pdftoppm").is_file():
            return str(directory)
    return None


def extract_text_with_pdfplumber(pdf_path: Path, max_pages: int | None = None) -> str:
    chunks: list[str] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        pages = pdf.pages[:max_pages] if max_pages else pdf.pages
        for page in pages:
            page_text = page.extract_text() or ""
            if page_text.strip():
                chunks.append(page_text)
    return "\n\n".join(chunks).strip()


def extract_text_with_ocr(pdf_path: Path, lang: str, dpi: int, max_pages: int) -> str:
    chunks: list[str] = []
    images = convert_from_path(
        str(pdf_path),
        dpi=dpi,
        first_page=1,
        last_page=max_pages,
        thread_count=1,
        poppler_path=resolve_poppler_path(),
    )
    for image in images:
        chunks.append(pytesseract.image_to_string(image, lang=lang))
        image.close()
    return "\n\n".join(chunks).strip()


def extract_text(pdf_path: Path, lang: str = "ind", dpi: int = 200, max_ocr_pages: int = 3) -> tuple[str, str]:
    text = extract_text_with_pdfplumber(pdf_path)
    if len(text) >= 80:
        return text, "pdfplumber"

    ocr_text = extract_text_with_ocr(pdf_path, lang=lang, dpi=dpi, max_pages=max_ocr_pages)
    return ocr_text, "tesseract"


def create_first_page_preview(pdf_path: Path, output_dir: Path, document_id: int, dpi: int = 120) -> Path | None:
    output_dir.mkdir(parents=True, exist_ok=True)
    images = convert_from_path(
        str(pdf_path),
        dpi=dpi,
        first_page=1,
        last_page=1,
        thread_count=1,
        poppler_path=resolve_poppler_path(),
    )
    if not images:
        return None

    preview_path = output_dir / f"document_{document_id}.jpg"
    image = images[0]
    image.thumbnail((900, 1200))
    image.save(preview_path, "JPEG", quality=82, optimize=True)
    image.close()
    return preview_path
