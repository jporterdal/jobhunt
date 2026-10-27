"""Uploaded documents: a content-addressed file store plus text extraction (no Flask, no database).

Files live at <documents dir>/<sha256[:2]>/<sha256>. Identical uploads share one file, and a file is
written under a temporary name and renamed into place, so a partial write never has a real hash name.
Back up this folder together with the database.
"""

from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

DEFAULT_DOCUMENTS_DIR = "data/documents"
TEXT_SUFFIXES = (".txt", ".md")


@dataclass(frozen=True)
class StoredFile:
    sha256: str
    size_bytes: int
    original_filename: str
    media_type: str
    text_content: str | None
    text_status: str  # 'extracted', 'unsupported' or 'failed: ...'


def path_for(documents_dir: Path, sha256: str) -> Path:
    return Path(documents_dir) / sha256[:2] / sha256


def store_bytes(documents_dir: Path, data: bytes) -> str:
    """Store the bytes (once) and return their SHA-256."""
    sha256 = hashlib.sha256(data).hexdigest()
    target = path_for(documents_dir, sha256)
    if target.exists():
        return sha256
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".upload-")
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return sha256


def read_bytes(documents_dir: Path, sha256: str) -> bytes | None:
    """The stored bytes, or None when the file is missing (for example, not restored from a backup)."""
    path = path_for(documents_dir, sha256)
    return path.read_bytes() if path.is_file() else None


def media_type(filename: str, reported: str | None = None) -> str:
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or reported or "application/octet-stream"


_TEXT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
_DRAW = "{urn:oasis:names:tc:opendocument:xmlns:drawing:1.0}"
_OFFICE = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"
_PARAGRAPHS = (_TEXT + "p", _TEXT + "h")
# Never text: tracked-change records, comments, footnote bodies and images.
_SKIPPED = (
    _TEXT + "tracked-changes",
    _OFFICE + "annotation",
    _OFFICE + "annotation-end",
    _TEXT + "note",
    _DRAW + "image",
)
_SPACES = re.compile(r"[ \t\r\n]+")


def odt_text(data: bytes) -> str:
    """The text of an ODT file's content.xml: one line per paragraph, heading, list item and table-cell
    paragraph, in document order. Tab stops stay tabs, text:s becomes spaces, line breaks become newlines,
    and a text box inside a frame is read where it stands. Headers and footers (styles.xml) are not read."""
    with zipfile.ZipFile(BytesIO(data)) as archive:
        root = ET.fromstring(archive.read("content.xml"))
    body = root.find(f"{_OFFICE}body")
    lines: list[str] = []

    def emit(parts: list[str]) -> None:
        for line in "".join(parts).split("\n"):
            if line.strip():
                lines.append(line.strip(" "))
        parts.clear()

    def inline(element, parts: list[str]) -> None:
        """Character content of a paragraph; a text box inside it flushes the line and adds its own."""
        if element.text:
            parts.append(_SPACES.sub(" ", element.text))
        for child in element:
            if child.tag in _SKIPPED:
                pass
            elif child.tag == _TEXT + "tab":
                parts.append("\t")
            elif child.tag == _TEXT + "s":
                parts.append(" " * int(child.get(_TEXT + "c", "1")))
            elif child.tag == _TEXT + "line-break":
                parts.append("\n")
            elif child.tag == _DRAW + "frame":
                boxes = child.findall(f"{_DRAW}text-box")
                if boxes:
                    emit(parts)
                    for box in boxes:
                        block(box)
            else:
                inline(child, parts)
            if child.tail:
                parts.append(_SPACES.sub(" ", child.tail))

    def block(element) -> None:
        for child in element:
            if child.tag in _SKIPPED:
                continue
            if child.tag in _PARAGRAPHS:
                parts: list[str] = []
                inline(child, parts)
                emit(parts)
            elif child.tag == _DRAW + "frame":
                for box in child.findall(f"{_DRAW}text-box"):
                    block(box)
            else:  # lists and list items, tables, rows and cells, sections: their paragraphs in order
                block(child)

    if body is not None:
        block(body)
    return "\n".join(lines)


def extract_text(data: bytes, filename: str) -> tuple[str | None, str]:
    """(text, status) for PDF, DOCX, ODT, TXT and MD files; other types are 'unsupported'."""
    suffix = Path(filename).suffix.lower()
    try:
        if suffix == ".pdf":
            from pypdf import PdfReader

            reader = PdfReader(BytesIO(data), strict=True)
            text = "\n\n".join((page.extract_text() or "").strip() for page in reader.pages)
        elif suffix == ".docx":
            import docx

            document = docx.Document(BytesIO(data))
            text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        elif suffix == ".odt":
            text = odt_text(data)
        elif suffix in TEXT_SUFFIXES:
            text = data.decode("utf-8", errors="replace")
        else:
            return None, "unsupported"
    except Exception as error:  # a document we can't read must not block the upload
        return None, f"failed: {type(error).__name__}: {error}"[:500]
    return text.strip(), "extracted"


def store_upload(documents_dir: Path, data: bytes, filename: str, reported_type: str | None = None) -> StoredFile:
    # Keep only the base name; some browsers send a full Windows path.
    filename = (filename or "").replace("\\", "/").rsplit("/", 1)[-1] or "upload"
    text, status = extract_text(data, filename)
    return StoredFile(
        sha256=store_bytes(documents_dir, data),
        size_bytes=len(data),
        original_filename=filename,
        media_type=media_type(filename, reported_type),
        text_content=text,
        text_status=status,
    )
