"""Link measurement: the reference set, request statement and reuse, scoring, verdicts, the preview, keeping
measurement apart from the app, and `jobhunt eval --links`."""

import json

import pytest
from sqlalchemy import func, select

from jobhunt import queries, userdata
from jobhunt.cli import main
from jobhunt.db import init_db, link_judgments, link_measurements, make_engine, skill_expansions
from jobhunt.enrich import expand, link_eval, links

from .conftest import add_posting
from .fakes import FakeOllama
from .test_links import (
    AI,
    BANK,
    EMBED,
    SIMILAR,
    axis,
    db,  # noqa: F401  (fixture)
    judge,
    link_of,
    mark,
    profile,
    relations_answer,
)
from .test_userdata import write

# Two directions: "devops" things on axis 0, "people" things on axis 1. Similarities are cosines.
VECTORS = {
    "CI/CD": axis(1, 0, 0), "Git": axis(0.8, 0.6, 0), "Written communication": axis(0, 1, 0),
    "Vector databases": axis(0.5, 0, 0.87),
    "GitHub Actions": axis(0.96, 0.28, 0), "Docker": axis(0.9, 0, 0.44), "Communication": axis(0.1, 0.99, 0),
    "serverless CI/CD": axis(0, 0.2, 0.98), "Python": axis(-1, 0, 0),
}


@pytest.fixture
def labelled(db, monkeypatch):
    """Four reference posting skills (three links, one refusal) and a same-identity one left out."""
    monkeypatch.setattr(links, "SHORTLIST_FLOOR", 0.5)
    monkeypatch.setattr(links, "SHORTLIST_K", 2)
    for name in ("CI/CD", "Git", "Written communication", "Vector databases", "Python"):
        mark(db, AI, name, "Design")
    ids = dict(zip(
        ["GitHub Actions", "Docker", "Communication", "serverless CI/CD", "Python"],
        profile(db, "GitHub Actions", "Docker", "Communication", "serverless CI/CD", "Python"),
        strict=True,
    ))
    write(db, userdata.set_link_override, "CI/CD", ids["GitHub Actions"], "specific")
    write(db, userdata.set_link_override, "Git", ids["serverless CI/CD"], "related")
    write(db, userdata.set_link_override, "Written communication", ids["Communication"], "general")
    write(db, userdata.set_link_override, "Vector databases", None)
    write(db, userdata.set_link_override, "Python", ids["Python"], "same")  # same identity: left out
    return db, ids


def client(*answers, **kwargs):
    return FakeOllama(responses={"relations": list(answers)} if answers else None, vectors=VECTORS, **kwargs)


def measure(engine, c, retrievals=None, judges=None, **kwargs):
    p = link_eval.plan(engine, c, retrievals, judges, **kwargs)
    return p, link_eval.execute(engine, c, p)


def by_key(result, key):
    return next(o for o in result.links + result.refusals if o.ref.key == key)


# --- The reference set (5.1) ---


def test_building_the_reference_set(labelled):
    db, ids = labelled
    mark(db, BANK, "Kubernetes", "Design")
    write(db, userdata.set_link_override, "Kubernetes", ids["Docker"], "related")
    write(db, userdata.set_link_override, "Salesforce", None)  # no posting asks for it
    write(db, userdata.remove_profile_skill, ids["Docker"])  # the Kubernetes override goes stale
    with db.connect() as conn:
        ref = link_eval.reference_set(conn)
    assert [r.key for r in ref.links] == ["ci/cd", "git", "written communication"]
    assert [r.key for r in ref.refusals] == ["vector databases"]
    assert ref.left_out == {"not a posting skill": 1, "same identity": 1, "stale": 1}


def test_override_on_an_alias_key_is_same_identity(labelled):
    db, ids = labelled
    mark(db, BANK, "GH Actions", "Design")
    write(db, userdata.set_link_override, "GH Actions", ids["GitHub Actions"], "same")
    with db.connect() as conn:
        assert "gh actions" in {r.key for r in link_eval.reference_set(conn).links}
        gh = queries.resolve_skill(conn, "gh actions").id
    write(db, userdata.merge_skill, gh, ids["GitHub Actions"])
    with db.connect() as conn:
        ref = link_eval.reference_set(conn)
    assert "gh actions" not in {r.key for r in ref.all}
    assert ref.left_out["same identity"] == 2


def test_no_overrides(db):
    mark(db, AI, "CI/CD")
    profile(db, "GitHub Actions")
    with pytest.raises(link_eval.NoReference):
        link_eval.plan(db, client())


def test_unknown_version(db):
    with pytest.raises(link_eval.UnknownMethod, match="link-judge@5, link-judge@6"):
        link_eval.plan(db, client(), judges=["link-judge@9"])


# --- Requests and reuse (5.1) ---


def test_stating_requests_first(labelled):
    db, _ = labelled
    c = client()
    p = link_eval.plan(db, c, [expand.STEP])
    # 4 reference posting skills and 5 profile skills have no expansion
    assert len(p.expansions) == 9 and not p.exact[f"{expand.STEP} + link-judge@5"]
    assert "expansion requests: 9" in p.statement() and c.requests == [] and c.embed_requests == []


def test_reusing_the_apps_judgments(labelled):
    db, _ = labelled
    for key in ("CI/CD", "Git", "Written communication", "Vector databases"):
        write(db, userdata.clear_link_override, key)
    judge(db, client(relations_answer("specific", "none")))
    app_requests = len(client().requests)
    labelled_again(db)
    c = client(relations_answer("none", "none"))
    p = link_eval.plan(db, c)
    # Only Git needs a judgment: with serverless CI/CD added to a shortlist that lacked it.
    assert p.judgments["names + link-judge@5"] == 1 and p.exact["names + link-judge@5"]
    _, report = measure(db, c)
    assert (report.new_judgments, len(c.requests), app_requests) == (1, 1, 0)


def labelled_again(db):
    with db.connect() as conn:
        ids = {s.name: s.id for s in queries.profile_skills(conn)}
    write(db, userdata.set_link_override, "CI/CD", ids["GitHub Actions"], "specific")
    write(db, userdata.set_link_override, "Git", ids["serverless CI/CD"], "related")
    write(db, userdata.set_link_override, "Written communication", ids["Communication"], "general")
    write(db, userdata.set_link_override, "Vector databases", None)


def test_measurement_reused_and_fresh_judges_again(labelled):
    db, _ = labelled
    c = client(relations_answer("specific", "none"))
    _, first = measure(db, c, [expand.STEP])
    expansions = len(c.requests) - first.new_judgments
    assert expansions == 9 and first.new_judgments > 0
    c2 = client(relations_answer("specific", "none"))
    _, again = measure(db, c2, [expand.STEP])
    assert (again.new_judgments, c2.requests) == (0, [])
    c3 = client(relations_answer("specific", "none"))
    _, fresh = measure(db, c3, [expand.STEP], fresh=True)
    assert fresh.new_judgments == first.new_judgments and c3.calls("phrases") == 0  # expansions are reused


# --- Candidate finding and judging measures (5.2) ---


def test_a_missed_candidate_and_the_sweep(labelled):
    db, ids = labelled
    _, report = measure(db, client(relations_answer("specific", "none")))
    git = by_key(report.results[0], "git")
    # Git's right skill serverless CI/CD is 4th of 5 at 0.12: outside a shortlist of 2 at floor 0.5
    assert (git.shortlisted, git.rank, git.similarity) == (False, 4, 0.12)
    text = link_eval.format_text(report)
    assert "missed: Git -> serverless CI/CD (rank 4, similarity 0.12)" in text
    table = link_eval.sweep(report.retrievals[0], report.plan.reference)
    cell = next(c for c in table if c["size"] == 3 and c["floor"] == 0.60)
    assert cell["shortlisted"] == 2 and len(table) == len(link_eval.SWEEP_SIZES) * len(link_eval.SWEEP_FLOORS)


def test_judging_on_its_own_shortlist_and_right_skill_added(labelled):
    db, ids = labelled

    def answer(user):
        # Written communication: no link although Communication is a candidate; Git: related to serverless CI/CD
        if "Posting skill: Written communication" in user:
            return relations_answer("none", "none")
        if "Posting skill: Git" in user and "serverless CI/CD" in user:
            return {"relations": [{"candidate": n, "relation": "related"} for n, line in enumerate(
                [row for row in user.splitlines() if row[:1].isdigit()], start=1) if "serverless" in line]}
        return (
            relations_answer("specific", "none") if "Posting skill: CI/CD" in user else relations_answer("none", "none")
        )

    _, report = measure(db, client(answer))
    result = report.results[0]
    assert by_key(result, "written communication").outcome() == "refused"
    git = by_key(result, "git")
    assert git.outcome() == "not_found" and git.outcome(with_added=True) == "right"
    assert result.counts()["not_found"] == 1 and result.counts(with_added=True)["not_found"] == 0
    assert result.counts()["right"] == 1 and result.counts(with_added=True)["right"] == 2
    assert result.kept == 1  # Vector databases: none to all its candidates


# --- Verdicts and differences (5.2) ---


@pytest.mark.parametrize("fixed,broke,expected", [
    (0, 0, "same"),
    (5, 0, "better"),  # p = 1/32
    (0, 5, "worse"),
    (4, 0, "within noise"),  # p = 1/16: four flips can happen by chance
    (8, 1, "better"),  # p = 9/256
    (6, 1, "within noise"),  # p = 7/64
    (3, 3, "within noise"),
])
def test_verdicts(fixed, broke, expected):
    assert link_eval.Comparison(fixed, broke).verdict == expected


def test_comparing_posting_skill_by_posting_skill(labelled):
    db, _ = labelled

    def first(user):
        return (
            relations_answer("specific", "none") if "Posting skill: CI/CD" in user else relations_answer("none", "none")
        )

    def second(user):
        # CI/CD lost, Vector databases' refusal broken: two broken, none fixed
        return relations_answer("related", "none")

    _, base = measure(db, client(first))
    _, other = measure(db, client(second), fresh=True)
    comparison = link_eval.compare(base.results[0], other.results[0])
    assert (comparison.fixed, comparison.broke, comparison.verdict) == (0, 2, "within noise")
    assert comparison.describe() == "within noise (fixed 0, broke 2, p=0.25)"


def test_tied_with_yours(labelled):
    db, ids = labelled
    write(db, userdata.set_link_override, "CI/CD", ids["Docker"], "specific")
    # GitHub Actions and Docker both specific: GitHub Actions wins on shortlist order
    _, report = measure(db, client(relations_answer("specific", "specific")))
    assert by_key(report.results[0], "ci/cd").outcome() == "tied"
    assert report.results[0].counts()["tied"] == 1


def test_combinations_compared_with_differences(labelled):
    db, _ = labelled

    def answer(user):
        return (
            relations_answer("specific", "none")
            if "Posting skill: CI/CD" in user
            else relations_answer("related", "none")
        )

    c = client(answer)
    _, report = measure(db, c, judges=["link-judge@6", "link-judge@5"])
    assert [r.combo.judge for r in report.results] == ["link-judge@5", "link-judge@6"]  # the app's comes first
    assert link_eval.verdict(report.results[0], report.results[1]) == "same"
    data = json.loads(link_eval.report_json(report))
    entry = next(e for e in data["per_posting_skill"] if e["key"] == "ci/cd")
    assert entry["user"]["relation"] == "specific"
    assert entry["combinations"]["names + link-judge@5"]["link"]["name"] == "GitHub Actions"
    assert data["combinations"][1]["verdict"] == "same"


def test_previewing_a_candidate_method(labelled):
    db, _ = labelled
    mark(db, SIMILAR, "Jenkins", "Design")
    VECTORS["Jenkins"] = axis(1, 0.1, 0)
    try:
        _, report = measure(db, client(relations_answer("specific", "none")), all_skills=True)
    finally:
        del VECTORS["Jenkins"]
    [result] = report.results
    assert set(result.preview) == {"jenkins"} and result.preview["jenkins"].link is not None
    assert "preview: 1 of 1 posting skills linked, 1 differ from the app's links" in link_eval.format_text(report)


# --- Kept apart from the app (5.3) ---


def test_measuring_doesnt_change_links(labelled):
    db, ids = labelled
    write(db, userdata.clear_link_override, "Git")
    judge(db, client(relations_answer("related", "none")))  # the app's own judgment of Git
    app_link = link_of(db, "git")
    write(db, userdata.set_link_override, "Git", ids["serverless CI/CD"], "related")
    _, report = measure(db, client(relations_answer("same", "same")), judges=["link-judge@6"])
    assert report.new_judgments > 0
    with db.connect() as conn:
        assert conn.execute(select(func.count()).select_from(link_measurements)).scalar_one() == report.new_judgments
        assert links.plan(conn, EMBED) == []
    write(db, userdata.clear_link_override, "Git")
    assert link_of(db, "git") == app_link
    with db.connect() as conn:
        assert {links.judge_of(j.pipeline) for j in conn.execute(select(link_judgments))} == {"link-judge@5"}


# --- `jobhunt eval --links` (5.4) ---


@pytest.fixture
def links_db(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'links.db'}"
    engine = make_engine(url)
    init_db(engine)
    ai = add_posting(engine, "senior-ai-engineer.json")
    write(engine, userdata.set_setting, "llm.model", "gemma4:12b")
    mark(engine, ai, "CI/CD", "Design")
    [actions] = profile(engine, "GitHub Actions")
    write(engine, userdata.set_link_override, "CI/CD", actions, "specific")
    engine.dispose()
    return url


def use_client(monkeypatch, c):
    monkeypatch.setattr("jobhunt.enrich.ollama.OllamaClient", lambda url: c)
    return c


def test_cli_measures_links(links_db, monkeypatch, capsys):
    c = use_client(monkeypatch, client(relations_answer("specific")))
    assert main(["eval", "--links", "--db", links_db]) == 0
    out, err = capsys.readouterr()
    assert "judging requests for names + link-judge@5: up to 2" in err  # no vectors yet: an upper bound
    assert "right skill, right relation" in out and c.calls("relations") == 1


def test_cli_dry_run_makes_no_request(links_db, monkeypatch, capsys):
    c = use_client(monkeypatch, client())
    assert main(["eval", "--links", "--retrieval", expand.STEP, "--dry-run", "--db", links_db]) == 0
    assert "expansion requests: 2" in capsys.readouterr().err and c.requests == [] and c.embed_requests == []


@pytest.mark.parametrize("argv,message", [
    (["--judge", "link-judge@9"], "available: link-judge@5, link-judge@6"),
    (["--retrieval", "words"], "available: names, skill-expand@1"),
    (["--skills", "atomic@2"], "can't be used with --links"),
    (["--segmenter", "rules"], "can't be used with --links"),
])
def test_cli_refusals(links_db, monkeypatch, capsys, argv, message):
    c = use_client(monkeypatch, client())
    assert main(["eval", "--links", *argv, "--db", links_db]) == 1
    assert message in capsys.readouterr().err and c.requests == []


def test_cli_link_options_need_links(links_db, capsys):
    assert main(["eval", "--dry-run", "--db", links_db]) == 1
    assert "need --links" in capsys.readouterr().err


def test_cli_no_overrides(links_db, monkeypatch, capsys):
    engine = make_engine(links_db)
    write(engine, userdata.clear_link_override, "CI/CD")
    engine.dispose()
    c = use_client(monkeypatch, client())
    assert main(["eval", "--links", "--db", links_db]) == 1
    assert "links set on the links page" in capsys.readouterr().err and c.requests == []


def test_cli_unreachable_after_stating_requests(links_db, monkeypatch, capsys):
    use_client(monkeypatch, client(state="offline"))
    engine = make_engine(links_db)
    write(engine, userdata.set_setting, "llm.embed_model", "nomic-embed-text:latest")
    engine.dispose()
    assert main(["eval", "--links", "--db", links_db]) == 1
    err = capsys.readouterr().err
    assert "judging requests for names + link-judge@5: up to 2" in err and "Ollama is unreachable" in err


def test_cli_no_embedding_model(links_db, monkeypatch, capsys):
    use_client(monkeypatch, client(models=[]))
    assert main(["eval", "--links", "--db", links_db]) == 1
    assert "no embedding model" in capsys.readouterr().err


def test_link_measurement_instead_of_extraction(links_db, monkeypatch, capsys):
    c = use_client(monkeypatch, client(relations_answer("specific")))
    assert main(["eval", "--links", "--json", "--db", links_db]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["reference"]["links"] == 1 and c.calls("lines") == 0 and c.calls("skills") == 0
    engine = make_engine(links_db)
    with engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(skill_expansions)).scalar_one() == 0
    engine.dispose()
