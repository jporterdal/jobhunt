import json
import socket

import pytest
from sqlalchemy import func, select

from jobhunt import documents, privacy
from jobhunt.cli import main
from jobhunt.db import (
    DERIVED_TABLES,
    USER_TABLES,
    enrichment_salaries,
    enrichment_skills,
    init_db,
    posting_enrichments,
    postings,
    records,
    tailored_cvs,
)
from jobhunt.demo import persona, seed
from jobhunt.demo.scripted import CHAT_MODEL
from jobhunt.importer import import_files
from jobhunt.parsers.posting_file import PARSER

from .conftest import add_posting, throwaway_engine

# Written by the clock, not by the demo: when a run was made and how long its steps took.
CLOCK_COLUMNS = {"created_at", "started_at", "finished_at"}


def build(engine, tmp_path, name="documents"):
    return seed.build(engine, tmp_path / name)


def count(conn, table, *where):
    return conn.execute(select(func.count()).select_from(table).where(*where)).scalar_one()


def job_id(conn, external_id):
    return conn.execute(select(postings.c.job_id).where(postings.c.external_id == external_id)).scalar_one()


def test_postings_come_in_through_the_public_format(engine):
    outcomes = [r.outcome for path in seed.posting_files() for r in import_files(engine, [path], parsers=[PARSER])]
    assert outcomes == ["new"] * 10 + ["updated"]
    with engine.connect() as conn:
        ids = sorted(conn.execute(select(postings.c.external_id)).scalars())
    assert ids == [str(n) for n in range(9000000101, 9000000111)]


def test_every_scripted_suggestion_is_verified(engine, tmp_path):
    build(engine, tmp_path)
    with engine.connect() as conn:
        assert count(conn, posting_enrichments, posting_enrichments.c.status != "succeeded") == 0
        assert count(conn, enrichment_skills, enrichment_skills.c.verified.is_(False)) == 0
        assert count(conn, enrichment_salaries, enrichment_salaries.c.verified.is_(False)) == 0
        for run in conn.execute(select(posting_enrichments)):
            assert run.model == CHAT_MODEL
            assert count(conn, enrichment_skills, enrichment_skills.c.enrichment_id == run.id) > 0


def test_demo_into_a_new_database(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["demo"]) == 0
    assert (tmp_path / "demo" / "jobhunt.db").is_file() and any((tmp_path / "demo" / "documents").iterdir())
    out = capsys.readouterr().out
    assert "jobhunt serve --db sqlite:///demo/jobhunt.db --documents demo/documents" in out


def test_real_data_is_refused_by_the_command(tmp_path, capsys):
    url = f"sqlite:///{tmp_path / 'real.db'}"
    with throwaway_engine("sqlite", tmp_path / "real.db") as engine:
        init_db(engine)
        add_posting(engine)
        before = (tmp_path / "real.db").read_bytes()
    assert main(["demo", "--db", url, "--documents", str(tmp_path / "docs")]) == 2
    assert "isn't empty" in capsys.readouterr().err
    assert (tmp_path / "real.db").read_bytes() == before and not (tmp_path / "docs").exists()


def test_refusals(engine, tmp_path):
    assert seed.refusal(engine, tmp_path / "documents") is None
    (tmp_path / "documents").mkdir()
    (tmp_path / "documents" / "a.txt").write_text("x")
    assert "isn't empty" in seed.refusal(engine, tmp_path / "documents")
    add_posting(engine)
    assert "postings" in seed.refusal(engine, tmp_path / "other")


def test_built_offline(tmp_path, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("the demo must not open a network connection")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    with throwaway_engine("sqlite", tmp_path / "demo.db") as engine:
        init_db(engine)
        build(engine, tmp_path)
        with engine.connect() as conn:
            assert count(conn, posting_enrichments) == 10


@pytest.fixture
def demo(engine, tmp_path):
    """(engine, test client, the demo's ids) for a fresh demo database, served with no model server."""
    from jobhunt.web import create_app

    built = build(engine, tmp_path)
    app = create_app(engine, tmp_path / "inbox", tmp_path / "documents", host="127.0.0.1", port=8000)
    app.config["TESTING"] = True
    with engine.connect() as conn:
        ids = {external_id: job_id(conn, external_id) for external_id in persona.TRIAGE}
    return engine, app.test_client(), ids, built


def page(client, path: str) -> str:
    response = client.get(path, base_url="http://127.0.0.1:8000")
    assert response.status_code == 200, path
    return response.get_data(as_text=True)


def test_every_page_has_content(demo):
    engine, client, ids, built = demo
    tailored = ids[persona.TAILORED_FOR]
    expected = {
        "/": ["Machine Learning Engineer", "Example Payments", "Demo data"],
        f"/postings/{tailored}": ["Model says", CHAT_MODEL, "Have (", "Don't have (", "Original posting"],
        f"/postings/{ids['9000000103']}": ["Power BI", "$88,000"],
        "/insights": ["Analytics Lead, Health Data", "Large language models"],
        "/applications": ["Machine Learning Engineer", "Data Engineer"],
        "/companies": ["Example Labs"],
        "/skills": ["Python"],
        "/profile": ["Jane Doe", "Claim triage model", "Contract Analyst", "sklearn"],
        "/profile/links": ["Statistical modelling", "Power BI"],
        f"/postings/{tailored}/cv": ["Jane Doe", "Claim triage model"],
        f"/cvs/{built.cv_id}": ["Jane Doe", "Example Insurance"],
        "/settings": [CHAT_MODEL],
    }
    for path, values in expected.items():
        html = page(client, path)
        for value in values:
            assert value in html, (path, value)

    response = client.get(f"/cvs/{built.cv_id}.odt", base_url="http://127.0.0.1:8000")
    assert response.status_code == 200
    text = documents.odt_text(response.get_data())
    assert "Jane Doe" in text and "Example Insurance" in text
    assert "Contract Analyst" not in text  # a private record is never printed


def comparable(conn, table) -> list[tuple]:
    """The table's rows by primary key, without clock-written columns or step timings."""
    columns = [c for c in table.columns if c.name not in CLOCK_COLUMNS]
    order = list(table.primary_key.columns) or columns
    return [tuple(_untimed(v) for v in row) for row in conn.execute(select(*columns).order_by(*order))]


def _untimed(value):
    if isinstance(value, str) and value[:1] in "{[":
        try:
            return json.dumps(_strip_seconds(json.loads(value)), sort_keys=True)
        except ValueError:
            return value
    return value


def _strip_seconds(value):
    if isinstance(value, dict):
        return {k: _strip_seconds(v) for k, v in value.items() if k != "seconds"}
    if isinstance(value, list):
        return [_strip_seconds(v) for v in value]
    return value


def test_two_builds_match(engine, tmp_path):
    build(engine, tmp_path, "first")
    backend = "postgres" if engine.dialect.name == "postgresql" else "sqlite"
    with throwaway_engine(backend, tmp_path / "second.db") as second:
        init_db(second)
        build(second, tmp_path, "second")
        with engine.connect() as a, second.connect() as b:
            for table in USER_TABLES + DERIVED_TABLES:
                assert comparable(a, table) == comparable(b, table), table.name
            assert count(a, records) > 0 and count(a, tailored_cvs) == 1


def test_demo_data_passes_the_pattern_check():
    scanner = privacy.Scanner(privacy.Terms({}), privacy.Allowed())
    demo_dir = seed.POSTINGS_DIR.parent
    files = sorted(p for p in demo_dir.rglob("*") if p.is_file() and p.suffix in (".py", ".json"))
    assert len(files) > 11
    for path in files:
        assert scanner.scan_text(str(path), path.read_text(encoding="utf-8")) == [], path
