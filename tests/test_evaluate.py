"""Evaluation: labelled set, matching, metrics and miss attribution, run reuse."""

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from jobhunt import userdata
from jobhunt.db import enrichment_skills, posting_enrichments, rejected_suggestions
from jobhunt.enrich import evaluate
from jobhunt.enrich.evaluate import Counts, Labelled, Mark, Suggestion
from jobhunt.enrich.pipeline import Unreachable

from .conftest import CANDIDATE_SYSTEM, PIPELINE, add_posting, add_run
from .fakes import FakeLLM, label_lines, skill
from .test_userdata import JOB, OTHER, write

TEXT = """Requirements
- Solid experience with PyTorch
- Python and SQL
- MLflow for experiment tracking
- Docker
About the team
- Experience with Airflow is welcome"""


def span(needle):
    start = TEXT.index(needle)
    return start, start + len(needle)


def _line(text, needle):
    for row in text.splitlines():
        if needle in row:
            start = text.index(row)
            return start, start + len(row)


def line(needle):
    return _line(TEXT, needle)


REQUIRED_SEGMENTS = [(*line(n), "required") for n in ("PyTorch", "Python", "MLflow", "Docker")]


def mark(name, quote, importance=None, origin="selection"):
    return Mark(userdata.name_key(name), name, quote, importance, origin)


def suggestion(name, quote, importance="required", rejected=False):
    return Suggestion(userdata.name_key(name), importance, span(quote), rejected)


def scored(marks, suggestions, segments=REQUIRED_SEGMENTS, text=TEXT):
    counts = Counts()
    evaluate.score(counts, Labelled(JOB, "t", 1, text, marks), suggestions, [list(s) for s in segments])
    return counts


# --- Placement ---


def found(text, quote):
    return [text[start:end] for start, end in evaluate.placements(text, quote)]


def test_placement_skips_occurrences_inside_words():
    text = "Our digital platform\n- Git and GitHub"
    assert evaluate.placements(text, "git") == [(text.index("Git"), text.index("Git") + 3)]


def test_placement_of_quotes_ending_in_punctuation():
    text = "Use C#, C++ and .NET; not C#9 (C++17)."
    assert found(text, "C#") == ["C#", "C#"]
    assert found(text, "c++") == ["C++", "C++"]
    assert found(text, ".net") == [".NET"]


def test_placement_at_every_occurrence():
    text = "Python developer\n- Expert-level python"
    assert found(text, "Python") == ["Python", "python"]


def test_partial_word_selection_falls_back_to_substrings():
    assert found("We use Claude Code daily", "Claude Cod") == ["Claude Cod"]


def test_absent_quote_has_no_placement():
    assert evaluate.placements(TEXT, "Kubernetes") == []
    assert evaluate.placements(TEXT, "   ") == []


# --- Matching ---


def test_different_name_same_text_matches():
    marks = [mark("PyTorch", "experience with PyTorch")]
    pairs = evaluate.match([suggestion("PyTorch framework", "PyTorch")], marks, [[span("experience with PyTorch")]])
    assert pairs == [(0, 0)]


def test_key_match_wins_and_each_side_matches_once():
    marks = [mark("Python", "Python"), mark("Python", "Python and SQL")]
    sugg = [suggestion("Python", "Python"), suggestion("SQL", "SQL")]
    places = [[span("Python")], [span("Python and SQL")]]
    assert sorted(evaluate.match(sugg, marks, places)) == [(0, 0), (1, 1)]
    assert evaluate.match([suggestion("Python", "Python")], marks, places) == [(0, 0)]


def test_quote_inside_a_longer_word():
    text = "We build digital products.\nRequirements\n- Git"
    git = text.rindex("Git")
    sugg = [Suggestion("version control", "required", (git, git + 3))]
    c = scored([mark("Git", "Git", "required")], sugg, [(*_line(text, "- Git"), "required")], text)
    assert (c.matched_marks["all"], c.right["all"]) == (1, 1)


def test_suggestion_pairs_with_selected_mark_before_accepted():
    marks = [mark("PyTorch framework", "PyTorch", origin="suggestion"), mark("PyTorch", "experience with PyTorch")]
    places = [[span("PyTorch")], [span("experience with PyTorch")]]
    assert evaluate.match([suggestion("PyTorch framework", "PyTorch")], marks, places) == [(0, 1)]


def test_rejected_suggestion_never_matches():
    counts = scored([mark("Python", "Python")], [suggestion("Python", "Python", rejected=True)])
    assert (counts.right["all"], counts.wrong["all"], counts.unjudged["all"]) == (0, 1, 0)
    assert counts.matched_marks["all"] == 0


def test_recall_four_of_five_and_precision():
    marks = [
        mark("PyTorch", "experience with PyTorch", "required"),
        mark("Python", "Python", "required"),
        mark("SQL", "SQL", "preferred"),
        mark("MLflow", "MLflow"),
        mark("Docker", "Docker", "required"),
    ]
    sugg = [
        suggestion("PyTorch framework", "PyTorch"),
        suggestion("Python", "Python"),
        suggestion("SQL", "SQL"),
        suggestion("MLflow", "MLflow", "preferred"),
        suggestion("Teamwork", "Solid"),
    ]
    c = scored(marks, sugg)
    assert (c.matched_marks["all"], c.marks["all"]) == (4, 5)
    assert (c.matched_marks["required"], c.marks["required"]) == (2, 3)
    assert (c.matched_marks["preferred"], c.marks["preferred"]) == (1, 1)
    assert (c.right["all"], c.wrong["all"], c.unjudged["all"]) == (4, 0, 1)  # Teamwork matches no mark
    assert (c.right["preferred"], c.unjudged["preferred"]) == (1, 0)
    # importance is compared only where the mark has one: PyTorch, Python agree; SQL (preferred vs required) doesn't
    assert (c.importance_agree, c.importance_pairs) == (2, 3)


def test_selected_and_accepted_marks_on_one_posting():
    marks = [
        mark(n, n, "required") for n in ("PyTorch", "Python", "SQL", "MLflow", "Docker", "Solid", "Airflow", "team")
    ]
    marks += [
        mark("FastAPI", "experience", "required", "suggestion"),
        mark("Tracking", "tracking", "preferred", "suggestion"),
    ]
    c = scored(marks, [suggestion("Python", "Python"), suggestion("Tracking", "tracking", "required")])
    assert (c.matched_marks["all"], c.marks["all"]) == (1, 8)
    assert (c.right["all"], c.unjudged["all"]) == (2, 0)
    assert (c.importance_agree, c.importance_pairs) == (1, 1)  # the accepted mark's importance is not compared
    assert c.located == 8 and sum(c.misses.values()) == 7


def test_accepted_suggestion_counts_right_and_leaves_recall_alone():
    marks = [mark("Python", "Python", "required"), mark("FastAPI", "Docker", "required", "suggestion")]
    c = scored(marks, [suggestion("FastAPI", "Docker")])
    assert (c.right["all"], c.matched_marks["all"], c.marks["all"]) == (1, 0, 1)


def test_rejected_and_unjudged_suggestions():
    marks = [mark(n, n) for n in ("PyTorch", "Python", "SQL")]
    sugg = [suggestion(n, n) for n in ("PyTorch", "Python", "SQL")]
    sugg += [
        suggestion("Docker", "Docker", rejected=True),
        suggestion("MLflow", "MLflow"),
        suggestion("Teamwork", "Solid"),
    ]
    c = scored(marks, sugg)
    assert (c.right["all"], c.wrong["all"], c.unjudged["all"]) == (3, 1, 2)
    summary = evaluate._summary(c)
    assert summary["precision"]["all"] == {"count": 3, "of": 4, "ratio": 0.75}
    assert summary["unjudged"]["all"] == 2


# --- Attribution ---


def test_unmatched_marks_attributed_to_one_step():
    marks = [
        mark("Airflow", "Experience with Airflow"),  # on a line labelled other: segmenter miss
        mark("MLflow", "MLflow for experiment tracking"),  # in a required segment, not suggested: extractor miss
        mark("Kafka", "streaming with Kafka"),  # no longer in the description: not located
        mark("Python", "Python"),  # matched
    ]
    c = scored(marks, [suggestion("Python", "Python")])
    assert c.misses == {"segmentation": 1, "extraction": 1, "not_located": 1}
    assert (c.reached, c.located) == (2, 3)  # the unlocated mark is left out of segment recall


def test_reached_at_a_later_occurrence():
    text = "Python Developer\nRequirements\n- Strong Python"
    c = scored([mark("Python", "Python")], [], [(*_line(text, "- Strong"), "required")], text)
    assert c.misses == {"segmentation": 0, "extraction": 1, "not_located": 0}
    assert (c.reached, c.located) == (1, 1)


def test_accepted_marks_are_not_attributed():
    c = scored([mark("Airflow", "Experience with Airflow", origin="suggestion")], [])
    assert c.misses == {"segmentation": 0, "extraction": 0, "not_located": 0} and c.located == 0


# --- The labelled set and evaluate() ---


@pytest.fixture
def db(engine):
    add_posting(engine, description_text=TEXT, description_html="<p>" + TEXT.replace("\n", "<br>") + "</p>")
    add_posting(engine, "senior-ai-engineer.json")
    write(engine, userdata.set_setting, "llm.model", "gemma4:12b")
    return engine


def eval_llm(**kwargs):
    return FakeLLM(
        {
            "lines": [
                label_lines({"PyTorch": "required", "Python": "required", "MLflow": "required", "Docker": "required"})
            ],
            "skills": [
                {
                    "skills": [
                        skill(1, "PyTorch framework", "PyTorch"),
                        skill(2, "Python", "Python"),
                        skill(2, "SQL", "SQL"),
                        skill(3, "MLflow", "MLflow"),
                    ]
                }
            ],
        },
        **kwargs,
    )


def label(engine):
    for name, quote in [
        ("PyTorch", "experience with PyTorch"),
        ("Python", "Python"),
        ("SQL", "SQL"),
        ("MLflow", "MLflow"),
        ("Airflow", "Experience with Airflow"),
    ]:
        write(engine, userdata.add_skill_mark, JOB, name, quote, importance="required")
    write(engine, userdata.set_skills_complete, JOB, True)


def runs(engine):
    with engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(posting_enrichments)).scalar_one()


def test_accepting_a_suggestion_keeps_the_posting_labelled(db):
    label(db)
    run_id = add_run(db, OTHER, skills=[("Python", "required", "Python")])
    with db.begin() as conn:
        item = conn.execute(
            select(enrichment_skills.c.id).where(enrichment_skills.c.enrichment_id == run_id)
        ).scalar_one()
        userdata.accept_suggestion(conn, item)
        userdata.set_skills_complete(conn, OTHER, True)
        origins = {p.job_id: [m.origin for m in p.marks] for p in evaluate.labelled_set(conn)}
    assert origins == {JOB: ["selection"] * 5, OTHER: ["suggestion"]}


def test_evaluate_end_to_end(db):
    label(db)
    llm = eval_llm()
    report = evaluate.evaluate(db, llm)
    assert (report.model, report.pipeline, report.new_runs, report.reused_runs) == ("gemma4:12b", PIPELINE, 1, 0)
    summary = report.to_dict()
    assert "groups" not in summary and summary["postings"] == 1
    assert summary["recall"]["all"] == {"count": 4, "of": 5, "ratio": 0.8}
    assert summary["precision"]["all"] == {"count": 4, "of": 4, "ratio": 1.0}
    assert summary["unjudged"] == {"all": 0, "required": 0, "preferred": 0}
    assert summary["misses"] == {"segmentation": 1, "extraction": 0, "not_located": 0}
    assert summary["segment_recall"] == {"count": 4, "of": 5, "ratio": 0.8}
    assert summary["importance_agreement"]["ratio"] == 1.0
    assert summary["failures"] == 0 and summary["mean_run_seconds"] is not None
    text = report.format_text()
    assert "precision 100% (4/4), 0 unjudged" in text and "recall  80% (4/5)" in text and "1 segmentation" in text
    assert "blind" not in text and "reviewed" not in text
    assert runs(db) == 1
    with db.connect() as conn:
        assert conn.execute(select(posting_enrichments.c.origin)).scalar_one() == "eval"


def test_evaluate_reuses_runs_unless_fresh(db):
    label(db)
    evaluate.evaluate(db, eval_llm())
    llm = eval_llm()
    again = evaluate.evaluate(db, llm)
    assert (again.new_runs, again.reused_runs) == (0, 1) and llm.requests == []
    fresh = evaluate.evaluate(db, llm, fresh=True)
    assert fresh.new_runs == 1 and llm.requests and runs(db) == 2


def test_evaluate_other_model_and_segmenter(db):
    label(db)
    evaluate.evaluate(db, eval_llm())
    llm = eval_llm()
    report = evaluate.evaluate(db, llm, model="phi4:latest", segmenter="rules")
    assert report.model == "phi4:latest" and report.pipeline.startswith("seg=rules@2")
    assert report.new_runs == 1 and llm.model == "phi4:latest" and llm.calls("lines") == 0


def test_failed_runs_counted_not_attributed(db):
    label(db)
    llm = eval_llm()
    llm.responses["skills"] = [{"skills": []}]
    summary = evaluate.evaluate(db, llm).to_dict()
    assert summary["failures"] == 1 and summary["postings"] == 0
    assert summary["misses"] == {"segmentation": 0, "extraction": 0, "not_located": 0}


def test_reusing_an_app_run(db):
    label(db)
    app_run = add_run(db, JOB, skills=[("Python", "required", "Python")])
    llm = eval_llm()
    report = evaluate.evaluate(db, llm)
    assert (report.new_runs, report.reused_runs) == (0, 1) and llm.requests == []
    assert runs(db) == 1 and report.to_dict()["recall"]["all"]["count"] == 1
    with db.connect() as conn:
        assert (
            conn.execute(select(posting_enrichments.c.origin).where(posting_enrichments.c.id == app_run)).scalar_one()
            == "app"
        )


def test_evaluating_a_candidate_leaves_the_app_alone(db, candidate):
    from jobhunt import queries

    label(db)
    add_run(db, JOB, skills=[("Docker", "required", "Docker")])
    write(db, userdata.add_profile_skill, "Docker", "proficient")

    def app_view():
        with db.connect() as conn:
            return queries.posting_skills(conn, JOB), queries.enrichment_panel(conn, JOB), queries.effective_links(conn)

    before = app_view()
    report = evaluate.evaluate(db, eval_llm(), skills="atomic@5")
    assert report.new_runs == 1
    with db.connect() as conn:
        origins = conn.execute(
            select(posting_enrichments.c.origin).order_by(posting_enrichments.c.id)
        ).scalars().all()
    assert origins == ["app", "eval"]
    assert app_view() == before
    assert "pytorch framework" not in {s["key"] for s in before[0]}  # the eval run's suggestion stays out


def test_no_labelled_postings(db):
    llm = eval_llm()
    with pytest.raises(evaluate.NoLabelledPostings):
        evaluate.evaluate(db, llm)
    assert llm.requests == []


def test_unreachable_writes_nothing(db):
    label(db)
    with pytest.raises(Unreachable):
        evaluate.evaluate(db, FakeLLM(unreachable=True))
    assert runs(db) == 0


def test_stored_runs_need_no_server(db):
    label(db)
    evaluate.evaluate(db, eval_llm())
    report = evaluate.evaluate(db, FakeLLM(unreachable=True))
    assert report.reused_runs == 1


# --- Per posting, reasons, sets, marks selected after a run, JSON detail ---

T1 = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
T2 = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)
T4 = datetime(2026, 10, 4, 9, 0, tzinfo=UTC)  # after add_run's runs (2026-10-03 12:00)


def label_at(engine, job_id, marks, now):
    for name, quote in marks:
        write(engine, userdata.add_skill_mark, job_id, name, quote, now=now, importance="required")
    write(engine, userdata.set_skills_complete, job_id, True, now=now)


def test_counts_add():
    a, b = Counts(postings=1, failures=1), Counts(postings=2, selected_after_run=3)
    a.right["all"], b.right["all"] = 2, 5
    a.wrong_by_reason["not_for_me"], b.run_seconds = 1, [1.5]
    c = a + b
    assert (c.postings, c.failures, c.selected_after_run, c.right["all"], c.run_seconds) == (3, 1, 3, 7, [1.5])
    assert c.wrong_by_reason == {"not_a_skill": 0, "not_for_me": 1, "no_reason": 0}


def test_wrong_suggestions_by_reason(db):
    label_at(db, JOB, [("Python", "Python")], T1)
    add_run(
        db,
        JOB,
        skills=[
            ("Python", "required", "Python"),
            ("Requirements", "required", "Requirements"),
            ("Experiment tracking", "required", "experiment tracking"),
            ("Docker", "required", "Docker"),
            ("Team", "preferred", "the team"),
        ],
    )
    write(db, userdata.reject_suggestion, JOB, "Requirements", "not-a-skill")
    write(db, userdata.reject_suggestion, JOB, "Experiment tracking", "not-a-skill")
    write(db, userdata.reject_suggestion, JOB, "Docker", "not-for-me")
    with db.begin() as conn:  # rejected before reasons existed
        conn.execute(rejected_suggestions.insert().values(job_id=JOB, skill_key="team", created_at=T1))
    report = evaluate.evaluate(db, FakeLLM(unreachable=True))
    summary = report.to_dict()
    assert summary["precision"]["all"] == {"count": 1, "of": 5, "ratio": 0.2}
    assert summary["wrong_by_reason"] == {"not_a_skill": 2, "not_for_me": 1, "no_reason": 1}
    assert "wrong by reason: 2 not a skill, 1 not for me, 1 no reason" in report.format_text()
    [detail] = summary["per_posting"]
    assert sorted((w["name"], w["reason"]) for w in detail["wrong"]) == [
        ("Docker", "not-for-me"),
        ("Experiment tracking", "not-a-skill"),
        ("Requirements", "not-a-skill"),
        ("Team", None),
    ]


def sets_db(db):
    """JOB labelled before the held-out start (T1 < T2), OTHER after it (T4); both have stored runs."""
    label_at(db, JOB, [("Python", "Python"), ("Docker", "Docker")], T1)
    write(db, userdata.set_setting, "eval.holdout_start", T2)
    label_at(db, OTHER, [("Python", "Python")], T4)
    add_run(db, JOB, skills=[("Python", "required", "Python")])
    add_run(db, OTHER, skills=[("Python", "required", "Python")])


def test_labelled_after_the_start(db):
    sets_db(db)
    report = evaluate.evaluate(db, FakeLLM(unreachable=True))
    assert [(name, size, c.postings, c.matched_marks["all"], c.marks["all"]) for name, size, c in report.sets()] == [
        ("development", 1, 1, 1, 2),
        ("held-out", 1, 1, 1, 1),
        ("together", 2, 2, 2, 3),
    ]
    summary = report.to_dict()
    assert summary["recall"]["all"] == {"count": 2, "of": 3, "ratio": 2 / 3}  # together, at the top level
    assert summary["sets"]["development"]["labelled"] == 1 and summary["sets"]["held_out"]["recall"]["all"]["of"] == 1
    assert [p["set"] for p in summary["per_posting"]] == ["development", "held-out"]
    text = report.format_text()
    assert "development: 1 labelled postings, 1 scored" in text and "held-out: 1 labelled postings" in text
    assert "together: 2 labelled postings, 2 scored" in text and "postings: " not in text


def test_no_held_out_set(db):
    sets_db(db)
    write(db, userdata.set_setting, "eval.holdout_start", None)
    report = evaluate.evaluate(db, FakeLLM(unreachable=True))
    assert [(name, size) for name, size, _ in report.sets()] == [("all", 2)]
    summary = report.to_dict()
    assert "sets" not in summary and summary["holdout_start"] is None
    assert "postings: 2 scored" in report.format_text()


def test_re_flagging_keeps_a_posting_in_development(db):
    sets_db(db)
    write(db, userdata.set_skills_complete, JOB, False, now=T4)
    write(db, userdata.add_skill_mark, JOB, "SQL", "SQL", now=T4)
    write(db, userdata.set_skills_complete, JOB, True, now=T4)
    with db.connect() as conn:
        assert {p.job_id: p.set for p in evaluate.labelled_set(conn)} == {JOB: "development", OTHER: "held-out"}


def test_mark_selected_after_a_run(db):
    label_at(db, JOB, [("Python", "Python")], T1)
    add_run(db, JOB, skills=[("Python", "required", "Python")])  # finished 2026-10-03
    write(db, userdata.add_skill_mark, JOB, "Docker", "Docker", now=T4)
    report = evaluate.evaluate(db, FakeLLM(unreachable=True))
    summary = report.to_dict()
    assert summary["selected_after_run"] == 1 and summary["per_posting"][0]["selected_after_run"] == 1
    assert summary["recall"]["all"] == {"count": 1, "of": 2, "ratio": 0.5}  # still scored as selected
    assert "warning: 1 selected mark was made after the posting had a successful run" in report.format_text()


def test_failed_runs_do_not_count_for_the_warning(db):
    label_at(db, JOB, [("Python", "Python")], T1)
    add_run(db, JOB, status="failed", error="boom", pipeline="seg=rules@2 old")
    write(db, userdata.add_skill_mark, JOB, "Docker", "Docker", now=T4)
    with db.connect() as conn:
        [posting] = evaluate.labelled_set(conn)
    assert posting.first_run_at is None and posting.selected_after_run() == 0


def test_json_detail(db):
    label(db)
    run_id = add_run(
        db,
        JOB,
        skills=[
            ("PyTorch", "required", "PyTorch"),
            ("Python", "required", "Python"),
            ("Docker", "required", "Docker"),
            ("Requirements", "required", "Requirements"),
        ],
        segments=REQUIRED_SEGMENTS,
    )
    write(db, userdata.reject_suggestion, JOB, "Requirements", "not-a-skill")
    report = evaluate.evaluate(db, FakeLLM(unreachable=True))
    summary = json.loads(evaluate.report_json(report))
    old_fields = {
        "model", "pipeline", "new_runs", "reused_runs", "postings", "failures", "precision", "unjudged", "recall",
        "importance_agreement", "segment_recall", "misses", "mean_run_seconds",
    }
    assert old_fields <= set(summary) and summary["postings"] == 1 and summary["reused_runs"] == 1
    assert summary["skills"] == "atomic@2" and run_id
    [detail] = summary["per_posting"]
    assert (detail["job_id"], detail["set"], detail["status"]) == (JOB, "development", "succeeded")
    assert detail["missed"] == [
        {"name": "SQL", "importance": "required", "quote": "SQL", "step": "extraction"},
        {"name": "MLflow", "importance": "required", "quote": "MLflow", "step": "extraction"},
        {"name": "Airflow", "importance": "required", "quote": "Experience with Airflow", "step": "segmentation"},
    ]
    assert detail["wrong"] == [{"name": "Requirements", "quote": "Requirements", "reason": "not-a-skill"}]
    assert detail["unjudged"] == [{"name": "Docker", "importance": "required", "quote": "Docker"}]


def test_evaluate_with_a_skill_method(db, candidate):
    label(db)
    llm = eval_llm()
    report = evaluate.evaluate(db, llm, skills="atomic@5")
    assert "skills=atomic@5" in report.pipeline and report.skills == "atomic@5"
    assert all(r.system == CANDIDATE_SYSTEM for r in llm.requests if r.key == "skills")
    with pytest.raises(evaluate.UnknownSkills, match="atomic@2, atomic@5"):
        evaluate.evaluate(db, llm := eval_llm(), skills="atomic@3")
    assert llm.requests == []


def test_skill_method_defaults_to_the_apps(db, candidate):
    label(db)
    assert "skills=atomic@2" in evaluate.evaluate(db, eval_llm()).pipeline
