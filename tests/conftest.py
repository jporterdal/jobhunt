import json
from contextlib import contextmanager
from datetime import UTC
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
POSTINGS = FIXTURES / "postings"


PG_URL_ENV = "JOBHUNT_TEST_PG_URL"


@pytest.fixture(params=["sqlite", "postgres"])
def empty_engine(request, tmp_path):
    """An empty database: a temp SQLite file, or a throwaway Postgres schema."""
    with throwaway_engine(request.param, tmp_path / "test.db") as eng:
        yield eng


@contextmanager
def throwaway_engine(backend: str, sqlite_path: Path):
    """An empty database on `backend` ("sqlite": a file at `sqlite_path`; "postgres": a schema dropped afterwards,
    or the test is skipped without JOBHUNT_TEST_PG_URL)."""
    import os
    import uuid

    from sqlalchemy import text

    from jobhunt.db import make_engine

    if backend == "sqlite":
        eng = make_engine(f"sqlite:///{sqlite_path}")
        yield eng
        eng.dispose()
        return

    url = os.environ.get(PG_URL_ENV)
    if not url:
        pytest.skip(f"set {PG_URL_ENV} to run Postgres tests")
    schema = f"jh_test_{uuid.uuid4().hex[:12]}"
    admin = make_engine(url)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    eng = make_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        yield eng
    finally:
        eng.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture
def engine(empty_engine):
    """An initialized database (schema at head) on each configured backend."""
    from jobhunt.db import init_db

    init_db(empty_engine)
    return empty_engine


def posting_file(name: str) -> Path:
    return POSTINGS / name


def posting_text(name: str) -> str:
    """The plain text the store derives from a posting file's description."""
    from jobhunt.sanitize import clean_html, html_to_text

    return html_to_text(clean_html(json.loads(posting_file(name).read_text(encoding="utf-8"))["description_html"]))


def add_posting(engine, fixture="data-automation.json", captured_at=None, tag="", **changes) -> int:
    """Import an invented posting file through the built-in parser; returns the posting's key.

    `changes` replace the file's fields (a changed re-capture); `description_text` alone becomes HTML with one
    line break per newline, so the stored text is exactly it. `tag` makes the bytes differ without changing the
    compared content (it is a volatile detail).
    """
    import html
    from datetime import date, datetime

    from jobhunt.parsers import CaptureFile, label
    from jobhunt.parsers.posting_file import PARSER
    from jobhunt.sanitize import clean_html, html_to_text
    from jobhunt.store import store_capture

    data = json.loads(posting_file(fixture).read_text(encoding="utf-8"))
    text = changes.pop("description_text", None)
    if text is not None:
        changes.setdefault("description_html", "<p>" + html.escape(text, quote=False).replace("\n", "<br>") + "</p>")
        assert html_to_text(clean_html(changes["description_html"])) == text, "description_text must match the HTML"
    for key, value in changes.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value.isoformat() if isinstance(value, date) else value
    if tag:
        data["volatile_details"] = {**data.get("volatile_details", {}), "tag": tag}
    captured_at = captured_at or datetime(2026, 9, 20, 15, 0, tzinfo=UTC)
    data["captured_at"] = captured_at.isoformat()
    raw = json.dumps(data, ensure_ascii=False, indent=2).encode()

    posting = PARSER.parse(CaptureFile(Path(fixture), raw, captured_at))
    assert not hasattr(posting, "reason"), getattr(posting, "reason", None)
    with engine.begin() as conn:
        return store_capture(conn, posting, raw, fixture, captured_at, captured_at, label(PARSER)).job_id


BASE_URL = "http://127.0.0.1:8000"


@pytest.fixture
def web(engine, tmp_path):
    """(app, client) for the web interface on 127.0.0.1:8000, with a temp inbox and documents folder."""
    from jobhunt.web import create_app

    app = create_app(engine, tmp_path / "inbox", tmp_path / "documents", host="127.0.0.1", port=8000)
    app.config["TESTING"] = True
    return app, app.test_client()


@pytest.fixture
def client(web):
    return web[1]


CANDIDATE_SYSTEM = "Candidate prompt: list only the skills each numbered line names."


@pytest.fixture
def candidate(monkeypatch):
    """A test-only candidate skill extractor `atomic@5`, registered beside the app's `atomic@2`."""
    from jobhunt.enrich import skills

    extractor = skills.AtomicExtractor(5, CANDIDATE_SYSTEM, "\n\nList every skill the {group} lines name.")
    monkeypatch.setattr(skills, "EXTRACTORS", (skills.ATOMIC_V2, extractor))
    return extractor


def post(client, url, data=None, origin=BASE_URL, **kwargs):
    """A form post as the interface's own pages send it (with a same-origin Origin header)."""
    headers = kwargs.pop("headers", {})
    if origin is not None:
        headers.setdefault("Origin", origin)
    return client.post(BASE_URL + url, data=data or {}, headers=headers, **kwargs)


def get(client, url, **kwargs):
    return client.get(BASE_URL + url, **kwargs)


PIPELINE = "seg=llm-lines@2 skills=atomic@2 salary=paylines@1 validate=v@3"
CANDIDATE_PIPELINE = PIPELINE.replace("skills=atomic@2", "skills=atomic@5")  # see the candidate fixture


def add_run(
    engine,
    job_id=1,
    skills=(),
    salaries=(),
    status="succeeded",
    error=None,
    model="gemma4:12b",
    pipeline=PIPELINE,
    snapshot_id=None,
    segments=None,
    seconds=2.0,
    origin="app",
):
    """Store an extraction run on the posting's latest (or a given) snapshot, through derived.save_run.

    `skills` are (name, importance, quote) or SkillItems; quotes and amounts are validated against the
    snapshot text as a real run would. `segments` are (start, end, label) for the step trace. `origin` is
    'app' (the job queue's) or 'eval' (`jobhunt eval`'s).
    """
    from datetime import datetime, timedelta

    from sqlalchemy import select

    from jobhunt.db import posting_snapshots
    from jobhunt.enrich import derived, validate
    from jobhunt.enrich.pipeline import RunResult, Segment, SkillItem
    from jobhunt.store import latest_snapshot

    items = [s if isinstance(s, SkillItem) else SkillItem(s[0], s[1], "technical", s[2]) for s in skills]
    started = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
    with engine.begin() as conn:
        if snapshot_id is None:
            snapshot = latest_snapshot(conn, job_id)
        else:
            snapshot = conn.execute(select(posting_snapshots).where(posting_snapshots.c.id == snapshot_id)).one()
        text = snapshot.description_text
        segs = [Segment(*s) for s in segments or ()]
        result = RunResult(
            status,
            error,
            started,
            started + timedelta(seconds=seconds),
            segs,
            validate.check_skills(text, items) if status == "succeeded" else [],
            validate.check_salaries(text, list(salaries)) if status == "succeeded" else [],
            {"steps": [], "segments": [[s.start, s.end, s.label] for s in segs]},
        )
        return derived.save_run(conn, job_id, snapshot.id, model, pipeline, result, origin)
