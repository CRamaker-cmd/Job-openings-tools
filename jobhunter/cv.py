"""Your CV: upload a file, keep a copy on the data drive, and extract its text (used when you ask the AI agent to
customise a letter). Supports PDF (text-based), DOCX, TXT and Markdown. Nothing here talks to the network."""
from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

MAX_BYTES = 5 * 1024 * 1024
MAX_CHARS = 60_000
ALLOWED = (".pdf", ".docx", ".txt", ".md")
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class CVError(ValueError):
    """A problem the user can fix (wrong file type, scanned PDF, too big...); the message is shown on the page."""


def _clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = re.sub(r"[ \t\xa0]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _pdf(data: bytes) -> str:
    if not data.startswith(b"%PDF-"):
        raise CVError("That file doesn't look like a PDF.")
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise CVError("This PDF is password-protected. Remove the password or paste your CV text below.")
        return "\n\n".join((page.extract_text() or "") for page in reader.pages[:30])
    except CVError:
        raise
    except Exception as e:  # pypdf raises many kinds of errors on damaged files
        raise CVError(f"Could not read this PDF ({type(e).__name__}). Try exporting it again, or paste your CV text below.")


def _docx(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            info = z.getinfo("word/document.xml")
            if info.file_size > 20 * 1024 * 1024:
                raise CVError("This document is unusually large.")
            root = ET.fromstring(z.read("word/document.xml"))
    except CVError:
        raise
    except (KeyError, zipfile.BadZipFile, ET.ParseError):
        raise CVError("That file doesn't look like a Word (.docx) document.")
    paragraphs = []
    for p in root.iter(f"{_W}p"):
        parts = []
        for el in p.iter():
            if el.tag == f"{_W}t" and el.text:
                parts.append(el.text)
            elif el.tag in (f"{_W}tab", f"{_W}br"):
                parts.append("\t" if el.tag == f"{_W}tab" else "\n")
        paragraphs.append("".join(parts))
    return "\n".join(paragraphs)


def extract_text(filename: str, data: bytes) -> str:
    """Plain text of an uploaded CV. Raises CVError with a message the user can act on."""
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED:
        raise CVError(f"Upload a PDF, Word (.docx), .txt or .md file (not '{ext or 'no extension'}').")
    if not data:
        raise CVError("The file is empty.")
    if len(data) > MAX_BYTES:
        raise CVError(f"The file is larger than {MAX_BYTES // (1024 * 1024)} MB.")
    text = {".pdf": _pdf, ".docx": _docx}.get(ext, lambda d: d.decode("utf-8", errors="replace"))(data)
    text = _clean(text)
    if len(text) < 40:
        raise CVError("No readable text found. Scanned or image-only PDFs can't be read: paste your CV text into the box below instead.")
    if len(text) > MAX_CHARS:
        raise CVError(f"The text is longer than {MAX_CHARS:,} characters, which is too long for a CV. Upload a shorter version.")
    return text


def storage_dir(cfg: dict) -> Path:
    return Path(cfg["db_path"]).parent / "uploads"


def save_file(cfg: dict, filename: str, data: bytes) -> str:
    """Keep the original next to the database (replacing an earlier upload). Returns the stored file name."""
    d = storage_dir(cfg)
    d.mkdir(parents=True, exist_ok=True)
    remove_file(cfg)
    name = "cv" + Path(filename).suffix.lower()
    (d / name).write_bytes(data)
    return name


def remove_file(cfg: dict) -> None:
    d = storage_dir(cfg)
    for ext in ALLOWED:
        (d / f"cv{ext}").unlink(missing_ok=True)


def stored_file(cfg: dict) -> Path | None:
    d = storage_dir(cfg)
    return next((d / f"cv{e}" for e in ALLOWED if (d / f"cv{e}").exists()), None)
