"""A laid-out CV as an OpenDocument Text file, with the standard library only (design D7).

The text goes into content.xml through ElementTree, so the library escapes it; every paragraph names a style from
styles.py, which holds every property. Zip entries carry a fixed time, so the same CV gives the same bytes.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from io import BytesIO

from . import styles
from .layout import CONTACT_SEPARATOR, SOURCE_SEPARATOR, SUBTITLE_SEPARATOR
from .model import Bullet, Cv, Entry

MIMETYPE = "application/vnd.oasis.opendocument.text"
ODF_VERSION = "1.3"
FIXED_TIME = (1980, 1, 1, 0, 0, 0)

NS = {
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    "meta": "urn:oasis:names:tc:opendocument:xmlns:meta:1.0",
    "manifest": "urn:oasis:names:tc:opendocument:xmlns:manifest:1.0",
}
for _prefix, _uri in NS.items():
    ET.register_namespace(_prefix, _uri)

_SPACE_RUN = re.compile(r"( {2,}|\t|\n)")


def _q(prefix: str, name: str) -> str:
    return f"{{{NS[prefix]}}}{name}"


def _add_text(parent: ET.Element, text: str) -> None:
    """Append text to an element, as ODF wants it: a tab as text:tab, a newline as text:line-break, and a run of
    spaces as one space and text:s for the rest."""
    last: ET.Element | None = None

    def put(chunk: str) -> None:
        if last is None:
            parent.text = (parent.text or "") + chunk
        else:
            last.tail = (last.tail or "") + chunk

    for part in _SPACE_RUN.split(text):
        if not part:
            continue
        if part == "\t":
            last = ET.SubElement(parent, _q("text", "tab"))
        elif part == "\n":
            last = ET.SubElement(parent, _q("text", "line-break"))
        elif part.startswith("  "):
            put(" ")
            last = ET.SubElement(parent, _q("text", "s"), {_q("text", "c"): str(len(part) - 1)})
        else:
            put(part)


def _p(parent: ET.Element, style: str, text: str, tag: str = "p") -> ET.Element:
    element = ET.SubElement(parent, _q("text", tag), {_q("text", "style-name"): style})
    _add_text(element, text)
    return element


def _entry(body: ET.Element, e: Entry, depth: int) -> None:
    heading_style = styles.ENTRY if depth == 0 else styles.SUB_ENTRY
    line_style = styles.LINE if depth == 0 else styles.SUB_LINE
    heading = ET.SubElement(body, _q("text", "p"), {_q("text", "style-name"): heading_style})
    title = ET.SubElement(heading, _q("text", "span"), {_q("text", "style-name"): styles.ENTRY_TITLE})
    _add_text(title, e.title)
    rest = (SUBTITLE_SEPARATOR + e.subtitle if e.subtitle else "") + ("\t" + e.dates if e.dates else "")
    if rest:
        # Text after the span is the span's tail; _add_text on the heading would put it before the span.
        holder = ET.Element("holder")
        _add_text(holder, rest)
        title.tail = holder.text
        heading.extend(list(holder))
    for line in e.lines:
        _p(body, line_style, line)
    if e.sources:
        _p(body, styles.SOURCE if depth == 0 else styles.SUB_LINE, SOURCE_SEPARATOR.join(e.sources))
    if e.context_note:
        _p(body, styles.NOTE if depth == 0 else styles.SUB_LINE, e.context_note)
    for child in e.children:
        _entry(body, child, depth + 1)


def content_xml(cv: Cv) -> bytes:
    root = ET.Element(_q("office", "document-content"), {_q("office", "version"): ODF_VERSION})
    body = ET.SubElement(ET.SubElement(root, _q("office", "body")), _q("office", "text"))
    h = cv.header
    for style, line in ((styles.NAME, h.name), (styles.HEADLINE, h.headline), (styles.PRODUCED, h.produced)):
        if line:
            _p(body, style, line)
    if h.contacts:
        _p(body, styles.CONTACT, CONTACT_SEPARATOR.join(h.contacts))
    for section in cv.sections:
        heading = _p(body, styles.HEADING, section.heading, tag="h")
        heading.set(_q("text", "outline-level"), "1")
        bullets = None
        for block in section.blocks:
            if isinstance(block, Bullet):
                if bullets is None:
                    bullets = ET.SubElement(body, _q("text", "list"), {_q("text", "style-name"): styles.BULLETS})
                _p(ET.SubElement(bullets, _q("text", "list-item")), styles.BULLET, block.text)
                continue
            bullets = None
            if isinstance(block, Entry):
                _entry(body, block, 0)
            else:
                _p(body, styles.PARAGRAPH, block.text)
    return ET.tostring(root, encoding="UTF-8", xml_declaration=True)


def _manifest() -> bytes:
    root = ET.Element(_q("manifest", "manifest"), {_q("manifest", "version"): ODF_VERSION})
    entries = (("/", MIMETYPE), ("content.xml", "text/xml"), ("styles.xml", "text/xml"), ("meta.xml", "text/xml"))
    for path, media_type in entries:
        attrs = {_q("manifest", "full-path"): path, _q("manifest", "media-type"): media_type}
        if path == "/":
            attrs[_q("manifest", "version")] = ODF_VERSION
        ET.SubElement(root, _q("manifest", "file-entry"), attrs)
    return ET.tostring(root, encoding="UTF-8", xml_declaration=True)


def _meta() -> bytes:
    root = ET.Element(_q("office", "document-meta"), {_q("office", "version"): ODF_VERSION})
    ET.SubElement(ET.SubElement(root, _q("office", "meta")), _q("meta", "generator")).text = "jobhunt"
    return ET.tostring(root, encoding="UTF-8", xml_declaration=True)


def write(cv: Cv) -> bytes:
    """The ODT package: `mimetype` first and stored uncompressed, then the manifest, styles, content and meta."""
    out = BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        parts = (
            ("mimetype", MIMETYPE.encode("ascii"), zipfile.ZIP_STORED),
            ("META-INF/manifest.xml", _manifest(), zipfile.ZIP_DEFLATED),
            ("styles.xml", styles.STYLES_XML.encode("utf-8"), zipfile.ZIP_DEFLATED),
            ("content.xml", content_xml(cv), zipfile.ZIP_DEFLATED),
            ("meta.xml", _meta(), zipfile.ZIP_DEFLATED),
        )
        for name, data, compression in parts:
            info = zipfile.ZipInfo(name, date_time=FIXED_TIME)
            info.compress_type = compression
            archive.writestr(info, data)
    return out.getvalue()
