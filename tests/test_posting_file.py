import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from jobhunt.parsers import CaptureFile, ParsedPosting, Rejected
from jobhunt.parsers.posting_file import PARSER

POSTINGS = Path(__file__).parent / "fixtures" / "postings"
MTIME = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)

COMPLETE = {
    "format": "jobhunt-posting",
    "version": 1,
    "source": "jobs.example.com",
    "external_id": "A-1042",
    "url": "https://jobs.example.com/view/A-1042",
    "title": "Data Engineer",
    "company": "Acme",
    "location": "Example City, EX",
    "workplace_type": "Remote",
    "employment_type": "Full-time",
    "posted_on": "2026-09-30",
    "posted_precision": "week",
    "description_html": "<p>Build pipelines.</p>",
    "details": {
        "apply_method": "external",
        "reposted": False,
        "skills_listed": ["SQL", "Python"],
        "level": 3,
        "x": None,
    },
    "volatile_details": {"applicants": "12 applicants"},
}


def parse(data, name="posting.json"):
    raw = data if isinstance(data, bytes) else json.dumps(data).encode()
    return PARSER.parse(CaptureFile(Path(name), raw, MTIME))


def without(key):
    return {k: v for k, v in COMPLETE.items() if k != key}


def test_complete_posting_file():
    posting = parse(COMPLETE)
    assert isinstance(posting, ParsedPosting)
    assert (posting.source, posting.external_id, posting.url) == ("jobs.example.com", "A-1042", COMPLETE["url"])
    assert (posting.title, posting.company, posting.location) == ("Data Engineer", "Acme", "Example City, EX")
    assert (posting.workplace_type, posting.employment_type) == ("Remote", "Full-time")
    assert (posting.posted_on, posting.posted_precision) == (date(2026, 9, 30), "week")
    assert posting.description_html == "<p>Build pipelines.</p>" and posting.description_text is None
    assert posting.details == COMPLETE["details"]
    assert posting.volatile_details == {"applicants": "12 applicants"}
    assert posting.captured_at is None


def test_precision_defaults_to_day():
    assert parse(without("posted_precision")).posted_precision == "day"


def test_optional_fields_may_be_left_out():
    minimal = {
        k: COMPLETE[k]
        for k in ("format", "version", "source", "external_id", "url", "title", "company", "description_html")
    }
    posting = parse(minimal)
    assert isinstance(posting, ParsedPosting)
    assert (posting.location, posting.workplace_type, posting.posted_on, posting.posted_precision) == (
        None,
        None,
        None,
        None,
    )
    assert posting.details == {} and posting.volatile_details == {}


def test_captured_at_is_converted_to_utc():
    posting = parse({**COMPLETE, "captured_at": "2026-09-01T06:00:00-03:00"})
    assert posting.captured_at == datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
    assert parse({**COMPLETE, "captured_at": "2026-09-01T09:00:00Z"}).captured_at == posting.captured_at


@pytest.mark.parametrize("field", ["source", "external_id", "url", "title", "company", "description_html"])
def test_missing_required_field_is_named(field):
    result = parse(without(field))
    assert isinstance(result, Rejected) and repr(field) in result.reason


def test_empty_required_field_is_named():
    result = parse({**COMPLETE, "company": "  "})
    assert isinstance(result, Rejected) and "'company'" in result.reason


@pytest.mark.parametrize("data", [
    {"format": "something-else", "version": 1},
    {"title": "Data Engineer"},
    [1, 2, 3],
    "jobhunt-posting",
])
def test_other_json_is_not_recognised(data):
    assert parse(data) is None


@pytest.mark.parametrize("raw", [b"<html><body>Hi</body></html>", b"\xff\xfe\x00", b""])
def test_non_json_is_not_recognised(raw):
    assert parse(raw, "page.html") is None


def test_recognised_by_contents_not_name():
    assert isinstance(parse(COMPLETE, "saved page.html"), ParsedPosting)


def test_unsupported_version():
    result = parse({**COMPLETE, "version": 2})
    assert isinstance(result, Rejected) and "unsupported version 2" in result.reason


@pytest.mark.parametrize("version", [None, "1", True])
def test_version_must_be_a_whole_number(version):
    result = parse({**COMPLETE, "version": version})
    assert isinstance(result, Rejected) and "'version'" in result.reason


def test_unknown_top_level_field_is_named():
    result = parse({**COMPLETE, "salary": "100k"})
    assert isinstance(result, Rejected) and "'salary'" in result.reason


@pytest.mark.parametrize("changes, field", [
    ({"title": 7}, "title"),
    ({"location": ["Example City"]}, "location"),
    ({"workplace_type": "Remote-first"}, "workplace_type"),
    ({"posted_on": "last week"}, "posted_on"),
    ({"posted_precision": "fortnight"}, "posted_precision"),
    ({"captured_at": "2026-09-01T09:00:00"}, "captured_at"),
    ({"details": ["a"]}, "details"),
    ({"details": {"nested": {"a": 1}}}, "nested"),
    ({"volatile_details": {"mixed": ["a", 1]}}, "mixed"),
    ({"url": "ftp://jobs.example.com/1"}, "url"),
    ({"url": "/view/1"}, "url"),
    ({"source": "Jobs.Example.com"}, "source"),
])
def test_wrong_values_are_named(changes, field):
    result = parse({**COMPLETE, **changes})
    assert isinstance(result, Rejected) and repr(field) in result.reason


def test_precision_without_a_date_is_rejected():
    result = parse({**without("posted_on"), "posted_precision": "day"})
    assert isinstance(result, Rejected) and "'posted_precision'" in result.reason


def test_non_finite_numbers_are_not_recognised():
    assert parse(json.dumps(COMPLETE).replace('"level": 3', '"level": NaN').encode()) is None


@pytest.mark.parametrize("path", sorted(POSTINGS.glob("*.json")), ids=lambda p: p.name)
def test_every_fixture_parses(path):
    assert isinstance(PARSER.parse(CaptureFile(path, path.read_bytes(), MTIME)), ParsedPosting)
