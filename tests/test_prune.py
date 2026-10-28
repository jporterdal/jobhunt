import json
import os
import threading
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from jobhunt import db, prune
from jobhunt.db import inbox_prunes
from jobhunt.parsers.posting_file import PARSER
from jobhunt.userdata import add_tag, set_notes

from .conftest import add_posting
from .fakes import FakeParser

PAGED = FakeParser("paged", companion_suffixes=("_files", ".meta"), discardable_suffixes=("_files",))
PARSERS = [PARSER, PAGED]
T0 = datetime(2026, 3, 2, 9, 0, tzinfo=UTC)


def page(folder, stem, assets=2, size=1000, zone=False):
    """A saved page `<stem>.html` with an asset folder `<stem>_files/` of `assets` files of `size` bytes."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{stem}.html").write_text("<html>a page</html>")
    files = folder / f"{stem}_files"
    files.mkdir()
    for i in range(assets):
        (files / f"asset{i}.js").write_bytes(b"x" * size)
    if zone:
        (folder / f"{stem}.html:Zone.Identifier").write_text("[ZoneTransfer]\nZoneId=3\n")
    return files


def names(folder):
    return sorted(p.name for p in folder.iterdir())


def records(engine):
    with engine.connect() as conn:
        return conn.execute(select(inbox_prunes).order_by(inbox_prunes.c.id)).all()


# --- What the prune looks at ---


def test_the_inbox_itself_is_untouched(engine, tmp_path):
    inbox = tmp_path / "inbox"
    page(inbox, "c")
    assert prune.plan(inbox, PARSERS) == []
    result = prune.run(engine, inbox, PARSERS, T0)
    assert result.removed == [] and names(inbox) == ["c.html", "c_files"]


def test_parser_no_longer_installed_keeps_its_companions(engine, tmp_path):
    inbox = tmp_path / "inbox"
    page(inbox / "processed", "a")
    assert prune.plan(inbox, [PARSER]) == []
    prune.run(engine, inbox, [PARSER], T0)
    assert names(inbox / "processed") == ["a.html", "a_files"]


def test_renamed_after_a_name_clash(tmp_path):
    inbox = tmp_path / "inbox"
    page(inbox / "processed", "a")
    page(inbox / "processed", "a (2)")
    assert sorted(c.path.name for c in prune.plan(inbox, PARSERS)) == ["a (2)_files", "a_files"]


def test_a_companion_is_not_asked_about_as_a_file_of_its_own(tmp_path):
    inbox = tmp_path / "inbox"
    page(inbox / "processed", "page")
    (inbox / "processed" / "page.meta").write_text("saved from somewhere")
    # Asked as a file of its own, `page.meta` would have a `page_files` companion by stem, owned twice.
    [planned] = prune.plan(inbox, PARSERS)
    assert planned.path.name == "page_files" and planned.owner.name == "page.html"
    assert planned.size == 2000


# --- Removing ---


def test_asset_folders_are_removed_and_pages_kept(engine, tmp_path):
    inbox = tmp_path / "inbox"
    page(inbox / "processed", "a", assets=3, size=500)
    page(inbox / "rejected", "b", assets=1, size=700, zone=True)
    result = prune.run(engine, inbox, PARSERS, T0)
    assert names(inbox / "processed") == ["a.html"]
    assert names(inbox / "rejected") == ["b.html", "b.html:Zone.Identifier"]
    assert sorted(c.path.name for c in result.removed) == ["a_files", "b_files"]
    assert result.bytes == 2200 and result.problems == []
    [row] = records(engine)
    assert (row.inbox, row.removed, row.bytes, row.problems) == (str(inbox.resolve()), 2, 2200, 0)
    assert row.started_at == T0 and row.finished_at >= T0
    assert json.loads(row.detail) == []
    assert result.summary() == "2 companions, 2.1 KB removed, 0 problems"


def test_a_link_to_elsewhere_is_removed_as_a_link(engine, tmp_path):
    inbox = tmp_path / "inbox"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("not the inbox's")
    (inbox / "processed").mkdir(parents=True)
    (inbox / "processed" / "a.html").write_text("<html></html>")
    try:
        os.symlink(outside, inbox / "processed" / "a_files", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links can't be made here")
    result = prune.run(engine, inbox, PARSERS, T0)
    assert [c.path.name for c in result.removed] == ["a_files"]
    assert names(inbox / "processed") == ["a.html"]
    assert (outside / "keep.txt").read_text() == "not the inbox's"


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignores permissions")
def test_a_companion_that_cant_be_removed_is_reported(engine, tmp_path):
    inbox = tmp_path / "inbox"
    locked = page(inbox / "processed", "a")
    page(inbox / "processed", "b")
    locked.chmod(0o500)  # its files can't be deleted
    try:
        result = prune.run(engine, inbox, PARSERS, T0)
    finally:
        locked.chmod(0o700)
    assert [c.path.name for c in result.removed] == ["b_files"]
    [(path, reason)] = result.problems
    assert path == locked and "Permission denied" in reason
    assert locked.exists() and not (inbox / "processed" / "b_files").exists()
    [row] = records(engine)
    assert (row.removed, row.problems) == (1, 1)
    assert json.loads(row.detail)[0][0] == "processed/a_files"


def test_missing_inbox_is_recorded_with_nothing_removed(engine, tmp_path):
    result = prune.run(engine, tmp_path / "nowhere", PARSERS, T0)
    assert result.missing and result.removed == []
    [row] = records(engine)
    assert (row.removed, row.bytes, row.problems) == (0, 0, 0)


def test_a_dry_run_removes_and_records_nothing(engine, tmp_path):
    inbox = tmp_path / "inbox"
    page(inbox / "processed", "a")
    result = prune.run(engine, inbox, PARSERS, T0, dry_run=True)
    assert [c.path.name for c in result.removed] == ["a_files"] and result.bytes == 2000
    assert names(inbox / "processed") == ["a.html", "a_files"]
    assert records(engine) == []
    assert result.summary() == "1 companion, 2.0 KB would be removed, 0 problems"


def test_a_path_already_gone_is_neither_counted_nor_a_problem(engine, tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    files = page(inbox / "processed", "a")
    planned = prune.plan(inbox, PARSERS)
    for child in files.iterdir():
        child.unlink()
    files.rmdir()  # a concurrent prune got there first
    monkeypatch.setattr(prune, "plan", lambda inbox, parsers: planned)
    result = prune.run(engine, inbox, PARSERS, T0)
    assert result.removed == [] and result.problems == []


def test_a_planned_path_outside_the_folder_is_refused(engine, tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    page(inbox / "processed", "a")
    elsewhere = page(tmp_path / "other", "x")
    planned = [prune.Companion(elsewhere, inbox / "processed" / "a.html", 0)]
    monkeypatch.setattr(prune, "plan", lambda inbox, parsers: planned)
    result = prune.run(engine, inbox, PARSERS, T0)
    assert result.removed == [] and [p for p, _ in result.problems] == [elsewhere]
    assert elsewhere.exists()


def test_stopping_ends_the_prune_between_companions(engine, tmp_path):
    inbox = tmp_path / "inbox"
    page(inbox / "processed", "a")
    page(inbox / "processed", "b")
    stop = threading.Event()
    result = prune.run(engine, inbox, PARSERS, T0, stop=stop, on_companion=lambda c, problem: stop.set())
    assert len(result.removed) == 1 and result.stopped
    assert len(records(engine)) == 1


def test_no_other_data_changes(engine, tmp_path):
    job_id = add_posting(engine)
    with engine.begin() as conn:
        set_notes(conn, job_id, "Worth a look")
        add_tag(conn, job_id, "backend")
    inbox = tmp_path / "inbox"
    page(inbox / "processed", "a")

    def counts():
        tables = (db.postings, db.captures, db.posting_snapshots, *db.USER_TABLES, *db.DERIVED_TABLES)
        with engine.connect() as conn:
            return {t.name: conn.execute(select(func.count()).select_from(t)).scalar_one() for t in tables}

    before = counts()
    prune.run(engine, inbox, PARSERS, T0)
    assert counts() == before


# --- The schedule ---


def pruner(engine, inbox, clock=lambda: T0):
    return prune.Pruner(engine, inbox, PARSERS, clock=clock)


def test_first_start_after_upgrading_prunes_at_once(engine, tmp_path, capsys):
    inbox = tmp_path / "inbox"
    page(inbox / "processed", "a")
    result = pruner(engine, inbox).run_once(T0)
    assert result is not None and len(result.removed) == 1
    assert len(records(engine)) == 1
    assert capsys.readouterr().out == "jobhunt: pruned inbox: 1 companion, 2.0 KB removed, 0 problems\n"


def test_restarted_within_a_day_waits_for_the_rest_of_it(engine, tmp_path):
    inbox = tmp_path / "inbox"
    prune.run(engine, inbox, PARSERS, T0)
    p = pruner(engine, inbox)
    start = T0 + timedelta(hours=3)
    assert p.run_once(start) is None
    assert p.wait_after(start) == prune.MAX_WAIT  # checks again hourly
    assert p.run_once(T0 + timedelta(hours=23, minutes=59)) is None
    assert p.run_once(T0 + timedelta(hours=24, seconds=1)) is not None
    assert len(records(engine)) == 2


def test_running_for_days_prunes_about_daily(engine, tmp_path):
    inbox = tmp_path / "inbox"
    p = pruner(engine, inbox)
    now, prunes = T0, []
    while now < T0 + timedelta(days=3, minutes=1):
        if p.run_once(now) is not None:
            prunes.append(now)
        now += p.wait_after(now) or timedelta(seconds=1)
    assert len(prunes) == 4  # at start-up, then three more
    gaps = [b - a for a, b in zip(prunes, prunes[1:], strict=False)]
    assert all(timedelta(hours=24) <= g < timedelta(hours=24, minutes=1) for g in gaps)


def test_a_prune_by_hand_pushes_the_next_one_back(engine, tmp_path):
    inbox = tmp_path / "inbox"
    p = pruner(engine, inbox)
    p.run_once(T0)
    prune.run(engine, inbox, PARSERS, T0 + timedelta(hours=10))
    assert p.run_once(T0 + timedelta(hours=25)) is None


def test_the_schedule_is_per_inbox(engine, tmp_path):
    prune.run(engine, tmp_path / "one", PARSERS, T0)
    assert pruner(engine, tmp_path / "two").run_once(T0 + timedelta(hours=1)) is not None
    with engine.connect() as conn:
        assert prune.latest(conn, tmp_path / "one").started_at == T0
        assert prune.latest(conn, tmp_path / "three") is None


def test_stop_ends_the_thread_promptly(engine, tmp_path):
    p = pruner(engine, tmp_path / "inbox", clock=lambda: datetime.now(UTC))
    p.start()
    deadline = datetime.now(UTC) + timedelta(seconds=5)
    while not records(engine) and datetime.now(UTC) < deadline:
        threading.Event().wait(0.01)
    p.stop()
    p.join(timeout=2)
    assert not p.is_alive()
    assert len(records(engine)) == 1  # the start-up prune, then waiting


def test_an_unexpected_error_is_logged_and_retried_later(engine, tmp_path, monkeypatch, caplog):
    p = pruner(engine, tmp_path / "inbox", clock=lambda: datetime.now(UTC))
    waits = []

    def boom(now):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(p, "run_once", boom)
    monkeypatch.setattr(p._stop_event, "wait", lambda seconds: (waits.append(seconds), p.stop()))
    p.run()
    assert waits == [prune.MAX_WAIT.total_seconds()]
    assert "inbox prune failed" in caplog.text
