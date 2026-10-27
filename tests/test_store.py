import dataclasses
import gzip
import json
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import func, inspect, select

from jobhunt.db import captures, posting_snapshots, postings
from jobhunt.parsers import CaptureFile
from jobhunt.parsers.posting_file import PARSER
from jobhunt.store import InvalidPosting, Stored, find_capture, read_capture, sha256_hex, store_capture

from .conftest import posting_file

SEP_20 = datetime(2026, 9, 20, 15, 0, tzinfo=UTC)
SEP_15 = datetime(2026, 9, 15, 15, 0, tzinfo=UTC)
OCT_1 = datetime(2026, 10, 1, 15, 0, tzinfo=UTC)
NOW = datetime(2026, 10, 2, 15, 0, tzinfo=UTC)

PATH = posting_file("data-automation.json")
RAW = PATH.read_bytes()
POSTING = PARSER.parse(CaptureFile(PATH, RAW, SEP_20))


def store(engine, posting=POSTING, raw=RAW, captured_at=SEP_20, name="a.json"):
    with engine.begin() as conn:
        return store_capture(conn, posting, raw, name, captured_at, NOW, "posting-file@1")


def variant(raw: bytes, tag: str) -> bytes:
    """Same posting, different bytes (as every re-capture is)."""
    return raw + f"\n{tag}".encode()


def count(engine, table):
    with engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(table)).scalar_one()


def posting_row(engine, source="jobs.example.com", external_id="A-1001"):
    with engine.connect() as conn:
        return conn.execute(
            select(postings).where(postings.c.source == source, postings.c.external_id == external_id)
        ).one()


def snapshots(engine):
    with engine.connect() as conn:
        return conn.execute(select(posting_snapshots).order_by(posting_snapshots.c.id)).all()


def test_schema_created(engine):
    names = set(inspect(engine).get_table_names())
    assert {"postings", "captures", "posting_snapshots"} <= names


def test_first_capture(engine):
    stored = store(engine)
    row = posting_row(engine)
    assert stored == Stored("new", row.job_id) and isinstance(row.job_id, int)
    assert (row.source, row.external_id) == ("jobs.example.com", "A-1001")
    assert row.url == "https://jobs.example.com/view/A-1001"
    assert row.first_seen_at == SEP_20 and row.last_seen_at == SEP_20
    [snap] = snapshots(engine)
    assert snap.title == POSTING.title and snap.company == "Example Bank"
    assert (snap.location, snap.workplace_type, snap.employment_type) == ("Example City, EX", "On-site", "Full-time")
    assert snap.posted_on_estimate == date(2026, 9, 14) and snap.posted_on_precision == "day"
    assert snap.parser == "posting-file@1"
    assert json.loads(snap.details_json) == {
        "apply_method": "external",
        "promotion": "Promoted by hirer",
        "reposted": True,
    }
    assert json.loads(snap.volatile_json) == {"applicants": "30 applicants", "posted_age": "6 days ago"}
    assert snap.description_text.startswith("Job Description\n\nAbout the role")


def test_capture_round_trip(engine):
    store(engine)
    with engine.connect() as conn:
        capture_id = find_capture(conn, sha256_hex(RAW)).id
        stored = conn.execute(select(captures).where(captures.c.id == capture_id)).one()
        assert read_capture(conn, capture_id) == RAW
    assert stored.sha256 == sha256_hex(RAW)
    assert gzip.decompress(stored.raw_gz) == RAW
    assert stored.source_name == "a.json" and stored.parser == "posting-file@1"
    assert stored.captured_at == SEP_20 and stored.imported_at == NOW


def test_recapture_later(engine):
    store(engine, captured_at=SEP_20)
    store(engine, raw=variant(RAW, "2"), captured_at=OCT_1)
    row = posting_row(engine)
    assert row.first_seen_at == SEP_20 and row.last_seen_at == OCT_1


def test_older_capture_after_newer(engine):
    store(engine, captured_at=OCT_1)
    store(engine, raw=variant(RAW, "2"), captured_at=SEP_15)
    row = posting_row(engine)
    assert row.first_seen_at == SEP_15 and row.last_seen_at == OCT_1


def test_capture_time_from_the_parser(engine):
    given = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
    store(engine, posting=dataclasses.replace(POSTING, captured_at=given), captured_at=OCT_1)
    row = posting_row(engine)
    with engine.connect() as conn:
        capture = conn.execute(select(captures)).one()
    assert capture.captured_at == row.first_seen_at == row.last_seen_at == given


def test_unchanged_recapture_with_new_volatile_details(engine):
    first = store(engine)
    busier = dataclasses.replace(
        POSTING, volatile_details={"applicants": "95 applicants"}, posted_on=date(2026, 9, 1), warnings=("odd",)
    )
    assert store(engine, posting=busier, raw=variant(RAW, "2"), captured_at=OCT_1) == Stored("unchanged", first.job_id)
    assert count(engine, posting_snapshots) == 1
    assert count(engine, captures) == 2
    assert posting_row(engine).last_seen_at == OCT_1


def test_details_compare_by_value_regardless_of_order_and_empty_values(engine):
    store(engine)
    same = dataclasses.replace(
        POSTING, details={"reposted": True, "promotion": "Promoted by hirer", "apply_method": "external", "x": None,
                          "y": "", "z": []},
    )
    assert store(engine, posting=same, raw=variant(RAW, "2")).outcome == "unchanged"


def test_changed_detail_adds_snapshot(engine):
    store(engine)
    changed = dataclasses.replace(POSTING, details={**POSTING.details, "reposted": False})
    assert store(engine, posting=changed, raw=variant(RAW, "2"), captured_at=OCT_1).outcome == "updated"
    assert [json.loads(s.details_json)["reposted"] for s in snapshots(engine)] == [True, False]


def test_changed_description_adds_snapshot(engine):
    store(engine)
    [first] = snapshots(engine)
    edited = dataclasses.replace(POSTING, description_html=POSTING.description_html + "<p>New requirement</p>")
    assert store(engine, posting=edited, raw=variant(RAW, "2"), captured_at=OCT_1).outcome == "updated"
    snaps = snapshots(engine)
    assert len(snaps) == 2
    assert snaps[0] == first  # history is never rewritten
    assert snaps[1].description_text.endswith("New requirement")


def test_look_alike_postings_stay_separate(engine):
    twin = dataclasses.replace(POSTING, external_id="A-1099", url="https://jobs.example.com/view/A-1099")
    first = store(engine)
    second = store(engine, posting=twin, raw=variant(RAW, "twin"))
    assert second.outcome == "new" and second.job_id != first.job_id
    assert count(engine, postings) == 2


def test_same_external_id_from_two_sources(engine):
    other = dataclasses.replace(POSTING, source="careers.example.org", url="https://careers.example.org/jobs/A-1001")
    first = store(engine)
    second = store(engine, posting=other, raw=variant(RAW, "other"))
    assert second.outcome == "new" and second.job_id != first.job_id
    assert posting_row(engine, "careers.example.org").job_id == second.job_id


def test_description_is_sanitized_and_text_derived(engine):
    unsafe = dataclasses.replace(
        POSTING,
        description_html='<p onclick="x()">Hi <a href="javascript:alert(1)">there</a></p><script>bad()</script>',
    )
    store(engine, posting=unsafe)
    [snap] = snapshots(engine)
    assert snap.description_html == "<p>Hi <a>there</a></p>"
    assert snap.description_text == "Hi there"


def test_parser_supplied_text_is_kept(engine):
    store(engine, posting=dataclasses.replace(POSTING, description_text="The parser's own text."))
    [snap] = snapshots(engine)
    assert snap.description_text == "The parser's own text."
    assert snap.description_html == POSTING.description_html


@pytest.mark.parametrize("changes, message", [
    ({"source": "Jobs.Example.com"}, "source"),
    ({"source": ""}, "source"),
    ({"external_id": " "}, "external ID"),
    ({"title": ""}, "title"),
    ({"description_html": "<script>x</script>"}, "description is empty"),
    ({"details": {"nested": {"a": 1}}}, "'nested'"),
    ({"volatile_details": {"n": float("nan")}}, "'n'"),
])
def test_invalid_postings_are_refused(engine, changes, message):
    with pytest.raises(InvalidPosting, match=message):
        store(engine, posting=dataclasses.replace(POSTING, **changes))


def test_sqlite_folder_created_on_demand(tmp_path):
    from jobhunt.db import init_db, make_engine

    db_file = tmp_path / "data" / "nested" / "jobhunt.db"
    eng = make_engine(f"sqlite:///{db_file}")
    init_db(eng)
    eng.dispose()
    assert db_file.exists()
