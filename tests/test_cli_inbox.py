import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from jobhunt import db, prune
from jobhunt.cli import build_parser, main
from jobhunt.parsers import Installed

from .fakes import FakeParser
from .test_prune import PARSERS, page


@pytest.fixture(autouse=True)
def parsers(monkeypatch):
    """The installed parsers: the built-in one and a saved-page parser marking `<stem>_files` discardable."""
    monkeypatch.setattr("jobhunt.parsers.installed", lambda: Installed(tuple(PARSERS)))


def prune_cli(tmp_path, *extra):
    return main(["inbox", "prune", "--inbox", str(tmp_path / "inbox"), "--db", f"sqlite:///{tmp_path / 'x.db'}",
                 *extra])


def recorded(tmp_path):
    engine = db.make_engine(f"sqlite:///{tmp_path / 'x.db'}")
    try:
        db.init_db(engine)
        with engine.connect() as conn:
            return conn.execute(select(db.inbox_prunes)).all()
    finally:
        engine.dispose()


def test_defaults_are_the_import_commands(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBHUNT_DB_URL", "sqlite:///x.db")
    monkeypatch.setenv("JOBHUNT_INBOX", str(tmp_path / "in"))
    pruning = build_parser().parse_args(["inbox", "prune"])
    imp = build_parser().parse_args(["import"])
    assert (pruning.db, pruning.inbox, pruning.dry_run) == (imp.db, imp.inbox, False)


def test_dry_run_lists_and_keeps_everything(tmp_path, capsys):
    inbox = tmp_path / "inbox"
    page(inbox / "processed", "a", assets=1, size=2048)
    page(inbox / "rejected", "b", assets=1, size=1024)
    assert prune_cli(tmp_path, "--dry-run") == 0
    out = capsys.readouterr().out.splitlines()
    assert out == [
        "would remove  processed/a_files  2.0 KB",
        "would remove  rejected/b_files  1.0 KB",
        "Totals: 2 companions, 3.0 KB would be removed, 0 problems",
    ]
    assert (inbox / "processed" / "a_files").exists() and (inbox / "rejected" / "b_files").exists()
    assert not (tmp_path / "x.db").exists()  # a dry run doesn't open the database


def test_a_prune_removes_and_records(tmp_path, capsys):
    page(tmp_path / "inbox" / "processed", "a", assets=1, size=100)
    assert prune_cli(tmp_path) == 0
    out = capsys.readouterr().out.splitlines()
    assert out == ["removed  processed/a_files  100 bytes", "Totals: 1 companion, 100 bytes removed, 0 problems"]
    assert not (tmp_path / "inbox" / "processed" / "a_files").exists()
    [row] = recorded(tmp_path)
    assert (row.removed, row.bytes) == (1, 100)


def test_pruning_by_hand_resets_the_schedule(tmp_path):
    page(tmp_path / "inbox" / "processed", "a")
    assert prune_cli(tmp_path) == 0
    engine = db.make_engine(f"sqlite:///{tmp_path / 'x.db'}")
    try:
        later = datetime.now(UTC) + timedelta(hours=1)
        assert prune.Pruner(engine, tmp_path / "inbox", PARSERS).run_once(later) is None
    finally:
        engine.dispose()
    assert len(recorded(tmp_path)) == 1


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignores permissions")
def test_problems_exit_1(tmp_path, capsys):
    locked = page(tmp_path / "inbox" / "processed", "a")
    locked.chmod(0o500)
    try:
        assert prune_cli(tmp_path) == 1
    finally:
        locked.chmod(0o700)
    out = capsys.readouterr().out
    assert "problem  processed/a_files: " in out and "Totals: 0 companions, 0 bytes removed, 1 problem" in out
    [row] = recorded(tmp_path)
    assert row.problems == 1


def test_no_inbox_exits_2(tmp_path, capsys):
    assert prune_cli(tmp_path) == 2
    assert "inbox folder not found" in capsys.readouterr().err
    assert not (tmp_path / "x.db").exists()


def test_parser_load_errors_are_warnings(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        "jobhunt.parsers.installed", lambda: Installed((FakeParser(),), ("parser 'broken' failed to load",))
    )
    (tmp_path / "inbox").mkdir()
    assert prune_cli(tmp_path, "--dry-run") == 0
    assert capsys.readouterr().out.splitlines()[0] == "warning: parser 'broken' failed to load"
