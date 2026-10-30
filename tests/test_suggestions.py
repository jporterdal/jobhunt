"""Settings, mark importance and origin, the labelled flag, rejections, accepting suggestions, and the
derived-data writer."""

import json
import math

import pytest
from sqlalchemy import select

from jobhunt import queries, userdata
from jobhunt.db import (
    app_settings,
    enrichment_salaries,
    enrichment_skills,
    posting_enrichments,
    posting_skill_marks,
    posting_triage,
    rejected_suggestions,
    skills,
)
from jobhunt.enrich.pipeline import SalaryItem
from jobhunt.userdata import UserDataError

from .conftest import add_posting, add_run
from .test_userdata import JOB, OTHER, T1, T2, T3, all_rows, count, write


@pytest.fixture
def db(engine):
    add_posting(engine)
    add_posting(engine, "senior-ai-engineer.json")
    return engine


def marks(engine):
    with engine.connect() as conn:
        return conn.execute(
            select(
                skills.c.name,
                posting_skill_marks.c.quote,
                posting_skill_marks.c.importance,
                posting_skill_marks.c.origin,
            )
            .join(skills, skills.c.id == posting_skill_marks.c.skill_id)
            .order_by(posting_skill_marks.c.id)
        ).all()


def suggestion_id(engine, name, run_id=None):
    with engine.connect() as conn:
        query = select(enrichment_skills.c.id).where(enrichment_skills.c.name == name)
        if run_id is not None:
            query = query.where(enrichment_skills.c.enrichment_id == run_id)
        return conn.execute(query).scalar_one()


RUN_SKILLS = [
    ("Data lineage", "required", "data lineage"),
    ("Data governance", "required", "data governance"),
    ("LangChain", "preferred", "LangChain"),
    ("Kubernetes", "required", "Kubernetes clusters"),  # not in the text: unverified
]


# --- Settings (2.1) ---


def test_settings_defaults(db):
    with db.connect() as conn:
        assert userdata.settings(conn) == {
            "llm.model": None,
            "llm.num_ctx": 8192,
            "llm.segmenter": "llm-lines",
            "llm.embed_model": None,
            "eval.holdout_share": 0.5,
            "demo.created_at": None,
        }


def test_settings_round_trip(db):
    write(db, userdata.set_setting, "llm.model", " gemma4:12b ")
    write(db, userdata.set_setting, "llm.num_ctx", "16384")
    write(db, userdata.set_setting, "llm.segmenter", "rules")
    write(db, userdata.set_setting, "llm.num_ctx", 4096, now=T2)
    with db.connect() as conn:
        assert userdata.settings(conn) == {
            "llm.model": "gemma4:12b",
            "llm.num_ctx": 4096,
            "llm.segmenter": "rules",
            "llm.embed_model": None,
            "eval.holdout_share": 0.5,
            "demo.created_at": None,
        }
    assert count(db, app_settings) == 3


def test_demo_marker(db):
    write(db, userdata.set_setting, "demo.created_at", T2)
    with db.connect() as conn:
        assert userdata.get_setting(conn, "demo.created_at") == T2
    with pytest.raises(userdata.UserDataError, match="time zone"):
        write(db, userdata.set_setting, "demo.created_at", T2.replace(tzinfo=None))


def test_holdout_share_set(db):
    write(db, userdata.set_setting, "eval.holdout_share", "0.3")
    with db.connect() as conn:
        assert userdata.get_setting(conn, "eval.holdout_share") == 0.3
    for share in (0.1, 0.9):
        write(db, userdata.set_setting, "eval.holdout_share", share)
        with db.connect() as conn:
            assert userdata.get_setting(conn, "eval.holdout_share") == share


def test_holdout_share_out_of_range(db):
    write(db, userdata.set_setting, "eval.holdout_share", 0.4)
    with pytest.raises(UserDataError, match="from 0.1 to 0.9"):
        write(db, userdata.set_setting, "eval.holdout_share", 0.95)
    with db.connect() as conn:
        assert userdata.get_setting(conn, "eval.holdout_share") == 0.4


@pytest.mark.parametrize(
    "key, value",
    [
        ("llm.model", "  "),
        ("llm.num_ctx", "lots"),
        ("llm.num_ctx", 1024),
        ("llm.num_ctx", 200000),
        ("llm.segmenter", "magic"),
        ("llm.skills", "atomic@2"),  # the code names the skill extraction method
        ("eval.holdout_share", 0.95),
        ("eval.holdout_share", 0.05),
        ("eval.holdout_share", "abc"),
        ("eval.holdout_share", "nan"),
        ("eval.holdout_start", "2026-10-03T09:00:00+00:00"),  # replaced by the share
        ("llm.temperature", "1"),
    ],
)
def test_settings_rejected(db, key, value):
    with pytest.raises(UserDataError):
        write(db, userdata.set_setting, key, value)
    assert count(db, app_settings) == 0


# --- Mark importance and origin (2.2) ---


def test_marking_with_and_without_importance(db):
    write(db, userdata.add_skill_mark, JOB, "Data lineage", "data lineage", importance="required")
    write(db, userdata.add_skill_mark, JOB, "LangChain", "LangChain")
    assert marks(db) == [
        ("Data lineage", "data lineage", "required", "selection"),
        ("LangChain", "LangChain", None, "selection"),
    ]


def test_changing_importance_keeps_quote_and_origin(db):
    mark_id = write(db, userdata.add_skill_mark, JOB, "PyTorch", "Design", origin="suggestion")
    write(db, userdata.set_mark_importance, mark_id, "required")
    assert marks(db) == [("PyTorch", "Design", "required", "suggestion")]
    write(db, userdata.set_mark_importance, mark_id, None)
    assert marks(db)[0].importance is None


@pytest.mark.parametrize("kwargs", [{"importance": "essential"}, {"origin": "model"}])
def test_invalid_mark_values(db, kwargs):
    with pytest.raises(UserDataError):
        write(db, userdata.add_skill_mark, JOB, "PyTorch", "Design", **kwargs)
    mark_id = write(db, userdata.add_skill_mark, JOB, "PyTorch", "Design")
    with pytest.raises(UserDataError):
        write(db, userdata.set_mark_importance, mark_id, "essential")


# --- Labelling complete (2.3) ---


def test_skills_complete_set_and_clear(db):
    write(db, userdata.set_rating, JOB, "interest", 4)
    write(db, userdata.set_skills_complete, JOB, True, now=T1)
    [row] = all_rows(db, posting_triage)
    assert row.skills_complete_at == T1 and row.interest == 4
    write(db, userdata.set_skills_complete, JOB, False, now=T2)
    [row] = all_rows(db, posting_triage)
    assert row.skills_complete_at is None and row.interest == 4


def test_skills_first_complete_is_kept(db):
    write(db, userdata.set_skills_complete, JOB, True, now=T1)
    write(db, userdata.set_skills_complete, JOB, False, now=T2)
    [row] = all_rows(db, posting_triage)
    assert row.skills_first_complete_at == T1
    write(db, userdata.set_skills_complete, JOB, True, now=T3)
    [row] = all_rows(db, posting_triage)
    assert (row.skills_complete_at, row.skills_first_complete_at) == (T3, T1)


def test_skills_complete_unknown_posting(db):
    with pytest.raises(UserDataError):
        write(db, userdata.set_skills_complete, 123, True)


# --- Eval sets ---


@pytest.mark.parametrize(
    "share, labelled, holdout, p",
    [(0.5, 10, 5, 0.5), (0.5, 9, 0, 0.989), (0.3, 10, 2, 0.538), (0.5, 0, 0, 0.5)],
)
def test_holdout_probability(share, labelled, holdout, p):
    assert userdata.holdout_probability(share, labelled, holdout) == pytest.approx(p, abs=0.0005)


def test_holdout_probability_odds_multiply_by_e():
    def odds(holdout):
        p = userdata.holdout_probability(0.5, 10, holdout)
        return p / (1 - p)

    for holdout in range(10):
        assert odds(holdout) / odds(holdout + 1) == pytest.approx(math.e)  # one posting short: e times the odds


def eval_set(engine, job_id):
    with engine.connect() as conn:
        row = conn.execute(select(posting_triage).where(posting_triage.c.job_id == job_id)).first()
    return (row.eval_set, row.eval_set_origin) if row else (None, None)


def never():
    raise AssertionError("no draw expected")


@pytest.mark.parametrize("draw, expected", [(0.2, "holdout"), (0.8, "dev")])
def test_drawing_a_set(db, draw, expected):
    # No posting labelled yet: P is the share, 0.5.
    write(db, userdata.set_skills_complete, JOB, True, now=T1, draw=lambda: draw)
    assert eval_set(db, JOB) == (expected, "drawn")
    [row] = all_rows(db, posting_triage)
    assert row.skills_first_complete_at == T1


@pytest.mark.parametrize("choice", ["dev", "holdout"])
def test_choosing_a_set(db, choice):
    write(db, userdata.set_skills_complete, JOB, True, choice=choice, draw=never)
    assert eval_set(db, JOB) == (choice, "chosen")


def test_unknown_choice_refused(db):
    with pytest.raises(UserDataError, match="auto, dev, holdout"):
        write(db, userdata.set_skills_complete, JOB, True, choice="test")
    assert all_rows(db, posting_triage) == []


def test_reflagging_keeps_the_set(db):
    write(db, userdata.set_skills_complete, JOB, True, now=T1, draw=lambda: 0.1)
    write(db, userdata.set_skills_complete, JOB, False, now=T2)
    assert eval_set(db, JOB) == ("holdout", "drawn")
    write(db, userdata.add_skill_mark, JOB, "Data lineage", "data lineage")
    write(db, userdata.set_skills_complete, JOB, True, now=T3, choice="dev", draw=never)
    assert eval_set(db, JOB) == ("holdout", "drawn")


def test_clearing_before_a_set_draws_nothing(db):
    write(db, userdata.set_skills_complete, JOB, False, draw=never)
    assert eval_set(db, JOB) == (None, None)


def test_draw_counts_only_flagged_postings(db):
    third = add_posting(db, tag="3", external_id="9000000003")
    write(db, userdata.set_skills_complete, JOB, True, choice="holdout")
    write(db, userdata.set_skills_complete, OTHER, True, choice="holdout")
    write(db, userdata.set_skills_complete, OTHER, False)
    # Counted: JOB only (1 labelled, 1 holdout), so P = 1 / (1 + e^0.5) = 0.378; counting OTHER too, 0.269.
    write(db, userdata.set_skills_complete, third, True, draw=lambda: 0.3)
    assert eval_set(db, third) == ("holdout", "drawn")  # 0.3 < 0.378; with OTHER counted it would be dev


def test_draw_uses_the_share(db):
    write(db, userdata.set_setting, "eval.holdout_share", 0.3)
    write(db, userdata.set_skills_complete, JOB, True, draw=lambda: 0.31)  # P = 0.3
    assert eval_set(db, JOB) == ("dev", "drawn")


def test_moving_to_dev(db):
    write(db, userdata.set_skills_complete, JOB, True, choice="holdout")
    write(db, userdata.set_skills_complete, JOB, False)
    write(db, userdata.move_eval_set, JOB, "dev")  # while the flag is cleared
    assert eval_set(db, JOB) == ("dev", "moved")


def test_moving_dev_to_dev_changes_nothing(db):
    write(db, userdata.set_skills_complete, JOB, True, now=T1, draw=lambda: 0.9)
    write(db, userdata.move_eval_set, JOB, "dev", now=T3)
    assert eval_set(db, JOB) == ("dev", "drawn")
    [row] = all_rows(db, posting_triage)
    assert row.updated_at == T1


def test_dev_to_holdout_refused(db):
    write(db, userdata.set_skills_complete, JOB, True, choice="dev")
    with pytest.raises(UserDataError, match="prompts may have been tuned on it"):
        write(db, userdata.move_eval_set, JOB, "holdout")
    assert eval_set(db, JOB) == ("dev", "chosen")


@pytest.mark.parametrize("job_id", [JOB, 123])  # JOB is never flagged; 123 isn't a posting
def test_moving_without_a_set_refused(db, job_id):
    with pytest.raises(UserDataError, match="isn't in an eval set"):
        write(db, userdata.move_eval_set, job_id, "dev")


def test_moving_to_an_unknown_set_refused(db):
    write(db, userdata.set_skills_complete, JOB, True, choice="holdout")
    with pytest.raises(UserDataError):
        write(db, userdata.move_eval_set, JOB, "test")
    assert eval_set(db, JOB) == ("holdout", "chosen")


# --- Rejections (2.4) ---


def test_reject_is_idempotent_and_case_insensitive(db):
    write(db, userdata.reject_suggestion, JOB, "Communication", "not-a-skill")
    write(db, userdata.reject_suggestion, JOB, "  communication ", "not-for-me")
    assert [(r.job_id, r.skill_key, r.reason) for r in all_rows(db, rejected_suggestions)] == [
        (JOB, "communication", "not-for-me")
    ]
    write(db, userdata.unreject_suggestion, JOB, "COMMUNICATION")
    write(db, userdata.unreject_suggestion, JOB, "Communication")
    assert count(db, rejected_suggestions) == 0


def test_reject_needs_a_known_reason(db):
    with pytest.raises(UserDataError):
        write(db, userdata.reject_suggestion, JOB, "Cursor", "boring")
    assert count(db, rejected_suggestions) == 0


def test_reason_set_on_earlier_rejection(db):
    with db.begin() as conn:  # rejected before reasons existed
        conn.execute(rejected_suggestions.insert().values(job_id=JOB, skill_key="ray", created_at=T1))
    write(db, userdata.set_rejection_reason, JOB, "Ray", "not-for-me")
    [row] = all_rows(db, rejected_suggestions)
    assert (row.skill_key, row.reason, row.created_at) == ("ray", "not-for-me", T1)
    with pytest.raises(UserDataError):
        write(db, userdata.set_rejection_reason, JOB, "Ray", "meh")
    with pytest.raises(UserDataError):
        write(db, userdata.set_rejection_reason, JOB, "Cursor", "not-for-me")
    with pytest.raises(UserDataError):
        write(db, userdata.set_rejection_reason, OTHER, "Ray", "not-for-me")
    assert [r.reason for r in all_rows(db, rejected_suggestions)] == ["not-for-me"]


# --- Derived writer (6.1) ---


def test_save_run_round_trip(db):
    run_id = add_run(
        db,
        skills=RUN_SKILLS,
        salaries=[SalaryItem(1000, 2000, "USD", "year", None, "base", "invented $1,000")],
        segments=[(0, 15, "other")],
    )
    with db.connect() as conn:
        run = conn.execute(select(posting_enrichments)).one()
        items = conn.execute(select(enrichment_skills).order_by(enrichment_skills.c.position)).all()
        [pay] = conn.execute(select(enrichment_salaries)).all()
    assert (run.id, run.job_id, run.model, run.status, run.error) == (run_id, JOB, "gemma4:12b", "succeeded", None)
    assert json.loads(run.output_json)["segments"] == [[0, 15, "other"]]
    assert [(i.name, i.key, i.importance, i.verified) for i in items] == [
        ("Data lineage", "data lineage", "required", True),
        ("Data governance", "data governance", "required", True),
        ("LangChain", "langchain", "preferred", True),
        ("Kubernetes", "kubernetes", "required", False),
    ]
    assert items[0].start_offset is not None and items[3].start_offset is None
    assert (pay.min_amount, pay.max_amount, pay.currency, pay.verified) == (1000, 2000, "USD", False)


def test_failed_run_stored_with_error(db):
    add_run(db, status="failed", error="skills: no skills were extracted from the required lines")
    [run] = all_rows(db, posting_enrichments)
    assert run.status == "failed" and run.error.startswith("skills:")
    assert count(db, enrichment_skills) == 0


def test_second_run_leaves_first_unchanged(db):
    add_run(db, skills=RUN_SKILLS[:1])
    before = all_rows(db, posting_enrichments), all_rows(db, enrichment_skills)
    add_run(db, skills=RUN_SKILLS[1:], model="phi4:latest")
    after_runs, after_items = all_rows(db, posting_enrichments), all_rows(db, enrichment_skills)
    assert after_runs[:1] == before[0] and after_items[:1] == before[1]
    assert len(after_runs) == 2


# --- Accepting (2.5) ---


def test_accept_suggestion_creates_mark(db):
    run_id = add_run(db, skills=RUN_SKILLS)
    write(db, userdata.accept_suggestion, suggestion_id(db, "Data lineage"))
    assert marks(db) == [("Data lineage", "data lineage", "required", "suggestion")]
    with pytest.raises(UserDataError, match="already marks"):
        write(db, userdata.accept_suggestion, suggestion_id(db, "Data lineage", run_id))


def test_accept_matches_existing_skill_case_insensitively(db):
    write(db, userdata.add_skill_mark, OTHER, "langchain", "Python")
    add_run(db, skills=RUN_SKILLS)
    write(db, userdata.accept_suggestion, suggestion_id(db, "LangChain"))
    assert count(db, skills) == 1


def test_accept_quotes_the_description(db):
    add_run(db, skills=[("Automation", "required", "AI–DRIVEN   automation")])
    write(db, userdata.accept_suggestion, suggestion_id(db, "Automation"))
    assert marks(db)[0].quote == "AI-driven automation"


def test_accept_refuses_unverified(db):
    add_run(db, skills=RUN_SKILLS)
    with pytest.raises(UserDataError, match="not in the description"):
        write(db, userdata.accept_suggestion, suggestion_id(db, "Kubernetes"))


def test_accept_refuses_failed_run(db):
    from jobhunt.enrich import derived
    from jobhunt.enrich.pipeline import Checked, RunResult, SkillItem

    with db.begin() as conn:
        from jobhunt.store import latest_snapshot

        snap = latest_snapshot(conn, JOB)
        start = snap.description_text.index("data lineage")
        result = RunResult(
            "failed", "salary: broken", T1, T2, [],
            [Checked(SkillItem("Data lineage", "required", "technical", "data lineage"), True, start, start + 12)],
        )
        derived.save_run(conn, JOB, snap.id, "m", "p", result, "app")
    with pytest.raises(UserDataError, match="failed"):
        write(db, userdata.accept_suggestion, suggestion_id(db, "Data lineage"))


def test_accept_refuses_run_on_older_snapshot(db):
    run_id = add_run(db, skills=RUN_SKILLS)
    add_posting(
        db, tag="v2", description_text="Rewritten. data lineage", description_html="<p>Rewritten. data lineage</p>"
    )
    with pytest.raises(UserDataError, match="older snapshot"):
        write(db, userdata.accept_suggestion, suggestion_id(db, "Data lineage"))
    with pytest.raises(UserDataError, match="older snapshot"):
        write(db, userdata.accept_all, JOB, run_id, "required")
    assert count(db, posting_skill_marks) == 0


def test_eval_run_not_acceptable(db):
    run_id = add_run(db, skills=RUN_SKILLS, origin="eval")
    with pytest.raises(UserDataError, match="not one the app uses"):
        write(db, userdata.accept_suggestion, suggestion_id(db, "Data lineage"))
    with pytest.raises(UserDataError, match="not one the app uses"):
        write(db, userdata.accept_all, JOB, run_id, "required")
    assert count(db, posting_skill_marks) == 0


def test_marks_from_a_run_the_app_no_longer_uses(db):
    run_id = add_run(db, skills=RUN_SKILLS)
    write(db, userdata.accept_all, JOB, run_id, "required")
    write(db, userdata.reject_suggestion, JOB, "LangChain", "not-for-me")
    with db.begin() as conn:  # what the 0007 backfill does to a run no posting job points at
        conn.execute(posting_enrichments.update().where(posting_enrichments.c.id == run_id).values(origin="eval"))
    assert [(m.name, m.origin) for m in marks(db)] == [
        ("Data lineage", "suggestion"),
        ("Data governance", "suggestion"),
    ]
    assert [r.skill_key for r in all_rows(db, rejected_suggestions)] == ["langchain"]
    with db.connect() as conn:
        assert [s["source"] for s in queries.posting_skills(conn, JOB)] == ["mark", "mark"]


def test_accept_all_skips_marked_and_rejected(db):
    run_id = add_run(db, skills=RUN_SKILLS + [("Lineage", "required", "lineage")])
    write(db, userdata.add_skill_mark, JOB, "data governance", "data governance")
    write(db, userdata.reject_suggestion, JOB, "Lineage", "not-a-skill")
    assert write(db, userdata.accept_all, JOB, run_id, "required") == 1
    assert [m.name for m in marks(db)] == ["data governance", "Data lineage"]
    assert write(db, userdata.accept_all, JOB, run_id, "required") == 0
    assert write(db, userdata.accept_all, JOB, run_id, "preferred") == 1
    with pytest.raises(UserDataError):
        write(db, userdata.accept_all, OTHER, run_id, "preferred")
    with pytest.raises(UserDataError):
        write(db, userdata.accept_all, JOB, run_id, "essential")


def test_eval_set_counts(db):
    jobs = [JOB, OTHER] + [add_posting(db, tag=str(i), external_id=str(9000000010 + i)) for i in range(3)]
    write(db, userdata.set_skills_complete, jobs[0], True, draw=lambda: 0.9)  # dev, drawn
    write(db, userdata.set_skills_complete, jobs[1], True, draw=lambda: 0.0)  # holdout, drawn
    write(db, userdata.set_skills_complete, jobs[2], True, choice="holdout")  # holdout, chosen
    write(db, userdata.set_skills_complete, jobs[3], True, choice="holdout")
    write(db, userdata.move_eval_set, jobs[3], "dev")  # dev, moved
    write(db, userdata.set_skills_complete, jobs[4], True, choice="holdout")
    write(db, userdata.set_skills_complete, jobs[4], False)  # unflagged: not counted
    with db.connect() as conn:
        assert queries.eval_set_counts(conn) == {"dev": 2, "holdout": 2, "holdout_not_drawn": 1}
