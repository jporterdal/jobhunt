"""The CV content model, its layout (headings, dates, terms, nesting) and the ODT export, read back with
documents.odt_text."""

import xml.etree.ElementTree as ET
import zipfile
from io import BytesIO

import pytest

from jobhunt.cvdoc import layout, odt, styles
from jobhunt.cvdoc.model import Bullet, Cv, Entry, Header, Paragraph, content_from_json, content_to_json
from jobhunt.documents import odt_text

STYLE_NS = "{urn:oasis:names:tc:opendocument:xmlns:style:1.0}"
TEXT_NS = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"


def record(title, kind="project", organisation=None, start=None, end=None, ongoing=False, lines=(), sources=(),
           context=None, children=(), record_id=1, location=None):
    return {
        "id": record_id, "kind": kind, "title": title, "organisation": organisation, "location": location,
        "start_date": start, "end_date": end, "ongoing": ongoing, "lines": list(lines), "sources": list(sources),
        "context": context, "children": list(children),
    }


def term(start, end, ongoing=False):
    return {"start_date": start, "end_date": end, "ongoing": ongoing}


def course_group(title, organisation, terms, record_ids=(1,)):
    return {
        "kind": "course", "title": title, "organisation": organisation, "location": None, "terms": terms,
        "record_ids": list(record_ids), "lines": [], "sources": [], "context": None, "children": [],
    }


def item(section, payload, source_kind="record", source_id=1):
    return {"section": section, "source_kind": source_kind, "source_id": source_id, "payload": payload}


def detail(kind, text, label=None):
    return item("header" if kind in layout.HEADER_KINDS else kind, {"kind": kind, "label": label, "text": text},
                "detail")


def content(*items, produced="2026-10-16", left_out=()):
    return {"produced": produced, "left_out": list(left_out), "items": list(items)}


# --- Content model (3.1) ---


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "contact", "label": "Email", "text": "someone@example.com"},
        {"text": "Built évolution strategies in Python & C++ <fast>"},
        record(
            "PhD",
            "degree",
            "Example University",
            end="2022",
            lines=["Thesis line"],
            children=[record("Thesis", "publication", record_id=2, sources=["https://doi.org/10.1/x"])],
        ),
        course_group(
            "COMP 1000", "Example Polytechnic", [term("2024-01", "2024-04"), term("2026-09", "2026-12")], (16, 19)
        ),
    ],
)
def test_every_payload_kind_round_trips(payload):
    assert content_from_json(content_to_json(payload)) == payload


def test_unknown_content_version():
    with pytest.raises(ValueError):
        content_from_json("{}", version=2)


# --- Dates and terms (3.2) ---


def test_year_and_month_dates():
    assert layout.date_range("2022", None) == "2022"
    assert layout.date_range("2022-09", None) == "Sep 2022"
    assert layout.date_range("2016", "2026") == "2016 – 2026"
    assert layout.date_range("2022", "2022") == "2022"


def test_ongoing_record():
    assert layout.date_range("2024-03", None, ongoing=True) == "Mar 2024 – present"


def test_range_with_only_an_end():
    assert layout.date_range(None, "2012") == "2012"
    assert layout.date_range(None, None) is None


def test_terms():
    assert layout.term_name("2024-01", "2024-04") == "Winter 2024"
    assert layout.term_name("2024-05", "2024-08") == "Summer 2024"
    assert layout.term_name("2026-09", "2026-12") == "Fall 2026"


def test_term_that_doesnt_fit_a_window():
    assert layout.term_name("2024-03", "2024-06") is None  # spans Winter and Summer
    assert layout.term_name("2024", "2024") is None  # no months
    assert layout.term_name("2024-09", "2025-04") is None  # two years
    assert layout.terms_line([term("2024-03", "2024-06"), term("2023-01", "2023-04")]) == (
        "Winter 2023, Mar 2024 – Jun 2024"
    )


def test_produced_month():
    assert layout.produced_month("2026-10-16") == "October 2026"


# --- Building a CV (3.3) ---


POLY_COURSE = "COMP 1000 Introduction to Programming"


def test_condensed_course():
    terms = [
        term("2026-09", "2026-12"),
        term("2026-01", "2026-04"),
        term("2024-01", "2024-04"),
        term("2025-01", "2025-04"),
    ]
    cv = layout.build(content(item("course", course_group(POLY_COURSE, "Example Polytechnic", terms),
                                   "course_group", None)))
    [section] = cv.sections
    [entry] = section.blocks
    assert (section.heading, entry.title, entry.subtitle, entry.dates) == (
        "Courses Taught", POLY_COURSE, "Example Polytechnic", "2024 – 2026")
    assert entry.lines == ("Winter 2024, Winter 2025, Winter 2026, Fall 2026",)


def test_produced_month_and_labelled_contacts():
    cv = layout.build(content(
        detail("name", "Ada Lovelace", label="Name"),
        detail("headline", "Analyst"),
        detail("contact", "Example City, EX"),
        detail("contact", "ada@example.com", label="Email"),
    ))
    assert cv.header == Header(
        "Ada Lovelace", "Analyst", "October 2026", ("Example City, EX", "Email: ada@example.com")
    )
    assert cv.sections == ()


def test_sections_in_order_and_empty_section_left_out():
    cv = layout.build(content(
        item("degree", record("PhD", "degree", end="2022")),
        item("highlights", {"text": "Python, every day"}, "highlight"),
        detail("goal", "To build things."),
        item("role", record("Professor", "role", start="2016", end="2026")),
    ))
    assert [s.key for s in cv.sections] == ["goal", "highlights", "role", "degree"]
    assert "Projects" not in [s.heading for s in cv.sections]
    assert cv.sections[0].blocks == (Paragraph("To build things."),)
    assert cv.sections[1].blocks == (Bullet("Python, every day"),)


def test_record_lines_and_sources():
    cv = layout.build(content(item("project", record(
        "tidyplots", organisation="GitHub", location="Example City", start="2023", ongoing=True, lines=["One", "Two"],
        sources=["https://github.com/x/tidyplots", "https://tidyplots.example"]))))
    [entry] = cv.sections[0].blocks
    assert entry == Entry("tidyplots", "GitHub, Example City", "2023 – present", ("One", "Two"),
                          ("https://github.com/x/tidyplots", "https://tidyplots.example"), None, ())


def test_thesis_under_its_degree():
    thesis = record("Evolution strategies for X", "publication", record_id=7)
    cv = layout.build(content(item("degree", record("PhD Computer Science", "degree", "Example University",
                                                    end="2022", lines=["Supervisor: Y"], children=[thesis]))))
    [section] = cv.sections
    assert section.key == "degree"
    [phd] = section.blocks
    assert [c.title for c in phd.children] == ["Evolution strategies for X"]
    assert layout.text(cv)[-3:] == ["PhD Computer Science — Example University\t2022", "Supervisor: Y",
                                    "Evolution strategies for X"]


def test_context_not_chosen():
    tidyplots = record("tidyplots", context={"title": "EXCONF 2024 paper", "organisation": "EXCONF"})
    [entry] = layout.build(content(item("project", tidyplots))).sections[0].blocks
    assert entry.context_note == "Part of: EXCONF 2024 paper"


def test_selected_publications_when_some_were_left_out():
    paper = item("publication", record("A paper", "publication"))
    assert layout.build(content(paper)).sections[0].heading == "Publications"
    assert layout.build(content(paper, left_out=["publication"])).sections[0].heading == "Selected Publications"


# --- Styles (4.1) ---


def _style_names(xml: bytes | str) -> set[str]:
    root = ET.fromstring(xml)
    return {e.get(STYLE_NS + "name") for e in root.iter() if e.get(STYLE_NS + "name")}


def test_styles_define_every_name():
    names = _style_names(styles.STYLES_XML)
    assert {"CvName", "CvHeadline", "CvContact", "CvHeading", "CvEntry", "CvLine", "CvNote", "CvSource",
            "CvBullets"} <= names
    assert set(styles.PARAGRAPH_STYLES + styles.TEXT_STYLES + styles.LIST_STYLES) <= names
    entry = next(
        e for e in ET.fromstring(styles.STYLES_XML).iter(STYLE_NS + "style") if e.get(STYLE_NS + "name") == "CvEntry"
    )
    [stop] = entry.iter(STYLE_NS + "tab-stop")
    assert stop.get(STYLE_NS + "type") == "right"


# --- ODT export (4.2) ---


def sample_cv() -> Cv:
    return layout.build(content(
        detail("name", "Ada <Lovelace> & Co", label="Name"),
        detail("headline", 'The "Analyst"'),
        detail("contact", "ada@example.com", label="Email"),
        detail("goal", "Seeking work  with   spaces."),
        item("highlights", {"text": "Python & C++ <fast>"}, "highlight"),
        item("highlights", {"text": "Second"}, "highlight"),
        item("role", record("Professor", "role", "Example University", start="2016", end="2026", lines=["Taught"],
                            children=[record("Child course", "course", start="2017")])),
        item("project", record("tidyplots", sources=["https://github.com/x/tidyplots"],
                               context={"title": "EXCONF paper", "organisation": None})),
        left_out=["publication"],
    ))


def test_export_reads_back_in_order():
    cv = sample_cv()
    data = odt.write(cv)
    read = odt_text(data).split("\n")
    assert read == layout.text(cv)
    assert "Seeking work  with   spaces." in read  # runs of spaces as text:s
    assert "Ada <Lovelace> & Co" in read and 'The "Analyst"' in read and "Python & C++ <fast>" in read
    assert "Professor — Example University\t2016 – 2026" in read


def test_spaces_survive_as_text_s():
    data = odt.write(sample_cv())
    with zipfile.ZipFile(BytesIO(data)) as archive:
        root = ET.fromstring(archive.read("content.xml"))
    assert any(True for _ in root.iter(TEXT_NS + "s"))
    assert any(True for _ in root.iter(TEXT_NS + "list"))  # highlights are a real list
    assert any(True for _ in root.iter(TEXT_NS + "h"))


def test_package_layout():
    with zipfile.ZipFile(BytesIO(odt.write(sample_cv()))) as archive:
        first = archive.infolist()[0]
        assert (first.filename, first.compress_type) == ("mimetype", zipfile.ZIP_STORED)
        assert archive.read("mimetype") == b"application/vnd.oasis.opendocument.text"
        assert {"META-INF/manifest.xml", "styles.xml", "content.xml", "meta.xml"} <= set(archive.namelist())
        manifest = archive.read("META-INF/manifest.xml").decode()
        assert "content.xml" in manifest and "styles.xml" in manifest


def test_every_style_used_is_defined():
    with zipfile.ZipFile(BytesIO(odt.write(sample_cv()))) as archive:
        content_root = ET.fromstring(archive.read("content.xml"))
        defined = _style_names(archive.read("styles.xml"))
    used = {e.get(TEXT_NS + "style-name") for e in content_root.iter() if e.get(TEXT_NS + "style-name")}
    assert used and used <= defined


def test_same_cv_same_bytes():
    assert odt.write(sample_cv()) == odt.write(sample_cv())
