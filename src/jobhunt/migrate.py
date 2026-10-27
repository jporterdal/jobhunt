"""Run the packaged Alembic migrations in-process; databases older than the baseline are refused."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.util import CommandError
from sqlalchemy import inspect
from sqlalchemy.engine import Connection, Engine

MIGRATIONS = Path(__file__).parent / "migrations"
BASELINE = "0010_baseline"


class TooOld(Exception):
    """The database predates the baseline: tables with no schema version, or a version these revisions don't know."""

    def __init__(self, found: str | None):
        self.found = found
        where = f"at schema version {found}" if found else "with tables but no schema version"
        super().__init__(
            f"the database is {where}, which predates the baseline ({BASELINE}); upgrade it first with a "
            "jobhunt release from before the baseline, then run this again (it was left unchanged)"
        )


def config(conn: Connection | None = None) -> Config:
    # Passing the connection (rather than a URL) keeps a Postgres search_path in effect.
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    cfg.attributes["connection"] = conn
    return cfg


@contextmanager
def migration_connection(engine: Engine) -> Iterator[Connection]:
    """A connection in one transaction for running revisions.

    On SQLite, foreign keys are switched off first (SQLite ignores the pragma inside a transaction), so a revision
    can rebuild a table other tables refer to; every foreign key is then checked before the commit.
    """
    with engine.connect() as conn:
        sqlite = conn.dialect.name == "sqlite"
        if sqlite:
            conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
            conn.commit()
        try:
            with conn.begin():
                yield conn
                if sqlite:
                    broken = conn.exec_driver_sql("PRAGMA foreign_key_check").all()
                    if broken:
                        raise RuntimeError(
                            f"the migration left {len(broken)} rows without their parent row: {broken[:5]}"
                        )
        finally:
            if sqlite:
                conn.exec_driver_sql("PRAGMA foreign_keys=ON")
                conn.commit()


def upgrade(engine: Engine, revision: str = "head") -> None:
    """Bring the schema to `revision`: create it in an empty database, or upgrade one at the baseline or later.
    Raises TooOld, before anything is written, for a database older than the baseline."""
    with migration_connection(engine) as conn:
        cfg = config(conn)
        check_not_too_old(conn)
        command.upgrade(cfg, revision)


def check_not_too_old(conn: Connection) -> None:
    tables = set(inspect(conn).get_table_names()) - {"alembic_version"}
    if not tables:
        return  # empty (or emptied by a downgrade to base): the baseline creates the schema
    found = MigrationContext.configure(conn).get_current_revision()
    if found is None:
        raise TooOld(None)
    try:
        ScriptDirectory.from_config(config()).get_revision(found)
    except CommandError:  # an id these revisions don't know: one squashed into the baseline
        raise TooOld(found) from None


def current_revision(engine: Engine) -> str | None:
    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def head_revision() -> str:
    return ScriptDirectory.from_config(config()).get_current_head()


def downgrade(engine: Engine, revision: str) -> None:
    """Take the schema down to `revision` (development and tests; copy the database first)."""
    with migration_connection(engine) as conn:
        command.downgrade(config(conn), revision)
