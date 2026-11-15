"""The MCP tools as plain functions (mcp_tools.py): the same rows and figures as the read models, paging, the
description limit, NotFound, the never-returned data and private records, and that nothing is written or contacted.
Needs no `mcp` package."""

import ast
import json
import urllib.request
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from jobhunt import documents, mcp_tools, queries, recommend, userdata
from jobhunt.db import DERIVED_TABLES, OPERATIONAL_TABLES, USER_TABLES, metadata
from jobhunt.enrich import derived
from jobhunt.enrich.links import PIPELINE as LINKS_PIPELINE
from jobhunt.enrich.links import Candidate, Planned
from jobhunt.mcp_tools import NotFound

from .conftest import add_posting, add_run, read_only_twin

T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def write(engine, fn, *args, **kwargs):
    with engine.begin() as conn:
        return fn(conn, *args, **kwargs)


def call(engine, tool, **arguments):
    with engine.connect() as conn:
        return mcp_tools.TOOLS[tool](conn, **arguments)


def posting(engine, n, title="Data Engineer", company="Example Labs", day=0, text=None, **changes):
    """A posting with external id 90000000nn, captured `day` days after T0 (so later ones are seen more recently)."""
    changes.setdefault("description_text", text or f"{title} at {company}. Python, SQL and Design.")
    return add_posting(
        engine,
        external_id=f"90000000{n:02d}",
        url=f"https://example.com/jobs/90000000{n:02d}",
        title=title,
        company=company,
        captured_at=T0 + timedelta(days=day),
        **changes,
    )


def mark(engine, job, name, importance="required", quote="Design"):
    return write(engine, userdata.add_skill_mark, job, name, quote, importance=importance)


def store_judgment(engine, key, name, relations):
    item = Planned(key, name, None, [Candidate(skill_id, f"skill {skill_id}", 0.9) for skill_id in relations])
    with engine.begin() as conn:
        derived.save_judgment(conn, item, "gemma4:12b", "nomic-embed-text:latest", LINKS_PIPELINE, "succeeded", None,
                              relations, {})


def counts(engine):
    with engine.connect() as conn:
        return {t.name: conn.execute(select(func.count()).select_from(t)).scalar_one() for t in metadata.sorted_tables}


# --- the module (2.1) ---


def test_scopes_name_the_spec_tools():
    assert mcp_tools.SCOPES == {
        "postings": ("search_postings", "get_posting"),
        "profile": ("posting_fit", "profile_skills", "recommendations"),
    }
    assert set(mcp_tools.TOOLS) == {name for names in mcp_tools.SCOPES.values() for name in names}


def test_module_imports_no_writer_flask_or_mcp():
    tree = ast.parse(Path(mcp_tools.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            dots = "." * node.level
            imported |= {dots + (node.module or alias.name) for alias in node.names}
    forbidden = ("userdata", "store", "enrich.derived", "enrich.jobs", "prune", "flask", "mcp")
    for name in imported:
        bare = name.lstrip(".")
        assert not any(bare == f or bare.startswith(f + ".") or bare.endswith("." + f) for f in forbidden), name
    assert {".queries", ".recommend"} <= imported


# --- search_postings (2.2) ---


@pytest.fixture
def listed(engine):
    """Five postings with a spread of triage: a tag, ratings, a dismissal, an application, workplace types."""
    jobs = [
        posting(engine, 1, "Data Engineer", "Example Labs", day=1, workplace_type="Remote", text="Airflow and SQL."),
        posting(engine, 2, "ML Engineer", "Example Robotics", day=2, workplace_type="Hybrid", text="Airflow, Python."),
        posting(engine, 3, "Analyst", "Example Bank", day=3, workplace_type="On-site", text="Airflow reporting."),
        posting(engine, 4, "Platform Engineer", "Example Cloud", day=4, workplace_type="Remote", text="Kubernetes."),
        posting(engine, 5, "Researcher", "Example University", day=5, workplace_type=None, posted_on=None,
                posted_precision=None, text="Statistics."),
    ]
    write(engine, userdata.add_tag, jobs[0], "shortlist")
    write(engine, userdata.set_rating, jobs[0], "interest", 4)
    write(engine, userdata.set_rating, jobs[0], "fit", 3)
    write(engine, userdata.set_rating, jobs[3], "interest", 5)
    with engine.connect() as conn:
        reason = queries.all_dismiss_reasons(conn)[0].id
    write(engine, userdata.dismiss, jobs[2], [reason])
    write(engine, userdata.start_application, jobs[1])
    return jobs


FILTERS = [
    {},
    {"q": "airflow"},
    {"q": "9000000004"},
    {"tag": "Shortlist"},
    {"min_interest": 4},
    {"unrated": True},
    {"workplace": "Remote"},
    {"status": "any"},
    {"status": "none"},
    {"status": "interested"},
    {"dismissed": "included"},
    {"dismissed": "only"},
    {"sort": "first_seen"},
    {"sort": "posted"},
    {"sort": "interest", "workplace": "Remote"},
]


@pytest.mark.parametrize("arguments", FILTERS)
def test_search_matches_the_postings_list(listed, engine, arguments):
    found = call(engine, "search_postings", **arguments)
    with engine.connect() as conn:
        rows = queries.posting_list(conn, queries.ListFilters(**arguments))
    assert [p["job_id"] for p in found["postings"]] == [r["job_id"] for r in rows]
    assert found["total"] == len(rows)
    for p in found["postings"]:
        assert {"job_id", "title", "company", "url", "first_seen", "last_seen", "tags", "dismissed"} <= set(p)


def test_filtered_search(listed, engine):
    found = call(engine, "search_postings", q="Airflow")
    assert found["total"] == 2
    assert [p["job_id"] for p in found["postings"]] == [listed[1], listed[0]]  # most recently seen first


def test_search_fields(listed, engine):
    first = call(engine, "search_postings", tag="shortlist")["postings"][0]
    assert first == {
        "job_id": listed[0], "title": "Data Engineer", "company": "Example Labs",
        "url": "https://example.com/jobs/9000000001", "location": "Example City, EX", "workplace_type": "Remote",
        "posted_on": "2026-09-14", "first_seen": first["first_seen"], "last_seen": first["last_seen"],
        "interest": 4, "fit": 3, "tags": ["shortlist"], "dismissed": False,
    }
    assert datetime.fromisoformat(first["last_seen"]) == T0 + timedelta(days=1)
    applied = call(engine, "search_postings", status="any")["postings"][0]
    assert applied["application_status"] == "interested"
    bare = call(engine, "search_postings", q="Statistics")["postings"][0]
    assert "workplace_type" not in bare and "posted_on" not in bare and "interest" not in bare


def test_paging(engine):
    jobs = [posting(engine, n, day=n) for n in range(1, 8)]
    newest_first = list(reversed(jobs))
    first = call(engine, "search_postings", limit=3)
    assert (first["total"], first["offset"], first["next_offset"]) == (7, 0, 3)
    assert [p["job_id"] for p in first["postings"]] == newest_first[:3]
    middle = call(engine, "search_postings", limit=3, offset=3)
    assert (middle["offset"], middle["next_offset"]) == (3, 6)
    assert [p["job_id"] for p in middle["postings"]] == newest_first[3:6]
    last = call(engine, "search_postings", limit=3, offset=6)
    assert "next_offset" not in last and [p["job_id"] for p in last["postings"]] == newest_first[6:]
    beyond = call(engine, "search_postings", offset=40)
    assert (beyond["total"], beyond["offset"], beyond["postings"]) == (7, 40, [])
    assert len(call(engine, "search_postings")["postings"]) == 7  # default limit 20


@pytest.mark.parametrize("arguments", [
    {"sort": "salary"}, {"limit": 0}, {"limit": 51}, {"offset": -1}, {"min_interest": 6},
    {"workplace": "Mars"}, {"status": "hired"}, {"dismissed": "never"},
])
def test_search_refuses_values_outside_the_schema(engine, arguments):
    with pytest.raises(ValueError, match=next(iter(arguments))):
        call(engine, "search_postings", **arguments)


# --- what narrowed a search: filters_used and total_without ---

# The value that makes each filter narrow nothing (dismissed: "included" shows dismissed postings too).
NEUTRAL = {"q": "", "tag": "", "min_interest": None, "unrated": False, "workplace": None, "status": None,
           "dismissed": "included"}


@pytest.mark.parametrize("arguments", FILTERS)
def test_total_without_each_filter_is_the_search_without_it(listed, engine, arguments):
    result = call(engine, "search_postings", **arguments)
    used = result.get("filters_used", {})
    assert set(used) <= set(NEUTRAL)  # never sort, limit or offset
    assert set(result.get("total_without", {})) == set(used)
    for name in used:
        without = {**arguments, name: NEUTRAL[name]}
        if name == "dismissed":
            without["dismissed"] = "included"
        assert result["total_without"][name] == call(engine, "search_postings", **without)["total"], name


def test_filters_used_name_what_was_applied(listed, engine):
    result = call(engine, "search_postings", q="  Engineer ", workplace="Remote", sort="interest", limit=1)
    assert result["filters_used"] == {"q": "Engineer", "workplace": "Remote", "dismissed": "hidden"}
    assert result["total_without"] == {"q": 2, "workplace": 3, "dismissed": 2}
    assert result["total"] == 2 and len(result["postings"]) == 1
    assert list(result)[:3] == ["total", "filters_used", "total_without"]  # before the postings


def test_the_default_dismissed_filter_is_named(listed, engine):
    result = call(engine, "search_postings")
    assert result["filters_used"] == {"dismissed": "hidden"}
    assert result["total_without"] == {"dismissed": 5} and result["total"] == 4


def test_no_filter_means_neither_field(listed, engine):
    result = call(engine, "search_postings", dismissed="included", sort="posted")
    assert "filters_used" not in result and "total_without" not in result


def test_every_filter_kind_is_named(listed, engine):
    result = call(engine, "search_postings", q="Data", tag="shortlist", min_interest=4, workplace="Remote",
                  status="none", dismissed="only")
    assert list(result["filters_used"]) == ["q", "tag", "min_interest", "workplace", "status", "dismissed"]
    unrated = call(engine, "search_postings", unrated=True)
    assert unrated["filters_used"] == {"unrated": True, "dismissed": "hidden"}


# --- get_posting (2.3) ---


def test_get_posting(engine):
    job = posting(engine, 1, workplace_type="Hybrid", text="Build pipelines.\nUse Airflow.")
    write(engine, userdata.add_tag, job, "shortlist")
    write(engine, userdata.set_rating, job, "interest", 5)
    found = call(engine, "get_posting", job_id=job)
    assert found == {
        "job_id": job, "title": "Data Engineer", "company": "Example Labs", "url": "https://example.com/jobs/9000000001",
        "location": "Example City, EX", "workplace_type": "Hybrid", "posted_on": "2026-09-14",
        "first_seen": found["first_seen"], "last_seen": found["last_seen"], "interest": 5, "tags": ["shortlist"],
        "dismissed": False, "source": "jobs.example.com", "employment_type": "Full-time", "posted_precision": "day",
        "snapshots": 1, "details": {"apply_method": "external", "promotion": "Promoted by hirer", "reposted": True},
        "description": "Build pipelines.\nUse Airflow.", "description_chars": 29,
    }
    assert "<" not in found["description"]


def test_get_posting_leaves_out_fields_without_a_value(engine):
    job = posting(engine, 1, location=None, workplace_type=None, employment_type=None, posted_on=None,
                  posted_precision=None)
    found = call(engine, "get_posting", job_id=job)
    for name in ("location", "workplace_type", "employment_type", "posted_on", "posted_precision", "interest",
                 "fit", "application_status", "description_truncated"):
        assert name not in found


def test_long_description_is_cut(engine):
    text = ("word " * 5200).strip()  # 25,999 characters
    job = posting(engine, 1, text=text)
    found = call(engine, "get_posting", job_id=job)
    assert found["description"] == text[: mcp_tools.DESCRIPTION_LIMIT]
    assert (found["description_chars"], found["description_truncated"]) == (len(text), True)


def test_unknown_posting(engine):
    with pytest.raises(NotFound) as raised:
        call(engine, "get_posting", job_id=999)
    assert str(raised.value) == "No posting with id 999."
    with pytest.raises(NotFound):
        call(engine, "posting_fit", job_id=999)


# --- posting_fit (2.4) ---


@pytest.fixture
def fitted(engine):
    """Posting A asks for Python (profile, proficient), Kubernetes (no link), Kubeflow (judged: general MLOps,
    related Python), SQL (preferred; a user override to Python) and AWS (unspecified, missing in the profile)."""
    a = posting(engine, 1, text="Python, Kubernetes, Kubeflow, SQL and AWS. Design.")
    b = posting(engine, 2, "ML Engineer", "Example Robotics", day=2, workplace_type="Hybrid")
    python = write(engine, userdata.add_profile_skill, "Python", "proficient")
    mlops = write(engine, userdata.add_profile_skill, "MLOps", "learning")
    write(engine, userdata.add_profile_skill, "AWS", "missing")
    mark(engine, a, "Python")
    mark(engine, a, "Kubernetes")
    mark(engine, a, "Kubeflow")
    mark(engine, a, "SQL", "preferred")
    mark(engine, a, "AWS", None)
    mark(engine, b, "Python")
    store_judgment(engine, "kubeflow", "Kubeflow", {mlops: "general", python: "related"})
    store_judgment(engine, "kubernetes", "Kubernetes", {})
    write(engine, userdata.set_link_override, "sql", python, "related")
    return {"a": a, "b": b, "python": python, "mlops": mlops}


def test_posting_fit_matches_the_summary(fitted, engine):
    found = call(engine, "posting_fit", job_id=fitted["a"])
    with engine.connect() as conn:
        summary = recommend.posting_summary(conn, fitted["a"])
    assert found["score"] == summary["score"]["score"]
    assert (found["skills"], found["unlinked"]) == (5, summary["score"]["unlinked"])
    flat = [e for g in summary["have"] for e in g["entries"]]
    assert [(e["name"], e["credit"]) for e in found["have"]] == [(e["name"], e["credit"]) for e in flat]
    flat = [e for g in summary["dont_have"] for e in g["entries"]]
    assert [(e["name"], e["reason"]) for e in found["dont_have"]] == [(e["name"], e["reason"]) for e in flat]
    by_name = {e["name"]: e for e in found["have"]}
    assert by_name["Python"] == {
        "name": "Python", "importance": "required", "source": "mark", "credit": pytest.approx(0.85),
        "profile_skill": "Python", "level": "proficient", "relation": "same", "link_source": "same",
    }
    assert by_name["Kubeflow"]["link_source"] == "model" and by_name["Kubeflow"]["relation"] == "related"
    assert by_name["SQL"]["link_source"] == "user" and by_name["SQL"]["importance"] == "preferred"
    missing = {e["name"]: e for e in found["dont_have"]}
    assert missing["Kubernetes"] == {"name": "Kubernetes", "importance": "required", "source": "mark",
                                     "reason": "no-link"}
    assert missing["AWS"] == {"name": "AWS", "source": "mark", "reason": "missing", "profile_skill": "AWS"}
    assert (found["title"], found["url"]) == ("Data Engineer", "https://example.com/jobs/9000000001")


def test_posting_without_skills(engine):
    job = posting(engine, 1)
    found = call(engine, "posting_fit", job_id=job)
    assert "score" not in found
    assert (found["skills"], found["have"], found["dont_have"]) == (0, [], [])


# --- profile_skills (2.5) ---


def test_profile_skills(engine):
    rust = write(engine, userdata.add_profile_skill, "Rust", "learning")
    python = write(engine, userdata.add_profile_skill, "Python", "expert")
    write(engine, userdata.add_profile_skill, "Go", "learning")
    write(engine, userdata.merge_skill, write(engine, userdata.add_profile_skill, "Python 3", "familiar"), python)
    found = call(engine, "profile_skills")
    assert found == {
        "count": 3,
        "skills": [
            {"name": "Python", "level": "expert", "level_origin": "user", "aliases": ["Python 3"]},
            {"name": "Go", "level": "learning", "level_origin": "user", "aliases": []},
            {"name": "Rust", "level": "learning", "level_origin": "user", "aliases": []},
        ],
    }
    assert rust


def test_empty_profile(engine):
    assert call(engine, "profile_skills") == {"count": 0, "skills": []}


# --- recommendations (2.6) ---


@pytest.mark.parametrize("workplace", [None, [], ["Remote"], ["Remote", "Hybrid"], ["On-site", "Hybrid", "Remote"]])
def test_recommendations_match_insights(fitted, engine, workplace):
    posting(engine, 3, "Remote Engineer", "Example Cloud", day=3, workplace_type="Remote")
    mark(engine, 3, "Python")
    mark(engine, 3, "Terraform")
    arguments = {} if workplace is None else {"workplace": workplace}
    found = call(engine, "recommendations", **arguments)
    with engine.connect() as conn:
        expected = recommend.recommendations(conn, recommend.workplace_choice(workplace or ()))
    assert [(p["job_id"], p["score"], p["value"]) for p in found["postings"]] == [
        (p["job_id"], p["score"], p["value"]) for p in expected["postings"]
    ]
    assert [(s["name"], s["gain"], s["improved"]) for s in found["skills"]] == [
        (s["name"], s["gain"], s["improved"]) for s in expected["skills"]
    ]
    assert (found["considered"], found["no_skills"]) == (expected["considered"], expected["no_skills"])
    if expected["workplaces"] is None:
        assert "workplaces" not in found
    else:
        assert found["workplaces"] == [w for w in queries.WORKPLACE_TYPES if w in workplace]
    for p in found["postings"] + [p for s in found["skills"] for p in s["postings"]]:
        assert p["url"].startswith("https://example.com/jobs/")
    assert found["postings"], "the fixture ranks postings under every filter here"


def test_recommendations_refuse_an_unknown_workplace(engine):
    with pytest.raises(ValueError, match="workplace"):
        call(engine, "recommendations", workplace=["Moon"])


@pytest.mark.parametrize("workplace", [["Remote"], ["Hybrid", "On-site"]])
def test_considered_without_the_workplace_filter(fitted, engine, workplace):
    result = call(engine, "recommendations", workplace=workplace)
    assert result["considered_without"] == {"workplace": call(engine, "recommendations")["considered"]}
    keys = list(result)
    assert keys.index("considered_without") == keys.index("considered") + 1 < keys.index("postings")


@pytest.mark.parametrize("workplace", [[], ["On-site", "Hybrid", "Remote"]])
def test_no_workplace_filter_means_no_considered_without(fitted, engine, workplace):
    assert "considered_without" not in call(engine, "recommendations", workplace=workplace)


# --- never-returned data and private records (3.1, 3.2) ---

NEVER = {
    "name": "Zqname Doe", "headline": "Zqheadline", "contact": "zqcontact@example.com", "summary": "Zqsummary",
    "goal": "Zqgoal", "record_title": "Zqrecordtitle", "record_org": "Zqrecordorg", "record_line": "Zqrecordline",
    "record_source": "https://example.com/zqsource", "ground_quote": "Zqgroundquote", "highlight": "Zqhighlight",
    "document_name": "zqdocname.txt", "document_label": "Zqdoclabel", "note": "Zqnote", "dismissal": "Zqdismissal",
    "mark_quote": "Zqmarkquote", "event_note": "Zqeventnote", "contact_person": "Zqcontactperson",
    "company_note": "Zqcompanynote", "volatile": "Zqvolatile", "old_title": "Zqoldtitle",
    "unverified": "Zqunverified", "private_title": "Zqprivatetitle", "private_org": "Zqprivateorg",
    "context_parent": "Zqcontextparent", "context_child": "Zqcontextchild", "cv_line": "Zqcvline",
}
SHARED = {"title": "Zqsharedtitle", "tag": "zqsharedtag", "skill": "Zqsharedskill"}


@pytest.fixture
def planted(engine, tmp_path):
    """A database with a marker in every never-returned field, and in a few shared ones."""
    old = posting(engine, 1, title=NEVER["old_title"], day=0)
    job = posting(engine, 1, title=SHARED["title"], day=1, tag=NEVER["volatile"],
                  text="Python, Rust, Go and Zqsharedskill. Design.")
    other = posting(engine, 2, "ML Engineer", "Example Robotics", day=2)
    assert old == job
    for kind in ("name", "headline", "contact", "summary", "goal"):
        write(engine, userdata.add_detail, kind, NEVER[kind])
    record = write(engine, userdata.add_record, {"kind": "role", "title": NEVER["record_title"],
                                                 "organisation": NEVER["record_org"]})
    write(engine, userdata.add_line, record, NEVER["record_line"])
    write(engine, userdata.add_source, record, url=NEVER["record_source"])
    python = write(engine, userdata.add_profile_skill, "Python", "proficient")
    write(engine, userdata.add_ground, python, record, NEVER["ground_quote"])
    highlight = write(engine, userdata.add_highlight, NEVER["highlight"])
    write(engine, userdata.add_coverage, highlight, python, NEVER["highlight"])
    stored = documents.store_upload(tmp_path / "documents", b"Zqdocumenttext", NEVER["document_name"])
    write(engine, userdata.add_document, stored, NEVER["document_label"], "cv")
    write(engine, userdata.set_notes, job, NEVER["note"])
    with engine.connect() as conn:
        reason = queries.all_dismiss_reasons(conn)[0].id
    write(engine, userdata.dismiss, other, [reason], comment=NEVER["dismissal"])
    app = write(engine, userdata.start_application, other)
    write(engine, userdata.add_event, app, "note", date(2026, 9, 3), note=NEVER["event_note"])
    contact = write(engine, userdata.save_contact, None, NEVER["contact_person"], ["zqperson@example.com"])
    write(engine, userdata.link_contact, app, contact)
    with engine.begin() as conn:
        company = userdata.get_or_create_company(conn, "Example Labs")
        userdata.update_company(conn, company.id, "Example Labs", None, None, NEVER["company_note"])
    write(engine, userdata.add_tag, job, SHARED["tag"])
    mark(engine, job, "Python", quote=NEVER["mark_quote"])
    mark(engine, job, SHARED["skill"])
    add_run(engine, job, skills=[(NEVER["unverified"], "required", "not in the text at all")])

    # Private records (3.2): Rust grounded only by a private record, Go only by a record private through its context.
    private = write(engine, userdata.add_record, {"kind": "project", "title": NEVER["private_title"],
                                                  "organisation": NEVER["private_org"], "disclosure": "private"})
    parent = write(engine, userdata.add_record, {"kind": "role", "title": NEVER["context_parent"],
                                                 "disclosure": "private"})
    child = write(engine, userdata.add_record, {"kind": "project", "title": NEVER["context_child"]})
    write(engine, userdata.set_part_of, child, parent)
    rust = write(engine, userdata.add_profile_skill, "Rust", "familiar")
    go = write(engine, userdata.add_profile_skill, "Go", "learning")
    write(engine, userdata.add_ground, rust, private)
    write(engine, userdata.add_ground, go, child)
    mark(engine, job, "Rust")
    mark(engine, job, "Go", "preferred")
    return {"job": job, "other": other}


def every_call(job, other):
    """Every tool with a spread of arguments."""
    yield "search_postings", {}
    yield "search_postings", {"dismissed": "included", "sort": "interest"}
    yield "search_postings", {"q": "Zqsharedtitle", "status": "any", "dismissed": "only"}
    yield "search_postings", {"tag": SHARED["tag"]}
    for job_id in (job, other):
        yield "get_posting", {"job_id": job_id}
        yield "posting_fit", {"job_id": job_id}
    yield "profile_skills", {}
    yield "recommendations", {}
    yield "recommendations", {"workplace": ["On-site"]}


def all_results(engine, job, other) -> str:
    return "\n".join(json.dumps(call(engine, tool, **arguments)) for tool, arguments in every_call(job, other))


def test_never_returned_data(planted, engine):
    text = all_results(engine, planted["job"], planted["other"]).casefold()
    for field, marker in NEVER.items():
        assert marker.casefold() not in text, field
    for field, marker in SHARED.items():
        assert marker.casefold() in text, field


def test_private_records_and_their_skills(planted, engine):
    skills = {s["name"]: s["level"] for s in call(engine, "profile_skills")["skills"]}
    assert (skills["Rust"], skills["Go"]) == ("familiar", "learning")
    fit = call(engine, "posting_fit", job_id=planted["job"])
    have = {e["name"]: e["level"] for e in fit["have"]}
    assert (have["Rust"], have["Go"]) == ("familiar", "learning")


# --- read-only, unchanged and offline (3.3) ---


def test_tools_on_a_read_only_engine_change_nothing_and_contact_nothing(planted, engine, monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("a tool tried to open an address")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    before = counts(engine)
    ro = read_only_twin(engine)
    try:
        for tool, arguments in every_call(planted["job"], planted["other"]):
            with ro.connect() as conn:
                mcp_tools.TOOLS[tool](conn, **arguments)
    finally:
        ro.dispose()
    assert counts(engine) == before
    assert set(before) >= {t.name for t in USER_TABLES + DERIVED_TABLES + OPERATIONAL_TABLES}
