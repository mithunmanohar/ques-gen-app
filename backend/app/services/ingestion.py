"""
Turns an uploaded past-year-paper file into plain text that can later be
fed to DeepSeek as source material for generation.

Supported today: PDF (text-based, not scanned images), Markdown, plain text.
A scanned/image-only PDF will yield little or no text — see README's
"Limitations" section. If that turns out to matter for your papers, the
natural next step is to add an OCR fallback in this one function without
touching anything else in the app.
"""
from pathlib import Path

from fastapi import UploadFile
from pypdf import PdfReader

SUPPORTED_EXTENSIONS = {".pdf": "pdf", ".md": "md", ".markdown": "md", ".txt": "txt"}


class UnsupportedFileType(ValueError):
    pass


def file_type_for(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFileType(
            f"Unsupported file type '{ext}'. Supported: {', '.join(SUPPORTED_EXTENSIONS)}"
        )
    return SUPPORTED_EXTENSIONS[ext]


def extract_text(file_path: Path, file_type: str) -> str:
    if file_type == "pdf":
        return _extract_pdf_text(file_path)
    # md / txt are already plain text
    return file_path.read_text(encoding="utf-8", errors="replace")


def _extract_pdf_text(file_path: Path) -> str:
    reader = PdfReader(str(file_path))
    pages_text = []
    for page in reader.pages:
        pages_text.append(page.extract_text() or "")
    return "\n\n".join(pages_text).strip()


async def save_upload(upload: UploadFile, destination_dir: Path, dest_filename: str) -> Path:
    destination_dir.mkdir(parents=True, exist_ok=True)
    dest_path = destination_dir / dest_filename
    contents = await upload.read()
    dest_path.write_bytes(contents)
    return dest_path
