import hashlib

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import MetaData, inspect, select
from sqlalchemy import text as sa_text

from jobhunt import db, migrate
from jobhunt.cli import main
from jobhunt.db import captures, init_db, posting_snapshots, postings

CAPTURED = (postings, captures, posting_snapshots)


def schema_diff(engine, target: MetaData) -> list:
    with engine.connect() as conn:
        return compare_metadata(MigrationContext.configure(conn), target)


def test_head_matches_metadata(engine):
    assert migrate.current_revision(engine) == migrate.head_revision() == migrate.BASELINE
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
