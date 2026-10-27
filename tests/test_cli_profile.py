"""`jobhunt profile reset` on a copy of a database with a profile."""

import sqlalchemy as sa

from jobhunt import db, userdata
from jobhunt.cli import main

KEPT = (db.profile_details, db.skill_aliases, db.profile_rejections, db.skill_link_overrides)
RESET = (
    db.records,
    db.record_lines,
    db.record_sources,
    db.claims,
    db.claim_records,
    db.highlights,
    db.highlight_claims,
)


def profile_copy(tmp_path):
    """A database with records (lines, a source, a context link), claims with grounds, highlights with coverage,
    an alias, details, a remembered rejection and link overrides."""
    url = f"sqlite:///{tmp_path / 'copy.db'}"
    engine = db.make_engine(url)
    db.init_db(engine)
    with engine.begin() as conn:
        project = userdata.add_record(conn, {"kind": "project", "title": "jobhunt"})
        userdata.add_line(conn, project, "jobhunt, in Python")
        userdata.add_source(conn, project, "https://github.com/x/jobhunt")
        userdata.set_part_of(conn, project, userdata.add_record(conn, {"kind": "other", "title": "Side work"}))
        userdata.add_record(conn, {"kind": "degree", "title": "PhD", "organisation": "Example University"})
        python = userdata.add_profile_skill(conn, "Python", "proficient")
        sql = userdata.add_profile_skill(conn, "SQL", "familiar")
        userdata.add_ground(conn, python, project, "Python")
        userdata.add_coverage(conn, userdata.add_highlight(conn, "8+ years with Python"), python, "Python")
        userdata.add_highlight(conn, "Data modelling with SQL")
        userdata.merge_skill(conn, userdata.add_profile_skill(conn, "Python 3", "familiar"), python)  # an alias
        userdata.add_detail(conn, "name", "Jane Doe")
        userdata.add_detail(conn, "headline", "Data engineer")
        userdata.delete_line(conn, userdata.add_line(conn, project, "an old line"))  # remembered
        userdata.set_link_override(conn, "Python 3", python, "same")
        userdata.set_link_override(conn, "Databases", sql, "general")
    return url, engine, python


def count(engine, table) -> int:
    with engine.connect() as conn:
        return conn.execute(sa.select(sa.func.count()).select_from(table)).scalar_one()


def test_resetting_a_copy(tmp_path, capsys):
    url, engine, python = profile_copy(tmp_path)
    kept = {t.name: count(engine, t) for t in KEPT}
    assert (count(engine, db.records), count(engine, db.claims), count(engine, db.highlights)) == (3, 2, 2)
    assert all(kept.values()), kept

    assert main(["profile", "reset", "--db", url, "--yes"]) == 0

    out = capsys.readouterr().out
    assert "Deleted 3 records, 2 claims and 2 highlights" in out
    for table in RESET:
        assert count(engine, table) == 0, table.name
    assert {t.name: count(engine, t) for t in KEPT} == kept
    with engine.connect() as conn:
        assert conn.execute(sa.select(db.skill_link_overrides.c.skill_id).where(
            db.skill_link_overrides.c.posting_key == "python 3")).scalar_one() == python
    engine.dispose()


def test_no_confirmation(tmp_path, capsys):
    url, engine, _ = profile_copy(tmp_path)
    assert main(["profile", "reset", "--db", url]) == 2
    assert "--yes" in capsys.readouterr().err
    assert (count(engine, db.records), count(engine, db.claims), count(engine, db.highlights)) == (3, 2, 2)
    engine.dispose()
