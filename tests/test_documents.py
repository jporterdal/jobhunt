"""Documents: content-addressed store and text extraction (10.1), upload and linking pages (10.2)."""

import hashlib
import re
from io import BytesIO

from sqlalchemy import select

from jobhunt import documents, userdata
from jobhunt.db import documents as documents_table

from .conftest import add_posting, get, post


def make_pdf(text: str) -> bytes:
    """A one-page PDF showing `text`, built by hand so no binary fixture is committed."""
    content = f"BT /F1 18 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


def make_docx(*paragraphs: str) -> bytes:
    import docx

    document = docx.Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


ODT_NAMESPACES = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
    'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
    'xmlns:xlink="http://www.w3.org/1999/xlink" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/"'
)


def make_odt(body: str) -> bytes:
    """An ODT file whose office:text holds `body` (ODF XML with the text, table and draw prefixes)."""
    from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

    content = (
        f'<?xml version="1.0" encoding="UTF-8"?><office:document-content {ODT_NAMESPACES} office:version="1.3">'
        f"<office:body><office:text>{body}</office:text></office:body></office:document-content>"
    )
    manifest = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.3">'
        '<manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.text"/>'
        '<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>'
        "</manifest:manifest>"
    )
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("mimetype", "application/vnd.oasis.opendocument.text", compress_type=ZIP_STORED)
        archive.writestr("content.xml", content, compress_type=ZIP_DEFLATED)
        archive.writestr("META-INF/manifest.xml", manifest, compress_type=ZIP_DEFLATED)
    return buffer.getvalue()


def odt_paragraphs(*lines: str) -> str:
    """Plain paragraphs, with a tab character in a line written as a text:tab stop."""
    from xml.sax.saxutils import escape

    return "".join(f"<text:p>{escape(line).replace(chr(9), '<text:tab/>')}</text:p>" for line in lines)


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


# --- Store and extraction (10.1) ---


def test_pdf_text_extracted(tmp_path):
    stored = documents.store_upload(tmp_path, make_pdf("Jane Doe CV"), "cv-2026-10.pdf", "application/pdf")
    assert stored.text_status == "extracted" and "Jane Doe CV" in stored.text_content
    assert stored.media_type == "application/pdf" and stored.original_filename == "cv-2026-10.pdf"


def test_docx_text_extracted(tmp_path):
    stored = documents.store_upload(tmp_path, make_docx("Cover letter", "Dear team,"), "letter.docx")
    assert stored.text_status == "extracted"
    assert stored.text_content == "Cover letter\nDear team,"


def test_text_and_markdown(tmp_path):
    assert documents.store_upload(tmp_path, "café\n".encode(), "notes.md").text_content == "café"
    assert documents.store_upload(tmp_path, b"bad \xff byte", "x.txt").text_content == "bad \ufffd byte"


def test_identical_bytes_stored_once(tmp_path):
    data = make_pdf("Same")
    first = documents.store_upload(tmp_path, data, "a.pdf")
    second = documents.store_upload(tmp_path, data, "b.pdf")
    assert first.sha256 == second.sha256 == hashlib.sha256(data).hexdigest()
    files = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert files == [tmp_path / first.sha256[:2] / first.sha256]


def test_read_back_is_byte_identical(tmp_path):
    data = make_docx("x")
    stored = documents.store_upload(tmp_path, data, "x.docx")
    assert documents.read_bytes(tmp_path, stored.sha256) == data
    assert documents.read_bytes(tmp_path, "0" * 64) is None


def test_png_is_unsupported(tmp_path):
    stored = documents.store_upload(tmp_path, PNG, "photo.png", "image/png")
    assert (stored.text_content, stored.text_status, stored.media_type) == (None, "unsupported", "image/png")
    assert documents.read_bytes(tmp_path, stored.sha256) == PNG


def test_corrupt_pdf_is_failed(tmp_path):
    stored = documents.store_upload(tmp_path, b"%PDF-1.4 this is not really a pdf", "broken.pdf")
    assert stored.text_content is None and stored.text_status.startswith("failed: ")
    assert documents.read_bytes(tmp_path, stored.sha256) is not None


CV_ODT_BODY = (
    # The contact block as a table, with a photo in the first cell.
    "<table:table><table:table-row>"
    '<table:table-cell><text:p><draw:frame><draw:image xlink:href="Pictures/photo.png"/></draw:frame></text:p>'
    "</table:table-cell>"
    "<table:table-cell><text:p>Jane Doe</text:p><text:p>jane@example.com</text:p></table:table-cell>"
    "</table:table-row><table:table-row>"
    "<table:table-cell><text:p>+1 902 555 0100</text:p></table:table-cell>"
    "</table:table-row></table:table>"
    "<text:p>EDUCATION</text:p>"
    "<text:list><text:list-item><text:p>MSc Statistics, Example Institute<text:tab/>2009</text:p></text:list-item>"
    '<text:list-item><text:p>PhD<text:s text:c="3"/>Computer Science<text:line-break/>Thesis: Search</text:p>'
    "</text:list-item></text:list>"
)


def test_odt_with_tab_aligned_dates(tmp_path):
    stored = documents.store_upload(tmp_path, make_odt(CV_ODT_BODY), "cv.odt")
    assert stored.text_status == "extracted"
    assert stored.text_content.split("\n") == [
        "Jane Doe",
        "jane@example.com",
        "+1 902 555 0100",
        "EDUCATION",
        "MSc Statistics, Example Institute\t2009",
        "PhD   Computer Science",
        "Thesis: Search",
    ]
    assert stored.media_type == "application/vnd.oasis.opendocument.text"


def test_odt_tracked_changes_and_annotations_give_no_text(tmp_path):
    body = (
        "<text:tracked-changes><text:changed-region text:id=\"c1\"><text:deletion>"
        "<text:p>Deleted draft line</text:p></text:deletion></text:changed-region></text:tracked-changes>"
        "<text:p>Kept <text:change text:change-id=\"c1\"/>line"
        "<office:annotation><dc:creator>Reviewer</dc:creator><text:p>Rephrase this</text:p></office:annotation>"
        " ends here</text:p>"
    )
    text, status = documents.extract_text(make_odt(body), "cv.odt")
    assert (text, status) == ("Kept line ends here", "extracted")


def test_odt_text_box_read_in_place(tmp_path):
    body = (
        "<text:p>Before</text:p>"
        "<text:p>Lead <draw:frame><draw:text-box><text:p>Boxed note</text:p></draw:text-box></draw:frame>tail</text:p>"
        "<text:h>AFTER</text:h>"
    )
    text, _ = documents.extract_text(make_odt(body), "cv.odt")
    assert text.split("\n") == ["Before", "Lead", "Boxed note", "tail", "AFTER"]


def test_broken_odt_is_failed_but_stored(client, engine, tmp_path):
    response = upload(client, b"PK\x03\x04 not really a zip", "cv.odt", kind="other")
    assert response.status_code == 303
    [doc] = document_rows(engine)
    assert doc.text_content is None and doc.text_status.startswith("failed: BadZipFile")


def test_windows_path_reduced_to_name(tmp_path):
    assert documents.store_upload(tmp_path, b"x", "C:\\Users\\me\\cv.txt").original_filename == "cv.txt"


# --- Upload and linking pages (10.2) ---


def upload(client, data, filename, kind="cv", label="", **extra):
    return post(
        client,
        "/documents",
        {"file": (BytesIO(data), filename), "kind": kind, "label": label, **extra},
        content_type="multipart/form-data",
    )


def document_rows(engine):
    with engine.connect() as conn:
        return conn.execute(select(documents_table).order_by(documents_table.c.id)).all()


def test_upload_a_cv(client, engine, tmp_path):
    data = make_pdf("Senior data engineer")
    response = upload(client, data, "cv-2026-10.pdf", label="CV v3")
    assert response.status_code == 303
    doc = document_rows(engine)[0]
    listing = get(client, "/documents").get_data(as_text=True)
    assert "CV v3" in listing and "cv-2026-10.pdf" in listing and f"{len(data)} bytes" in listing
    page = get(client, f"/documents/{doc.id}").get_data(as_text=True)
    assert "Senior data engineer" in page
    download = get(client, f"/documents/{doc.id}/download")
    assert download.data == data
    assert 'filename=cv-2026-10.pdf' in download.headers["Content-Disposition"]


def test_same_file_twice(client, engine, tmp_path):
    data = make_pdf("Same")
    upload(client, data, "cv.pdf", label="CV v3")
    upload(client, data, "cv-copy.pdf", label="CV v3 (sent to Example Bank)")
    rows = document_rows(engine)
    assert len(rows) == 2 and rows[0].sha256 == rows[1].sha256
    assert len([p for p in (tmp_path / "documents").rglob("*") if p.is_file()]) == 1


def test_unsupported_type(client, engine):
    upload(client, PNG, "photo.png", kind="other", label="Headshot")
    doc = document_rows(engine)[0]
    assert doc.text_status == "unsupported" and doc.text_content is None
    page = get(client, f"/documents/{doc.id}").get_data(as_text=True)
    assert "No extracted text" in page
    assert get(client, f"/documents/{doc.id}/download").data == PNG


def test_file_missing_state(client, engine, tmp_path):
    upload(client, b"plain", "a.txt", kind="other")
    doc = document_rows(engine)[0]
    documents.path_for(tmp_path / "documents", doc.sha256).unlink()
    page = get(client, f"/documents/{doc.id}").get_data(as_text=True)
    assert "File missing" in page
    assert get(client, f"/documents/{doc.id}/download").status_code == 404


def test_bad_kind_or_no_file(client, engine, tmp_path):
    assert upload(client, b"x", "a.txt", kind="resume").status_code == 400
    assert post(client, "/documents", {"kind": "cv"}).status_code == 400
    assert document_rows(engine) == []
    assert not (tmp_path / "documents").exists()


def test_upload_limit(web):
    app, client = web
    app.config["MAX_CONTENT_LENGTH"] = 1024
    assert upload(client, b"x" * 4096, "big.txt").status_code == 413


def test_one_cv_two_applications(client, engine):
    with engine.begin() as conn:
        advisory = userdata.create_application(conn, "AI Scientist", "Example Advisory")
        bank_app = userdata.create_application(conn, "Analytics Manager", "Example Bank")
    upload(client, make_pdf("CV"), "cv.pdf", label="CV v3", app_id=str(advisory))
    doc = document_rows(engine)[0]
    post(client, f"/applications/{bank_app}/documents", {"document_id": str(doc.id)})
    for app_id in (advisory, bank_app):
        page = get(client, f"/applications/{app_id}").get_data(as_text=True)
        assert re.search(rf'<a href="/documents/{doc.id}">CV v3</a>', page)
    doc_page = get(client, f"/documents/{doc.id}").get_data(as_text=True)
    assert "AI Scientist" in doc_page and "Analytics Manager" in doc_page

    post(client, f"/applications/{bank_app}/documents/{doc.id}/unlink")
    assert "Analytics Manager" not in get(client, f"/documents/{doc.id}").get_data(as_text=True)


def test_documents_survive_reimport(engine, tmp_path):
    # Re-importing a posting leaves its application's documents alone (application-tracking spec).
    job = add_posting(engine)
    with engine.begin() as conn:
        app_id = userdata.start_application(conn, job)
        doc_id = userdata.add_document(conn, documents.store_upload(tmp_path, b"cv", "cv.txt"), "CV", "cv")
        userdata.link_document(conn, app_id, doc_id)
    before = document_rows(engine)
    add_posting(engine, tag="v2", description_text="Changed.")
    assert document_rows(engine) == before
