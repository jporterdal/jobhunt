import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import MetaData, insert, inspect, select
from sqlalchemy import text as sa_text

from jobhunt import db, migrate
from jobhunt.cli import main
from jobhunt.db import captures, init_db, posting_snapshots, postings

from .conftest import add_posting

CAPTURED = (postings, captures, posting_snapshots)


def schema_diff(engine, target: MetaData) -> list:
    with engine.connect() as conn:
        return compare_metadata(MigrationContext.configure(conn), target)


def test_head_matches_metadata(engine):
    assert migrate.current_revision(engine) == migrate.head_revision() == "0012"
    assert schema_diff(engine, db.metadata) == []


def test_every_table_has_one_data_kind():
    kinds = [t.name for t in CAPTURED + db.USER_TABLES + db.DERIVED_TABLES + db.OPERATIONAL_TABLES]
    assert sorted(kinds) == sorted(db.metadata.tables)  # each table listed once, none left out
    assert {
        "records",
        "claims",
        "highlights",
        "skill_aliases",
        "profile_rejections",
        "tailored_cvs",
        "tailored_cv_items",
    } <= {t.name for t in db.USER_TABLES}
    assert "profile_suggestions" in {t.name for t in db.DERIVED_TABLES}


def test_init_db_is_repeatable(engine):
    head = migrate.current_revision(engine)
    init_db(engine)
    assert migrate.current_revision(engine) == head


def test_user_data_seeds_dismiss_reasons(engine):
    with engine.connect() as conn:
        labels = (
            conn.execute(select(db.dismiss_reasons.c.label).order_by(db.dismiss_reasons.c.position)).scalars().all()
        )
    assert labels == [
        "Too senior",
        "Too junior",
        "Location or on-site",
        "Compensation",
        "Wrong domain",
        "Skills mismatch",
        "Company",
        "Other",
    ]


def test_downgrade_and_upgrade_again(engine):
    migrate.downgrade(engine, "base")
    assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
    init_db(engine)
    assert schema_diff(engine, db.metadata) == []


def test_inbox_prunes_downgrade_and_upgrade_again(engine):
    migrate.downgrade(engine, migrate.BASELINE)
    assert "inbox_prunes" not in inspect(engine).get_table_names()
    assert "postings" in inspect(engine).get_table_names()
    init_db(engine)
    assert schema_diff(engine, db.metadata) == []


START = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)


def labelled_before_0012(engine, firsts, start=None, cleared=False) -> list[int]:
    """Postings with labelling first flagged at `firsts` (None: never; `cleared`: the flag since cleared), on a
    database taken back to 0011, with the held-out start `start` recorded; returns their keys."""
    jobs = [add_posting(engine, tag=str(i), external_id=str(9000000100 + i)) for i in range(len(firsts))]
    with engine.begin() as conn:
        for job, first in zip(jobs, firsts, strict=True):
            conn.execute(
                insert(db.posting_triage).values(
                    job_id=job,
                    updated_at=START,
                    skills_complete_at=None if cleared else first,
                    skills_first_complete_at=first,
                )
            )
    migrate.downgrade(engine, "0011")
    assert "eval_set" not in {c["name"] for c in inspect(engine).get_columns("posting_triage")}
    if start is not None:
        with engine.begin() as conn:
            conn.execute(
                insert(db.app_settings).values(key="eval.holdout_start", value=start.isoformat(), updated_at=START)
            )
    init_db(engine)
    return jobs


def eval_sets(engine, jobs) -> list:
    with engine.connect() as conn:
        rows = {r.job_id: (r.eval_set, r.eval_set_origin) for r in conn.execute(select(db.posting_triage)).all()}
    return [rows.get(job, (None, None)) for job in jobs]


def holdout_start_row(engine):
    with engine.connect() as conn:
        return conn.execute(select(db.app_settings).where(db.app_settings.c.key == "eval.holdout_start")).first()


def test_upgrading_with_no_held_out_start(engine):
    jobs = labelled_before_0012(engine, [START + timedelta(minutes=i) for i in range(9)])
    assert eval_sets(engine, jobs) == [("dev", "before-random")] * 9
    assert schema_diff(engine, db.metadata) == []


def test_upgrading_with_a_held_out_start(engine):
    before = [START - timedelta(hours=i + 1) for i in range(9)]
    after = [START + timedelta(hours=1), START + timedelta(days=2)]
    jobs = labelled_before_0012(engine, before + after + [None], start=START)
    assert eval_sets(engine, jobs) == [("dev", "before-random")] * 9 + [("holdout", "before-random")] * 2 + [
        (None, None)  # never flagged: no set until its first flagging
    ]
    assert holdout_start_row(engine) is None


def test_upgrading_a_posting_flagged_then_cleared(engine):
    jobs = labelled_before_0012(engine, [START - timedelta(1), START + timedelta(1)], start=START, cleared=True)
    assert eval_sets(engine, jobs) == [("dev", "before-random"), ("holdout", "before-random")]


def test_eval_sets_downgrade_and_upgrade_again(engine):
    jobs = labelled_before_0012(engine, [START])
    migrate.downgrade(engine, "0011")
    assert "eval_set" not in {c["name"] for c in inspect(engine).get_columns("posting_triage")}
    assert holdout_start_row(engine) is None  # the start isn't restored
    init_db(engine)
    assert eval_sets(engine, jobs) == [("dev", "before-random")]
    assert schema_diff(engine, db.metadata) == []


def snapshot(engine) -> dict:
    """Every table's rows, to show a refused database is left unchanged."""
    with engine.connect() as conn:
        names = sorted(inspect(conn).get_table_names())
        return {n: conn.execute(sa_text(f"SELECT * FROM {n}")).all() for n in names}


def test_pre_versioning_database_is_refused(empty_engine):
    # What the first release left behind: the captured tables from create_all(), with no schema version.
    with empty_engine.begin() as conn:
        conn.execute(sa_text("CREATE TABLE postings (job_id VARCHAR(32) PRIMARY KEY, url TEXT NOT NULL)"))
        conn.execute(sa_text("INSERT INTO postings VALUES ('1042', 'https://jobs.example.com/1042')"))
    before = snapshot(empty_engine)
    with pytest.raises(migrate.TooOld, match="tables but no schema version.*predates the baseline"):
        init_db(empty_engine)
    assert snapshot(empty_engine) == before


def test_database_older_than_the_baseline_is_refused(empty_engine):
    with empty_engine.begin() as conn:
        conn.execute(sa_text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"))
        conn.execute(sa_text("INSERT INTO alembic_version VALUES ('0008_knowledge_base')"))
        conn.execute(sa_text("CREATE TABLE postings (job_id VARCHAR(32) PRIMARY KEY, url TEXT NOT NULL)"))
    before = snapshot(empty_engine)
    with pytest.raises(migrate.TooOld, match="schema version 0008_knowledge_base, which predates the baseline"):
        init_db(empty_engine)
    assert snapshot(empty_engine) == before


def test_cli_refuses_an_old_database_with_exit_2(tmp_path, capsys):
    path = tmp_path / "old.db"
    engine = db.make_engine(f"sqlite:///{path}")
    with engine.begin() as conn:
        conn.execute(sa_text("CREATE TABLE postings (job_id VARCHAR(32) PRIMARY KEY, url TEXT NOT NULL)"))
    engine.dispose()
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    (tmp_path / "inbox").mkdir()
    (tmp_path / "inbox" / "a.json").write_text("{}")

    assert main(["import", "--inbox", str(tmp_path / "inbox"), "--db", f"sqlite:///{path}"]) == 2
    err = capsys.readouterr().err
    assert "predates the baseline" in err and "release from before the baseline" in err
    assert hashlib.sha256(path.read_bytes()).hexdigest() == checksum
    assert (tmp_path / "inbox" / "a.json").exists()  # nothing was imported or moved
