import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select

from jobhunt import importer
from jobhunt.cli import main
from jobhunt.db import captures, posting_snapshots, postings
from jobhunt.importer import discover, format_report, import_files
from jobhunt.parsers.posting_file import PARSER

from .conftest import posting_file
from .fakes import FakeParser, fake_file

ALPHA, BETA = FakeParser("alpha"), FakeParser("beta", "2")
PARSERS = [PARSER, ALPHA, BETA]


def put(folder: Path, fixture: str, name: str, mtime: int | None = None, zone: bool = False) -> Path:
    """Copy an invented posting file into `folder` as `name`."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    shutil.copyfile(posting_file(fixture), path)
    return _finish(path, mtime, zone)


def write(folder: Path, name: str, content: str, mtime: int | None = None, zone: bool = False) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(content, encoding="utf-8")
    return _finish(path, mtime, zone)


def _finish(path: Path, mtime: int | None, zone: bool) -> Path:
    if zone:
        (path.parent / (path.name + ":Zone.Identifier")).write_text("[ZoneTransfer]\nZoneId=3\n")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def rows(engine, table, *where):
    with engine.connect() as conn:
        return conn.execute(select(table).where(*where)).all()


def count(engine, table):
    with engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(table)).scalar_one()


def key(engine, source, external_id):
    with engine.connect() as conn:
        return conn.execute(
            select(postings.c.job_id).where(postings.c.source == source, postings.c.external_id == external_id)
        ).scalar_one()


# --- Discovery ---


def test_discovery(tmp_path):
    inbox = tmp_path / "inbox"
    put(inbox, "data-automation.json", "a.json", zone=True)
    write(inbox, "b.html", fake_file("alpha", wrap_html=True))
    (inbox / "c").mkdir()
    put(inbox / "processed", "innovation-lab.json", "old.json")
    assert [p.name for p in discover(inbox, PARSERS)] == ["a.json", "b.html"]


def test_discovery_orders_oldest_first(tmp_path):
    put(tmp_path, "data-automation.json", "newer.json", mtime=2_000_000_000)
    put(tmp_path, "innovation-lab.json", "older.json", mtime=1_900_000_000)
    assert [p.name for p in discover(tmp_path, PARSERS)] == ["older.json", "newer.json"]


def test_companions_named_by_a_parser(engine, tmp_path):
    inbox = tmp_path / "inbox"
    paged = FakeParser("paged", companion_suffixes=(".txt", ".meta"))
    write(inbox, "page.html", fake_file("paged", wrap_html=True))
    write(inbox, "page.txt", "text form")
    write(inbox, "page.meta", "metadata")
    assert [p.name for p in discover(inbox, [paged])] == ["page.html"]

    [result] = import_files(engine, discover(inbox, [paged]), inbox, [paged])
    assert result.outcome == "new"
    assert sorted(p.name for p in inbox.iterdir()) == ["processed"]
    assert sorted(p.name for p in (inbox / "processed").iterdir()) == ["page.html", "page.meta", "page.txt"]


# --- Choosing a parser ---


def test_two_parsers_for_html_files(engine, tmp_path):
    path = write(tmp_path, "page.html", fake_file("alpha", wrap_html=True, id="7", title="Data Engineer"))
    [result] = import_files(engine, [path], parsers=PARSERS)
    assert (result.outcome, result.source, result.external_id, result.title) == (
        "new",
        "alpha.example",
        "7",
        "Data Engineer",
    )
    assert result.job_id == key(engine, "alpha.example", "7")
    with engine.connect() as conn:
        assert conn.execute(select(captures.c.parser)).scalar_one() == "alpha@1"
        assert conn.execute(select(posting_snapshots.c.parser)).scalar_one() == "alpha@1"


def test_a_failing_parser_rejects_only_that_file(engine, tmp_path):
    bad = write(tmp_path, "bad.html", fake_file("alpha", wrap_html=True, **{"raise": "boom"}), mtime=1_900_000_001)
    good = write(tmp_path, "good.html", fake_file("beta", wrap_html=True), mtime=1_900_000_002)
    results = import_files(engine, [bad, good], parsers=PARSERS)
    assert [r.outcome for r in results] == ["rejected", "new"]
    assert results[0].reason == "alpha@1: RuntimeError: boom"
    assert count(engine, postings) == 1


def test_nothing_recognises_the_file(engine, tmp_path):
    [result] = import_files(engine, [write(tmp_path, "notes.txt", "just some notes")], parsers=PARSERS)
    assert result.outcome == "rejected"
    assert result.reason == "not recognised by any installed parser (posting-file@1, alpha@1, beta@2)"
    assert count(engine, captures) == 0


def test_recognised_but_unusable(engine, tmp_path):
    path = write(tmp_path, "x.html", fake_file("alpha", reject="the description is empty"))
    [result] = import_files(engine, [path], parsers=PARSERS)
    assert (result.outcome, result.reason) == ("rejected", "alpha@1: the description is empty")


def test_posting_file_rejection_names_the_field(engine, tmp_path):
    data = json.loads(posting_file("data-automation.json").read_text())
    del data["company"]
    [result] = import_files(engine, [write(tmp_path, "a.json", json.dumps(data))], parsers=PARSERS)
    assert result.outcome == "rejected" and result.reason == "posting-file@1: missing field 'company'"


def test_two_parsers_accepting_one_file(engine, tmp_path):
    [result] = import_files(engine, [write(tmp_path, "x.html", fake_file("any"))], parsers=PARSERS)
    assert result.outcome == "rejected"
    assert result.reason == "accepted by more than one parser (alpha@1, beta@2)"
    assert count(engine, postings) == count(engine, captures) == 0


def test_store_refusal_is_the_parsers_error(engine, tmp_path):
    path = write(tmp_path, "x.html", fake_file("alpha", source="Not A Source"))
    [result] = import_files(engine, [path], parsers=PARSERS)
    assert result.outcome == "rejected" and result.reason.startswith("alpha@1: source 'Not A Source'")


def test_parser_warnings_reach_the_report(engine, tmp_path):
    [result] = import_files(
        engine, [write(tmp_path, "x.html", fake_file("alpha", warning="odd header"))], parsers=PARSERS
    )
    assert result.warnings == ["odd header"]
    assert "| warning: odd header" in format_report([result])


def test_load_warnings_start_the_report():
    report = format_report([], ["parser 'broken' failed to load: ImportError: x"])
    assert report.splitlines()[0] == "warning: parser 'broken' failed to load: ImportError: x"


# --- Processing and outcomes ---


def test_mixed_batch(engine, tmp_path):
    inbox = tmp_path / "inbox"
    import_files(engine, [posting_file("data-automation.json")], parsers=PARSERS)

    put(inbox, "senior-ai-engineer.json", "new.json", mtime=1_900_000_001)
    put(inbox, "data-automation-changed.json", "recapture.json", mtime=1_900_000_002)
    write(inbox, "broken.html", "<html>not a posting</html>", mtime=1_900_000_003)
    results = import_files(engine, discover(inbox, PARSERS), inbox, PARSERS)

    assert [(r.name, r.outcome) for r in results] == [
        ("new.json", "new"), ("recapture.json", "updated"), ("broken.html", "rejected")
    ]
    assert "not recognised" in results[2].reason
    report = format_report(results)
    assert report.splitlines()[-1] == "Totals: 1 new, 1 updated, 1 rejected"
    assert report.splitlines()[0].startswith("new       jobs.example.com A-1003 senior AI Engineer — Example Labs")
    assert "https://jobs.example.com/view/A-1003" in report
    job_id = key(engine, "jobs.example.com", "A-1001")
    assert len(rows(engine, posting_snapshots, posting_snapshots.c.job_id == job_id)) == 2


def test_identical_file_is_duplicate(engine, tmp_path):
    inbox = tmp_path / "inbox"
    put(inbox, "data-automation.json", "a.json")
    import_files(engine, discover(inbox, PARSERS), inbox, PARSERS)
    before = (count(engine, captures), count(engine, posting_snapshots), rows(engine, postings))

    shutil.copy2(inbox / "processed" / "a.json", inbox / "a.json")
    [result] = import_files(engine, discover(inbox, PARSERS), inbox, PARSERS)

    assert result.outcome == "duplicate"
    assert (result.source, result.external_id) == ("jobs.example.com", "A-1001")
    assert result.job_id == key(engine, "jobs.example.com", "A-1001")
    assert result.title == "Analytics Manager, Reporting Automation (Example City)"
    assert (count(engine, captures), count(engine, posting_snapshots), rows(engine, postings)) == before
    assert (inbox / "processed" / "a (2).json").exists()


def test_import_at_a_fixed_time(engine, tmp_path):
    captured = datetime(2026, 9, 20, 15, 0, tzinfo=UTC)
    now = datetime(2026, 10, 1, 9, 30, tzinfo=UTC)
    put(tmp_path, "data-automation.json", "a.json", mtime=int(captured.timestamp()))
    import_files(engine, [tmp_path / "a.json"], parsers=PARSERS, now=now)
    [capture], [posting] = rows(engine, captures), rows(engine, postings)
    assert capture.imported_at == now and capture.captured_at == captured
    assert posting.first_seen_at == posting.last_seen_at == captured


def test_unexpected_error_mid_batch(engine, tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    put(inbox, "data-automation.json", "1.json", mtime=1_900_000_001)
    put(inbox, "innovation-lab.json", "2.json", mtime=1_900_000_002)
    put(inbox, "senior-ai-engineer.json", "3.json", mtime=1_900_000_003)

    real_store = importer.store_capture

    def flaky(conn, posting, *args):
        if posting.external_id == "1002":
            raise ValueError("boom")
        return real_store(conn, posting, *args)

    monkeypatch.setattr(importer, "store_capture", flaky)
    results = import_files(engine, discover(inbox, PARSERS), inbox, PARSERS)

    assert [r.outcome for r in results] == ["new", "rejected", "new"]
    assert results[1].reason == "unexpected error: ValueError: boom"
    assert rows(engine, postings, postings.c.external_id == "1002") == []
    assert (inbox / "rejected" / "2.json").exists()


def test_failure_after_writes_rolls_back(engine, tmp_path, monkeypatch):
    def fail_after_writes(conn, posting, *args):
        real_store(conn, posting, *args)
        raise RuntimeError("disk full")

    real_store = importer.store_capture
    monkeypatch.setattr(importer, "store_capture", fail_after_writes)
    [result] = import_files(engine, [put(tmp_path, "data-automation.json", "a.json")], parsers=PARSERS)
    assert result.outcome == "rejected"
    assert count(engine, postings) == count(engine, captures) == count(engine, posting_snapshots) == 0


# --- Moving files ---


def test_accepted_file_moves_with_its_download_metadata(engine, tmp_path):
    inbox = tmp_path / "inbox"
    put(inbox, "data-automation.json", "a.json", zone=True)
    import_files(engine, discover(inbox, PARSERS), inbox, PARSERS)
    assert sorted(p.name for p in inbox.iterdir()) == ["processed"]
    assert sorted(p.name for p in (inbox / "processed").iterdir()) == ["a.json", "a.json:Zone.Identifier"]


def test_rejected_file_is_set_aside_with_every_parsers_companions(engine, tmp_path):
    inbox = tmp_path / "inbox"
    paged = FakeParser("paged", companion_suffixes=("_files",))
    write(inbox, "profile.html", "<html>a profile page</html>", zone=True)
    (inbox / "profile_files").mkdir()
    write(inbox / "profile_files", "logo.png", "png")
    [result] = import_files(engine, discover(inbox, [PARSER, paged]), inbox, [PARSER, paged])
    assert result.outcome == "rejected"
    assert sorted(p.name for p in (inbox / "rejected").iterdir()) == [
        "profile.html", "profile.html:Zone.Identifier", "profile_files"
    ]
    assert (inbox / "rejected" / "profile_files" / "logo.png").exists()
    assert count(engine, captures) == 0


def test_import_still_moves_discardable_companions(engine, tmp_path):
    inbox = tmp_path / "inbox"
    paged = FakeParser("paged", companion_suffixes=("_files",), discardable_suffixes=("_files",))
    write(inbox, "page.html", fake_file("paged", id="9000000001"))
    write(inbox / "page_files", "logo.png", "png")
    [result] = import_files(engine, discover(inbox, [PARSER, paged]), inbox, [PARSER, paged])
    assert result.outcome == "new"
    assert sorted(p.name for p in inbox.iterdir()) == ["processed"]
    assert sorted(p.name for p in (inbox / "processed").iterdir()) == ["page.html", "page_files"]
    assert (inbox / "processed" / "page_files" / "logo.png").read_text() == "png"


def test_name_collision_keeps_both(engine, tmp_path):
    inbox = tmp_path / "inbox"
    put(inbox / "processed", "innovation-lab.json", "a.json")
    put(inbox, "data-automation.json", "a.json", zone=True)
    import_files(engine, discover(inbox, PARSERS), inbox, PARSERS)
    names = sorted(p.name for p in (inbox / "processed").iterdir())
    assert names == ["a (2).json", "a (2).json:Zone.Identifier", "a.json"]
    assert (inbox / "processed" / "a.json").read_bytes() == posting_file("innovation-lab.json").read_bytes()


def test_collision_of_a_companion_moves_the_number_on(engine, tmp_path):
    inbox = tmp_path / "inbox"
    write(inbox / "processed", "a (2).json:Zone.Identifier", "older")
    put(inbox / "processed", "innovation-lab.json", "a.json")
    put(inbox, "data-automation.json", "a.json", zone=True)
    import_files(engine, discover(inbox, PARSERS), inbox, PARSERS)
    assert (inbox / "processed" / "a (3).json").exists() and (
        inbox / "processed" / "a (3).json:Zone.Identifier"
    ).exists()


def test_explicit_paths_are_not_moved(engine, tmp_path):
    path = put(tmp_path, "data-automation.json", "copy.json")
    [result] = import_files(engine, [path], parsers=PARSERS)
    assert result.outcome == "new"
    assert path.exists()
    assert not (tmp_path / "processed").exists()


def test_installed_parsers_by_default(engine, tmp_path):
    [result] = import_files(engine, [put(tmp_path, "data-automation.json", "a.json")])
    assert result.outcome == "new"


# --- CLI ---


def test_cli_imports_inbox(tmp_path, capsys):
    inbox = tmp_path / "inbox"
    put(inbox, "data-automation.json", "A.json", mtime=1_900_000_001)
    write(inbox, "B.html", "<html>a saved page</html>", mtime=1_900_000_002)
    db = tmp_path / "data" / "test.db"

    assert main(["import", "--inbox", str(inbox), "--db", f"sqlite:///{db}"]) == 0

    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith(
        "new       jobs.example.com A-1001 Analytics Manager, Reporting Automation (Example City) — Example Bank"
    )
    assert "https://jobs.example.com/view/A-1001" in out[0]
    assert out[1].startswith("rejected  B.html: not recognised by any installed parser (")
    assert "posting-file@1" in out[1]
    assert out[2] == "Totals: 1 new, 1 rejected"
    assert db.exists()


def test_cli_env_defaults_and_empty_inbox(tmp_path, capsys, monkeypatch):
    inbox = tmp_path / "empty"
    inbox.mkdir()
    monkeypatch.setenv("JOBHUNT_INBOX", str(inbox))
    monkeypatch.setenv("JOBHUNT_DB_URL", f"sqlite:///{tmp_path / 'x.db'}")
    assert main(["import"]) == 0
    assert capsys.readouterr().out.strip() == f"Nothing to import in {inbox}"


def test_cli_db_url_from_env(tmp_path, capsys, monkeypatch):
    inbox = tmp_path / "inbox"
    put(inbox, "data-automation.json", "A.json")
    db = tmp_path / "from-env.db"
    monkeypatch.setenv("JOBHUNT_INBOX", str(inbox))
    monkeypatch.setenv("JOBHUNT_DB_URL", f"sqlite:///{db}")
    assert main(["import"]) == 0
    assert db.exists()


def test_cli_default_db_path(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("JOBHUNT_DB_URL", raising=False)
    monkeypatch.delenv("JOBHUNT_INBOX", raising=False)
    monkeypatch.chdir(tmp_path)
    put(tmp_path / "inbox", "data-automation.json", "A.json")
    assert main(["import"]) == 0
    assert (tmp_path / "data" / "jobhunt.db").exists()


def test_cli_explicit_path(tmp_path, capsys):
    path = put(tmp_path, "senior-ai-engineer.json", "copy.json")
    assert main(["import", str(path), "--db", f"sqlite:///{tmp_path / 'x.db'}"]) == 0
    assert capsys.readouterr().out.startswith("new       jobs.example.com A-1003")
    assert path.exists()


def test_cli_missing_inbox_is_an_error(tmp_path, capsys):
    assert main(["import", "--inbox", str(tmp_path / "nope"), "--db", f"sqlite:///{tmp_path / 'x.db'}"]) == 2
    assert "inbox folder not found" in capsys.readouterr().err


def test_cli_help_names_no_site(capsys):
    import pytest

    with pytest.raises(SystemExit):
        main(["import", "--help"])
    out = capsys.readouterr().out
    assert "installed parsers" in out and "jobhunt-posting" in out
