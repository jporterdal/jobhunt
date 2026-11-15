"""db.read_only_engine: the database itself refuses writes, and nothing is created."""

import pytest
from sqlalchemy import func, insert, select
from sqlalchemy.exc import DBAPIError

from jobhunt.db import MissingDatabase, read_only_engine, tags

from .conftest import add_posting, read_only_twin


def test_select_works_and_insert_is_refused(engine):
    add_posting(engine)
    ro = read_only_twin(engine)
    try:
        with ro.connect() as conn:
            assert conn.execute(select(func.count()).select_from(tags)).scalar() == 0
        with pytest.raises(DBAPIError), ro.begin() as conn:
            conn.execute(insert(tags).values(name="shortlist"))
    finally:
        ro.dispose()
    with engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(tags)).scalar() == 0


def test_missing_sqlite_file_is_not_created(tmp_path):
    path = tmp_path / "absent" / "jobhunt.db"
    with pytest.raises(MissingDatabase):
        read_only_engine(f"sqlite:///{path}")
    assert not path.exists()
    assert not path.parent.exists()


def test_memory_database_is_refused():
    with pytest.raises(MissingDatabase):
        read_only_engine("sqlite://")
