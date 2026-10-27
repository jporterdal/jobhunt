"""The document pipeline (caps@1, llm@1, rules@1 records, cv-claims@1, part-of@1, validation) against FakeLLM,
and stored document runs with their suggestions."""

import json

import pytest
from sqlalchemy import select

from jobhunt.db import document_runs, profile_suggestions
from jobhunt.enrich import cv, derived
from jobhunt.enrich.pipeline import Cancelled

from .fakes import FakeLLM
from .test_profile import add_document, rows
from .test_userdata import write

CV_TEXT = "\n".join([
    "Jane Doe",
    "jane@example.com | +1 902 555 0100",
    "https://janedoe.dev",
    "github.com/janedoe",
    "Example City, EX",
    "SUMMARY & GOALS",
    "I build optimisation tools for people who plan things.",
    "SKILLS & EXPERIENCE",
    "8+ years experience with Python (incl. NumPy, matplotlib, scikit-learn)",
    "Familiar with serverless CI/CD",
    "TEACHING EXPERIENCE",
    "Sessional instructor at three Example City universities.",
    "Sessional Instructor, COMP 1000 Introduction to Programming, Example Polytechnic",
    "Taught Fall 2026, Winter 2026, Winter 2025, Winter 2024",
    "Lecturer, Example University, Example City — taught statistics",
    "STAT 2000 Statistics\t2016",
    "COMP 4150 Machine Learning\t2024",
    "EDUCATION",
    "PhD Computer Science, Example University\t2022",
    "PhD thesis: Adaptive penalty methods for constrained search\t2022",
    "PROJECTS",
    "city-parking - Parking enforcement tool",
    "Technologies: Python, Flask, PostgreSQL, Leaflet",
    "https://github.com/janedoe-example/city-parking",
])

ENTRIES = {
    "https://": {"label": "bullet"},  # first: the address also names the project
    "COMP 1000": {
        "label": "entry",
        "title": "Sessional Instructor, COMP 1000 Introduction to Programming",
        "organisation": "Example Polytechnic",
    },
    "Taught": {"label": "detail"},
    "Lecturer": {
        "label": "entry",
        "title": "Lecturer",
        "organisation": "Example University",
        "location": "Example City",
    },
    "STAT 2000": {"label": "detail"},
    "COMP 4150": {"label": "detail"},
    "PhD Computer Science": {"label": "entry", "title": "PhD Computer Science", "organisation": "Example University"},
    "PhD thesis": {"label": "entry", "title": "PhD thesis: Adaptive penalty methods for constrained search"},
    "city-parking": {"label": "entry", "title": "city-parking"},
    "Technologies": {"label": "bullet"},
    "Sessional instructor at": {"label": "text"},
}


def label_cv_lines(rules: dict[str, dict]):
    """A llm@1 response: each numbered line whose text contains a key gets that answer."""

    def respond(user: str) -> dict:
        out = []
        for row in user.splitlines():
            number, _, text = row.partition(": ")
            for needle, answer in rules.items():
                if needle in text:
                    out.append({"line": int(number), **answer})
                    break
        return {"lines": out}

    return respond


def cv_skills_for(rules: dict[str, list[dict]]):
    """A cv-claims@1 response: skills for each numbered line whose text contains a key."""

    def respond(user: str) -> dict:
        out = []
        for row in user.splitlines():
            number, _, text = row.partition(": ")
            for needle, found in rules.items():
                if needle in text:
                    out += [{"line": int(number), "level": "proficient", "kind": "technical", **f} for f in found]
        return {"cv_skills": out}

    return respond


SKILLS = {
    "8+ years": [
        {"name": "Python", "quote": "Python", "level": "expert"},
        {"name": "NumPy", "quote": "NumPy"},
        {"name": "matplotlib", "quote": "matplotlib"},
        {"name": "scikit-learn", "quote": "scikit-learn"},
    ],
    "serverless": [{"name": "CI/CD", "quote": "CI/CD", "level": "familiar"}],
    "Taught Fall": [{"name": "Teaching", "quote": "Taught", "kind": "soft"}],
    "Lecturer": [{"name": "Teaching", "quote": "taught statistics", "kind": "soft"}],
    "PhD Computer Science": [
        {"name": "PhD Computer Science", "quote": "PhD Computer Science", "kind": "qualification"}
    ],
    "PhD thesis": [
        {"name": "Penalty methods", "quote": "penalty methods"},
        {"name": "Kubernetes", "quote": "Kubernetes clusters"},
    ],
    "Technologies": [{"name": "Flask", "quote": "Flask"}, {"name": "Python", "quote": "Python"}],
}


def good_llm(part_of=None, **kwargs):
    return FakeLLM({
        "lines": [label_cv_lines(ENTRIES)],
        "cv_skills": [cv_skills_for(SKILLS)],
        "part_of": [part_of or {"part_of": []}],
    }, **kwargs)


def run(llm=None, text=CV_TEXT):
    return cv.run_document(text, llm or good_llm())


def records_titled(result, start):
    return [r for r in result.suggestions["record"] if (r["title"] or "").startswith(start)]


def claim_named(result, name):
    return next((c for c in result.suggestions["claim"] if c["name"] == name), None)


def position(result, title):
    return next(i for i, r in enumerate(result.suggestions["record"]) if r["title"] == title)


def highlight_at(result, start):
    return next(i for i, h in enumerate(result.suggestions["highlight"]) if h["text"].startswith(start))


# --- caps@1 sections (unchanged) ---


def test_heading_with_a_tabbed_note():
    assert (
        cv.heading_text("SELECTED PUBLICATIONS\t\t*(full citations available on my website)") == "SELECTED PUBLICATIONS"
    )
    assert cv.section_kind("SELECTED PUBLICATIONS") == "publication"


def test_combined_heading():
    assert cv.section_kind("SKILLS & EXPERIENCE") == "claims"


@pytest.mark.parametrize("heading, kind", [
    ("SUMMARY & GOALS", "summary"), ("PROFILE", "summary"), ("TEACHING EXPERIENCE", "experience"),
    ("WORK HISTORY", "experience"), ("EDUCATION", "education"), ("PROJECTS", "project"), ("AWARDS", "other"),
])
def test_section_kinds(heading, kind):
    assert cv.section_kind(heading) == kind


@pytest.mark.parametrize("line", ["PhD Computer Science", "Python 3", "A", "X" * 61, "\t2019", "MSc\tMATHS"])
def test_not_headings(line):
    assert cv.heading_text(line) is None


def test_sections_split_at_headings():
    sections = cv.SECTIONS.sections(CV_TEXT)
    assert [(s.name, s.kind, len(s.lines)) for s in sections] == [
        ("Contact", "contact", 5),
        ("Summary & Goals", "summary", 1),
        ("Skills & Experience", "claims", 2),
        ("Teaching Experience", "experience", 6),
        ("Education", "education", 2),
        ("Projects", "project", 3),
    ]


def test_contact_block():
    llm = good_llm()
    result = run(llm)
    sent = "\n".join(r.user + r.system for r in llm.requests)
    assert not any(
        secret in sent for secret in ("Jane Doe", "jane@example.com", "555 0100", "janedoe.dev", "Example City, EX")
    )
    suggested = json.dumps(result.suggestions)
    assert not any(secret in suggested for secret in ("Jane Doe", "jane@example.com", "optimisation tools"))


@pytest.mark.parametrize("written, parsed", [
    ("2019", "2019"), ("Sep 2019", "2019-09"), ("September 2019", "2019-09"), ("09/2019", "2019-09"),
    ("2019-9", "2019-09"), ("Present", "present"), ("spring", None), ("13/2019", None),
])
def test_parse_date(written, parsed):
    assert cv.parse_date(written) == parsed


# --- rules@1: records, lines, sources and highlights (5.1) ---


def test_degree_with_a_tab_aligned_year():
    [phd] = records_titled(run(), "PhD Computer Science")
    assert (phd["kind"], phd["title"], phd["organisation"], phd["start_date"], phd["end_date"], phd["ongoing"]) == (
        "degree", "PhD Computer Science", "Example University", None, "2022", False,
    )


def test_terms_split_by_rule():
    result = run()
    terms = records_titled(result, "Sessional Instructor, COMP 1000")
    assert [(r["kind"], r["organisation"], r["start_date"], r["end_date"]) for r in terms] == [
        ("course", "Example Polytechnic", "2026-09", "2026-12"),
        ("course", "Example Polytechnic", "2026-01", "2026-04"),
        ("course", "Example Polytechnic", "2025-01", "2025-04"),
        ("course", "Example Polytechnic", "2024-01", "2024-04"),
    ]
    assert all(r["lines"] == [] for r in terms)  # the "Taught" line is consumed
    assert not any(r["kind"] == "role" and "COMP" in (r["title"] or "") for r in result.suggestions["record"])


def test_lines_and_dates_from_lines():
    [lecturer] = records_titled(run(), "Lecturer")
    assert (lecturer["kind"], lecturer["location"], lecturer["start_date"], lecturer["end_date"]) == (
        "role", "Example City", "2016", "2024",  # undated: its lines' dates
    )
    assert lecturer["lines"] == ["taught statistics", "STAT 2000 Statistics", "COMP 4150 Machine Learning"]


def test_project_address_becomes_a_source():
    [parking] = records_titled(run(), "city-parking")
    assert parking["lines"] == [
        "Parking enforcement tool",
        "Technologies: Python, Flask, PostgreSQL, Leaflet",
    ]  # the entry line's rest first
    assert parking["sources"] == [{"kind": "repo", "url": "https://github.com/janedoe-example/city-parking"}]


def test_claims_lines_and_section_introductions_become_highlights():
    result = run()
    assert [h["text"] for h in result.suggestions["highlight"]] == [
        "8+ years experience with Python (incl. NumPy, matplotlib, scikit-learn)",
        "Familiar with serverless CI/CD",
        "Sessional instructor at three Example City universities.",
    ]
    assert not records_titled(result, "Familiar with")


def test_lines_requests_skip_claims_contact_and_summary():
    llm = good_llm()
    run(llm)
    headed = [r.system.split('headed "')[1].split('"')[0] for r in llm.requests if r.key == "lines"]
    assert headed == ["Teaching Experience", "Education", "Projects"]


def test_ongoing_entry_from_present():
    text = "PROJECTS\njobhunt, personal project\tMar 2025 – Present"
    llm = FakeLLM({"lines": [label_cv_lines({"jobhunt": {"label": "entry", "title": "jobhunt"}})]})
    [project] = cv.run_document(text, llm).suggestions["record"]
    assert (project["start_date"], project["end_date"], project["ongoing"]) == ("2025-03", None, True)
    assert project["lines"] == ["personal project"]


def test_unverified_date():
    text = "PROJECTS\nBuilt a scheduler in Go"
    llm = FakeLLM(
        {"lines": [label_cv_lines({"scheduler": {"label": "entry", "title": "Built a scheduler", "end": "2019"}})]}
    )
    result = cv.run_document(text, llm)
    [record] = result.suggestions["record"]
    assert record["end_date"] is None and record["start_date"] is None
    assert result.trace["unverified"]["dates"] == [{"line": "Built a scheduler in Go", "end": "2019"}]


def test_unverified_field_is_left_out():
    text = "EDUCATION\nMSc Statistics\t2009"
    llm = FakeLLM(
        {
            "lines": [
                label_cv_lines(
                    {"MSc": {"label": "entry", "title": "MSc Statistics", "organisation": "Example Institute"}}
                )
            ]
        }
    )
    result = cv.run_document(text, llm)
    [record] = result.suggestions["record"]
    assert (record["title"], record["organisation"], record["end_date"]) == ("MSc Statistics", None, "2009")
    assert result.trace["unverified"]["fields"] == [
        {"line": "MSc Statistics\t2009", "organisation": "Example Institute"}
    ]


# --- cv-claims@1 (5.2) ---


def test_claim_with_libraries():
    result = run()
    line = highlight_at(result, "8+ years")
    for name in ("Python", "NumPy", "matplotlib", "scikit-learn"):
        assert {"highlight": line, "quote": name} in claim_named(result, name)["coverage"]
    assert claim_named(result, "NumPy")["grounds"] == []


def test_skill_on_a_project_line():
    result = run()
    assert claim_named(result, "Flask")["grounds"] == [{"record": position(result, "city-parking"), "quote": "Flask"}]


def test_repeats_fold_into_one_claim_at_the_highest_level():
    result = run()
    python = claim_named(result, "Python")
    assert python["level"] == "expert"
    assert python["grounds"] == [{"record": position(result, "city-parking"), "quote": "Python"}]
    assert python["coverage"] == [{"highlight": highlight_at(result, "8+ years"), "quote": "Python"}]
    assert sum(c["name"] == "Python" for c in result.suggestions["claim"]) == 1


def test_a_skill_on_a_taught_line_grounds_every_term():
    result = run()
    terms = [
        i for i, r in enumerate(result.suggestions["record"]) if (r["title"] or "").startswith("Sessional Instructor")
    ]
    grounds = claim_named(result, "Teaching")["grounds"]
    assert [g["record"] for g in grounds] == terms + [position(result, "Lecturer")]
    assert {g["quote"] for g in grounds} == {"Taught", "taught statistics"}


def test_wording_sets_the_level():
    assert claim_named(run(), "CI/CD")["level"] == "familiar"


def test_invented_skill_quote():
    result = run()
    assert claim_named(result, "Kubernetes") is None
    assert {"name": "Kubernetes", "quote": "Kubernetes clusters"} in result.trace["unverified"]["skills"]
    assert claim_named(result, "Penalty methods") is not None


def test_skills_request_has_no_years():
    llm = good_llm()
    run(llm)
    [request, *_] = [r for r in llm.requests if r.key == "cv_skills"]
    assert "years" not in request.schema["properties"]["cv_skills"]["items"]["properties"]
    assert '"years"' not in request.system


def test_empty_section_retried_once_then_left_empty():
    llm = FakeLLM({"lines": [label_cv_lines(ENTRIES)]})  # no skills anywhere
    result = run(llm)
    assert result.status == "succeeded" and result.suggestions["claim"] == []
    skill_requests = [r for r in llm.requests if r.key == "cv_skills"]
    assert [cv.CV_SKILLS_REMINDER in r.user for r in skill_requests] == [False, True] * 4


# --- part-of@1 (5.3) ---


def test_thesis_and_degree():
    probe = run()
    thesis, phd = (
        position(probe, "PhD thesis: Adaptive penalty methods for constrained search"),
        position(probe, "PhD Computer Science"),
    )
    result = run(
        good_llm({"part_of": [{"record": thesis + 1, "part_of": phd + 1}, {"record": phd + 1, "part_of": None}]})
    )
    assert result.suggestions["part_of"] == [{"record": thesis, "part_of": phd}]


def test_cycle_dropped():
    result = run(good_llm({"part_of": [{"record": 1, "part_of": 2}, {"record": 2, "part_of": 1}]}))
    assert result.suggestions["part_of"] == [{"record": 0, "part_of": 1}]
    assert result.trace["unverified"]["part_of"] == [{"record": 2, "part_of": 1}]


def test_self_out_of_range_and_second_answers_dropped():
    result = run(
        good_llm(
            {
                "part_of": [
                    {"record": 3, "part_of": 3},
                    {"record": 4, "part_of": 99},
                    {"record": 5, "part_of": 1},
                    {"record": 5, "part_of": 2},
                ]
            }
        )
    )
    assert result.suggestions["part_of"] == [{"record": 4, "part_of": 0}]


def test_the_prompt_holds_the_guideline_word_for_word():
    guideline = (
        "a `part_of_id` reference is made by a Record entry when the existing entry is missing important context, may "
        "be misinterpreted, or may be difficult to understand without also considering its linked Record entry"
    )
    llm = good_llm()
    run(llm)
    [request] = [r for r in llm.requests if r.key == "part_of"]
    assert guideline in request.system and cv.PART_OF_GUIDELINE == guideline
    assert request.user.splitlines()[0].startswith("1: course | Sessional Instructor, COMP 1000")
    assert "PhD thesis" in request.user and "Jane Doe" not in request.user


def test_one_record_asks_nothing():
    text = "PROJECTS\njobhunt"
    llm = FakeLLM({"lines": [label_cv_lines({"jobhunt": {"label": "entry", "title": "jobhunt"}})]})
    assert cv.run_document(text, llm).suggestions["part_of"] == [] and llm.calls("part_of") == 0


# --- The run (5.4) ---


def test_pipeline_id():
    assert cv.pipeline_id() == (
        "cvseg=caps@1 cvlines=llm@1 cvrecords=rules@1 cvskills=cv-claims@1 cvpartof=part-of@1 validate=v@3"
    )
    cv.check_pipeline(cv.pipeline_id())
    with pytest.raises(ValueError, match="not available"):
        cv.check_pipeline("cvseg=caps@1 cvlines=llm@1 cvskills=cv-atomic@1 validate=v@3")


def test_malformed_answer_fails_the_run():
    llm = FakeLLM({"lines": [label_cv_lines(ENTRIES)], "cv_skills": [{"cv_skills": [{"line": 1}]}]})
    result = run(llm)
    assert result.status == "failed" and result.suggestions is None
    assert result.error.startswith("skills: response does not match the schema")


def test_cancelled_between_sections():
    calls = []
    llm = good_llm(on_call=calls.append)
    with pytest.raises(Cancelled):
        cv.run_document(CV_TEXT, llm, should_stop=lambda: len(calls) >= 2)
    assert calls == ["lines", "lines"]


# --- Stored runs ---


def test_extracting_twice(engine):
    document_id = add_document(engine)
    first = write(engine, derived.save_document_run, document_id, "f" * 64, "gemma4:12b", cv.pipeline_id(), run())
    before = rows(engine, profile_suggestions)
    second = write(engine, derived.save_document_run, document_id, "f" * 64, "gemma4:12b", cv.pipeline_id(), run())
    after = rows(engine, profile_suggestions)
    assert first != second and after[:len(before)] == before and len(after) == 2 * len(before)
    mine = [r for r in after if r.run_id == second]
    assert [(r.kind, r.position) for r in mine if r.kind == "record"][:2] == [("record", 0), ("record", 1)]
    assert json.loads(next(r.payload_json for r in mine if r.kind == "highlight")) == {
        "text": "8+ years experience with Python (incl. NumPy, matplotlib, scikit-learn)"
    }
    stored = rows(engine, document_runs)[1]
    trace = json.loads(stored.output_json)
    assert trace["steps"][0]["step"] == "sections" and "Kubernetes" in json.dumps(trace["unverified"])


def test_failed_run_is_stored_without_suggestions(engine):
    document_id = add_document(engine)
    result = run(FakeLLM({"lines": [{"lines": [{"line": "x"}]}]}))
    run_id = write(engine, derived.save_document_run, document_id, "f" * 64, "gemma4:12b", cv.pipeline_id(), result)
    with engine.connect() as conn:
        stored = conn.execute(select(document_runs).where(document_runs.c.id == run_id)).one()
    assert (stored.status, stored.error) == (
        "failed",
        "lines: response does not match the schema: $.lines[0].label is missing",
    )
    assert rows(engine, profile_suggestions) == []
