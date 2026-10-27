"""Match credits and scores, posting ranking and skill gains (pure functions), and recommendations from a database."""

import math
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from jobhunt import queries, recommend, userdata
from jobhunt.db import DERIVED_TABLES, OPERATIONAL_TABLES, USER_TABLES
from jobhunt.enrich import derived
from jobhunt.enrich.links import PIPELINE, Candidate, Planned
from jobhunt.recommend import credit, pool, rank_postings, score, skill_gains

from .conftest import add_posting
from .test_userdata import write

BANK, SIMILAR, AI = 1, 2, 3  # keys in the order the db fixture imports them
SEEN = datetime(2026, 10, 1, tzinfo=UTC)


def opt(skill_id, relation):
    return {"skill_id": skill_id, "relation": relation}


def asks(*skills):
    """Posting skills from (name, importance) pairs; the key is the casefolded name."""
    return [{"key": name.casefold(), "name": name, "importance": importance, "source": "suggestion"}
            for name, importance in skills]


def posting(job_id, interest=None, days_ago=0, dismissed=False, applied=False):
    return {
        "job_id": job_id,
        "title": f"Posting {job_id}",
        "interest": interest,
        "last_seen_at": SEEN - timedelta(days=days_ago),
        "dismissal_id": 1 if dismissed else None,
        "application_id": 1 if applied else None,
    }


# --- Credit (2.1) ---


def test_same_skill_at_a_level():
    assert credit([opt(1, "same")], {1: "proficient"}) == 0.85


def test_best_credit_not_strongest_relation():
    fine_tuning, llms = 1, 2
    options = [opt(fine_tuning, "general"), opt(llms, "related")]  # strongest first, as effective_links gives them
    assert credit(options, {fine_tuning: "missing", llms: "proficient"}) == pytest.approx(0.255)


def test_no_link():
    assert credit([], {1: "expert"}) == 0


# --- Score (2.2) ---


THREE = asks(("Python", "required"), ("AWS", "required"), ("Docker", "preferred"))
THREE_OPTIONS = {"python": [opt(1, "same")], "aws": [], "docker": [opt(2, "general")]}
THREE_CREDITS = {"python": 0.85, "aws": 0.0, "docker": 0.6}


def test_three_skills():
    match = score(THREE, THREE_CREDITS, THREE_OPTIONS)
    assert match["score"] == pytest.approx(0.46)
    assert (match["skills"], match["unlinked"]) == (3, 1)
    assert [g["name"] for g in match["gaps"]] == ["AWS", "Docker", "Python"]  # weighted loss: 2, 0.4, 0.3


def test_gaps_required_first_on_a_tie_and_at_most_three():
    skills = asks(("Rust", "preferred"), ("Go", "required"), ("SQL", "preferred"), ("Java", "preferred"))
    credits = {"go": 0.5}  # required: loses 2 × 0.5 = 1, as each unlinked preferred skill does
    gaps = score(skills, credits, {})["gaps"]
    assert [g["name"] for g in gaps] == ["Go", "Java", "Rust"]


def test_posting_without_skills():
    assert score([], {}, {})["score"] is None


# --- Posting ranking (2.3) ---


def test_interest_lifts_a_posting():
    a, b = asks(("Python", "required"), ("Rust", "required")), asks(("Go", "required"), ("SQL", "required"))
    credits = {"python": 1.0, "go": 1.0, "sql": 0.2}
    ranked, _ = rank_postings([posting("B"), posting("A", interest=5)], {"A": a, "B": b}, credits, {})
    assert [(r["job_id"], round(r["value"], 2)) for r in ranked] == [("A", 0.83), ("B", 0.6)]


def test_ties_newest_last_seen_first():
    skills = {job: asks(("Python", "required")) for job in "ABC"}
    rows = [posting("A", days_ago=3), posting("B", days_ago=1), posting("C", days_ago=2)]
    ranked, _ = rank_postings(rows, skills, {"python": 0.5}, {})
    assert [r["job_id"] for r in ranked] == ["B", "C", "A"]


def test_dismissed_and_applied_postings():
    rows = [posting("A", dismissed=True), posting("B", applied=True), posting("C"), posting("D")]
    skills = {job: asks(("Python", "required")) for job in "ABC"}
    ranked, no_skills = rank_postings(rows, skills, {"python": 0.5}, {})
    assert [r["job_id"] for r in ranked] == ["C"] and no_skills == 1  # D has no skills


# --- Skill gains (2.4) ---


def gains(rows, skills_by_job, options, profile):
    levels = {skill_id: s["level"] for skill_id, s in profile.items()}
    credits = {key: credit(o, levels) for key, o in options.items()}
    ranked, _ = rank_postings(rows, skills_by_job, credits, options)
    return {c["name"]: c for c in skill_gains(ranked, skills_by_job, credits, options, profile)}


def test_asked_for_more_often():
    profile = {1: {"name": "Python", "level": "proficient"}, 2: {"name": "Go", "level": "expert"}}
    ab = asks(("Python", "required"), ("AWS", "required"), ("SQL", "preferred"))  # scores 0.46, as above
    c = asks(("Python", "required"), ("Docker", "preferred"), ("SQL", "preferred"))
    options = {"python": [opt(1, "same")], "aws": [], "docker": [], "sql": [opt(2, "general")]}
    found = gains([posting("A"), posting("B"), posting("C")], {"A": ab, "B": ab, "C": c}, options, profile)
    assert list(found) == ["AWS", "Docker"]  # Python and Go are proficient or better, SQL has a link
    assert round(found["AWS"]["gain"] * 100) == 68 and found["AWS"]["improved"] == 2  # +0.34 in A and B
    assert round(found["Docker"]["gain"] * 100) == 21 and found["Docker"]["improved"] == 1  # +0.85 / 4 in C
    assert (found["AWS"]["key"], found["AWS"]["skill_id"], found["AWS"]["level"]) == ("aws", None, None)


def test_gain_weighted_by_interest_and_postings_most_improved_first():
    skills_by_job = {"A": asks(("AWS", "required"), ("SQL", "required")), "B": asks(("AWS", "required"))}
    found = gains([posting("A", interest=5), posting("B", interest=1)], skills_by_job, {"aws": [], "sql": []}, {})
    aws = found["AWS"]
    assert aws["gain"] == pytest.approx(0.425 * 5 / 3 + 0.85 / 3)
    assert [p["job_id"] for p in aws["postings"]] == ["B", "A"]  # B rises 0.85, A 0.425


def test_variants_grouped_under_a_missing_skill():
    profile = {1: {"name": "AWS", "level": "missing"}}
    skills_by_job = {"A": asks(("AWS", "required")), "B": asks(("Amazon Bedrock", "required"))}
    options = {"aws": [opt(1, "same")], "amazon bedrock": [opt(1, "general")]}
    found = gains([posting("A"), posting("B")], skills_by_job, options, profile)
    assert list(found) == ["AWS"]
    assert (found["AWS"]["skill_id"], found["AWS"]["level"], found["AWS"]["improved"]) == (1, "missing", 2)
    assert found["AWS"]["gain"] == pytest.approx(0.85 + 0.51)


def test_skill_already_proficient():
    profile = {1: {"name": "Python", "level": "proficient"}, 2: {"name": "Rust", "level": "expert"}}
    skills_by_job = {"A": asks(("Python", "required"), ("Rust", "preferred"))}
    options = {"python": [opt(1, "same")], "rust": [opt(2, "same")]}
    assert gains([posting("A")], skills_by_job, options, profile) == {}


def test_profile_skill_without_postings_has_no_gain():
    profile = {1: {"name": "Kubernetes", "level": "learning"}}
    assert gains([posting("A")], {"A": asks(("Python", "required"))}, {"python": []}, profile).keys() == {"Python"}


# --- Pooling unlinked skills (pool-unlinked-skills 1.1) ---


BASE = [1.0, 0.0, 0.0]


def toward(cosine):
    """A unit vector at exactly `cosine` to BASE."""
    return [cosine, math.sqrt(1 - cosine * cosine), 0.0]


def pools(asked, vectors):
    """pool() over {name: postings asking}, keyed by name; vectors by name."""
    counts = {name.casefold(): n for name, n in asked.items()}
    names = {name.casefold(): name for name in asked}
    leaders = pool(counts, names, {name.casefold(): v for name, v in vectors.items()})
    return {names[key]: names[leader] for key, leader in leaders.items()}


def test_one_name_inside_another():
    found = pools({"fine-tuning": 9, "LLM fine-tuning": 4}, {"fine-tuning": BASE, "LLM fine-tuning": toward(0.857)})
    assert found == {"fine-tuning": "fine-tuning", "LLM fine-tuning": "fine-tuning"}


def test_containment_only_when_the_leaders_words_are_inside():
    # Asked more, `LLM fine-tuning` leads, and its words aren't all in `fine-tuning`: 0.857 is too low alone.
    found = pools({"LLM fine-tuning": 9, "fine-tuning": 4}, {"LLM fine-tuning": BASE, "fine-tuning": toward(0.857)})
    assert found == {"LLM fine-tuning": "LLM fine-tuning", "fine-tuning": "fine-tuning"}


def test_similar_names():
    vectors = {"Azure": BASE, "Microsoft Azure": toward(0.957)}
    assert pools({"Azure": 2, "Microsoft Azure": 5}, vectors) == {"Microsoft Azure": "Microsoft Azure",
                                                                  "Azure": "Microsoft Azure"}


def test_a_shared_word_is_not_enough():
    found = pools({"Planning": 6, "Sprint planning": 2}, {"Planning": BASE, "Sprint planning": toward(0.78)})
    assert found == {"Planning": "Planning", "Sprint planning": "Sprint planning"}


def test_pools_dont_chain():
    orchestration = toward(0.92)
    # 0.85 to Kubernetes, 0.92 to Container orchestration: y solves 0.85 × 0.92 + y × orchestration[1] = 0.92
    y = (0.92 - 0.85 * 0.92) / orchestration[1]
    containers = [0.85, y, math.sqrt(1 - 0.85 ** 2 - y ** 2)]
    assert math.sumprod(containers, orchestration) == pytest.approx(0.92)
    found = pools({"Kubernetes": 5, "Container orchestration": 3, "Containers": 2},
                  {"Kubernetes": BASE, "Container orchestration": orchestration, "Containers": containers})
    assert found == {"Kubernetes": "Kubernetes", "Container orchestration": "Kubernetes", "Containers": "Containers"}


def test_joins_the_most_similar_qualifying_pool():
    a, b = BASE, [0.0, 1.0, 0.0]
    c = [0.93, 0.0, math.sqrt(1 - 0.93 ** 2)]  # 0.93 to `a`, 0 to `b`
    near_b = [0.0, 0.95, math.sqrt(1 - 0.95 ** 2)]
    found = pools({"Alpha": 5, "Beta": 4, "Gamma": 3, "Delta": 2}, {"Alpha": a, "Beta": b, "Gamma": c, "Delta": near_b})
    assert found == {"Alpha": "Alpha", "Beta": "Beta", "Gamma": "Alpha", "Delta": "Beta"}


def test_a_key_without_a_vector_is_alone():
    found = pools(
        {"fine-tuning": 9, "Fine tuning": 4, "LLM fine-tuning": 2}, {"fine-tuning": BASE, "LLM fine-tuning": BASE}
    )
    assert found == {"fine-tuning": "fine-tuning", "Fine tuning": "Fine tuning", "LLM fine-tuning": "fine-tuning"}


def test_equal_word_lists_pool():
    found = pools(
        {"fine-tuning": 3, "Fine tuning": 2, "Knowledge graph": 3, "Knowledge graphs": 2},
        {"fine-tuning": BASE, "Fine tuning": toward(0.85),
         "Knowledge graph": [0.0, 1.0, 0.0], "Knowledge graphs": [0.0, 0.85, math.sqrt(1 - 0.85 ** 2)]},
    )
    assert found == {"fine-tuning": "fine-tuning", "Fine tuning": "fine-tuning",
                     "Knowledge graph": "Knowledge graph", "Knowledge graphs": "Knowledge graph"}


def test_pooling_order():
    same = {name: BASE for name in ("Big", "Bigger", "abd", "abc")}
    # most asked first; then shorter name (Big before Bigger); then key (abc before abd)
    assert list(pools({"Bigger": 1, "abd": 1, "Big": 1, "abc": 1}, same)) == ["abc", "abd", "Big", "Bigger"]
    assert list(pools({"Bigger": 2, "abd": 1, "Big": 1, "abc": 1}, same)) == ["Bigger", "abc", "abd", "Big"]
    assert set(pools({"Bigger": 2, "abd": 1, "Big": 1, "abc": 1}, same).values()) == {"Bigger"}


# --- Pooled skill gains (pool-unlinked-skills 1.2) ---


def test_pooled_gain_counts_every_members_postings():
    skills_by_job = {
        "A": asks(("fine-tuning", "required")), "B": asks(("fine-tuning", "required")),
        "C": asks(("LLM fine-tuning", "required"), ("Python", "required")),
    }
    options = {"fine-tuning": [], "llm fine-tuning": [], "python": [opt(1, "same")]}
    profile = {1: {"name": "Python", "level": "proficient"}}
    levels = {1: "proficient"}
    credits = {key: credit(o, levels) for key, o in options.items()}
    ranked, _ = rank_postings([posting("A"), posting("B"), posting("C")], skills_by_job, credits, options)
    vectors = {"fine-tuning": BASE, "llm fine-tuning": toward(0.857)}
    found = skill_gains(ranked, skills_by_job, credits, options, profile, vectors)
    assert [(c["key"], c["name"], c["also"], c["improved"]) for c in found] == [
        ("fine-tuning", "fine-tuning", ["LLM fine-tuning"], 3)
    ]
    assert found[0]["gain"] == pytest.approx(0.85 + 0.85 + 0.85 / 2)


def test_linked_skills_are_not_pooled():
    profile = {1: {"name": "Docker", "level": "proficient"}}
    skills_by_job = {"A": asks(("Docker", "required")), "B": asks(("Containerization", "required"))}
    options = {"docker": [opt(1, "same")], "containerization": []}
    credits = {"docker": 0.85, "containerization": 0.0}
    ranked, _ = rank_postings([posting("A"), posting("A2"), posting("B")], skills_by_job | {"A2": skills_by_job["A"]},
                              credits, options)
    vectors = {"docker": BASE, "containerization": toward(0.95)}
    found = skill_gains(ranked, skills_by_job | {"A2": skills_by_job["A"]}, credits, options, profile, vectors)
    assert [(c["name"], c["also"]) for c in found] == [("Containerization", [])]


def test_without_vectors_every_unlinked_skill_is_its_own_candidate():
    skills_by_job = {"A": asks(("fine-tuning", "required")), "B": asks(("LLM fine-tuning", "required"))}
    found = gains([posting("A"), posting("B")], skills_by_job, {"fine-tuning": [], "llm fine-tuning": []}, {})
    assert {name: c["also"] for name, c in found.items()} == {"fine-tuning": [], "LLM fine-tuning": []}


# --- Workplace choice (filter-insights-by-workplace 1.1) ---


@pytest.mark.parametrize("values, chosen", [
    ([], None),
    (["On-site", "Hybrid", "Remote"], None),
    (["Remote", "Hybrid"], {"Remote", "Hybrid"}),
    (["Remote", "Moon"], {"Remote"}),
    (["Moon"], None),
    (["Remote", "Remote"], {"Remote"}),
])
def test_workplace_choice(values, chosen):
    assert recommend.workplace_choice(values) == (None if chosen is None else frozenset(chosen))


# --- From the database (2.5) ---


@pytest.fixture
def db(engine):
    assert add_posting(engine, "data-automation.json") == BANK
    assert add_posting(engine, "innovation-lab.json") == SIMILAR
    assert add_posting(engine, "senior-ai-engineer.json") == AI
    return engine


def mark(engine, job, name, importance="required", quote="Design"):
    return write(engine, userdata.add_skill_mark, job, name, quote, importance=importance)


def store_judgment(engine, key, name, relations):
    """A succeeded judgment of the current method relating `key` to profile skills {skill_id: relation}."""
    item = Planned(key, name, None, [Candidate(skill_id, f"skill {skill_id}", 0.9) for skill_id in relations])
    with engine.begin() as conn:
        derived.save_judgment(conn, item, "gemma4:12b", "nomic-embed-text:latest", PIPELINE, "succeeded", None,
                              relations, {})


def counts(engine):
    with engine.connect() as conn:
        return {t.name: conn.execute(select(func.count()).select_from(t)).scalar_one()
                for t in USER_TABLES + DERIVED_TABLES + OPERATIONAL_TABLES}


def test_recommendations_from_the_database(db):
    python = write(db, userdata.add_profile_skill, "Python", "proficient")
    mlops = write(db, userdata.add_profile_skill, "MLOps", "learning")
    mark(db, BANK, "Python")
    mark(db, BANK, "AWS")
    mark(db, SIMILAR, "Python")
    mark(db, SIMILAR, "Kubeflow", "preferred")
    store_judgment(db, "kubeflow", "Kubeflow", {mlops: "general", python: "related"})

    before = counts(db)
    with db.connect() as conn:
        found = recommend.recommendations(conn)
    assert counts(db) == before

    # SIMILAR: (2 × 0.85 + max(0.6 × 0.25, 0.3 × 0.85)) / 3; BANK: 2 × 0.85 / 4
    assert [(p["job_id"], round(p["score"], 3)) for p in found["postings"]] == [(SIMILAR, 0.652), (BANK, 0.425)]
    assert (found["considered"], found["no_skills"]) == (2, 1)
    # AWS: BANK rises 2 × 0.85 / 4; MLOps at proficient: Kubeflow's credit becomes 0.6 × 0.85, so SIMILAR rises
    # (0.51 − 0.255) / 3. Python is proficient already, and Kubeflow has links: neither is a candidate.
    assert [s["name"] for s in found["skills"]] == ["AWS", "MLOps"]
    assert [s["gain"] for s in found["skills"]] == [pytest.approx(0.425), pytest.approx(0.085)]
    assert found["skills"][1]["skill_id"] == mlops and found["skills"][1]["postings"][0]["job_id"] == SIMILAR
    assert found["postings"][1]["url"] and found["postings"][1]["gaps"][0]["name"] == "AWS"
    assert found["has_posting_skills"] and found["has_profile_skills"]


def test_nothing_to_recommend(db):
    with db.connect() as conn:
        found = recommend.recommendations(conn)
    assert (found["postings"], found["skills"], found["has_posting_skills"], found["has_profile_skills"]) == (
        [], [], False, False
    )


# --- Pooling from the database (pool-unlinked-skills 2.1) ---


def fine_tuning_variants(engine):
    """Python in the profile, `fine-tuning` marked on BANK and `LLM fine-tuning` on SIMILAR, and their stored name
    vectors (not unit length: recommendations normalizes them)."""
    write(engine, userdata.add_profile_skill, "Python", "proficient")
    mark(engine, BANK, "fine-tuning")
    mark(engine, SIMILAR, "LLM fine-tuning")
    with engine.begin() as conn:
        derived.save_embeddings(conn, "nomic-embed-text:latest", {
            "fine-tuning": [3 * x for x in BASE], "llm fine-tuning": [2 * x for x in toward(0.857)],
        })


def test_stored_vectors_pool_marked_variants(db):
    fine_tuning_variants(db)
    store_judgment(db, "llm fine-tuning", "LLM fine-tuning", {})  # judged, no relation: still unlinked
    before = counts(db)
    with db.connect() as conn:
        found = recommend.recommendations(conn)
    assert counts(db) == before
    assert [(s["name"], s["also"], s["improved"]) for s in found["skills"]] == [
        ("fine-tuning", ["LLM fine-tuning"], 2)
    ]
    assert found["skills"][0]["gain"] == pytest.approx(0.85 + 0.85)  # each posting's only skill


def test_no_stored_judgment_nothing_pooled(db):
    fine_tuning_variants(db)
    with db.connect() as conn:
        assert queries.latest_embed_model(conn) is None
        found = recommend.recommendations(conn)
    assert sorted((s["name"], s["also"]) for s in found["skills"]) == [("LLM fine-tuning", []), ("fine-tuning", [])]


# --- Workplace filter from the database (filter-insights-by-workplace 1.2) ---
# BANK is On-site; SIMILAR and AI are Hybrid.


def found_under(engine, workplaces):
    with engine.connect() as conn:
        return recommend.recommendations(conn, frozenset(workplaces) if workplaces is not None else None)


def test_workplace_filter_narrows_the_postings(db):
    write(db, userdata.add_profile_skill, "Python", "proficient")
    mark(db, BANK, "Python")
    mark(db, BANK, "Kubernetes")
    mark(db, SIMILAR, "Python")

    everything = found_under(db, None)
    assert [p["job_id"] for p in everything["postings"]] == [SIMILAR, BANK]
    assert (everything["considered"], everything["no_skills"], everything["workplaces"]) == (2, 1, None)
    assert [s["name"] for s in everything["skills"]] == ["Kubernetes"]

    hybrid = found_under(db, {"Hybrid"})
    assert [p["job_id"] for p in hybrid["postings"]] == [SIMILAR]
    assert (hybrid["considered"], hybrid["no_skills"]) == (1, 1)  # AI has no skills
    assert hybrid["skills"] == [] and hybrid["workplaces"] == {"Hybrid"}

    on_site = found_under(db, {"On-site"})
    assert (on_site["considered"], on_site["no_skills"]) == (1, 0)


def test_skill_gain_from_filtered_postings_only(db):
    write(db, userdata.add_profile_skill, "Python", "proficient")
    mark(db, BANK, "AWS")
    mark(db, AI, "AWS")
    assert [(s["name"], s["improved"]) for s in found_under(db, None)["skills"]] == [("AWS", 2)]
    hybrid = found_under(db, {"Hybrid"})["skills"]
    assert [(s["name"], s["improved"]) for s in hybrid] == [("AWS", 1)]
    assert hybrid[0]["gain"] == pytest.approx(0.85) and hybrid[0]["postings"][0]["job_id"] == AI


def test_posting_without_a_workplace_type(db):
    write(db, userdata.add_profile_skill, "Python", "proficient")
    mark(db, AI, "Python")
    add_posting(db, "senior-ai-engineer.json", captured_at=SEEN, tag="no type", workplace_type=None)
    everything = found_under(db, None)
    assert [(p["job_id"], p["workplace_type"]) for p in everything["postings"]] == [(AI, None)]
    assert found_under(db, {"Hybrid"})["considered"] == 0


# --- Posting summary (summarize-posting-skills 1.2, 1.3) ---


def test_best_option_is_the_best_credit():
    fine_tuning, llms = 1, 2
    options = [opt(fine_tuning, "general"), opt(llms, "related")]
    assert recommend.best_option(options, {fine_tuning: "missing", llms: "proficient"}) == opt(llms, "related")
    assert recommend.best_option([opt(1, "same"), opt(2, "same")], {1: "familiar", 2: "familiar"}) == opt(1, "same")
    assert recommend.best_option([], {}) is None


def summary_of(engine, job_id):
    with engine.connect() as conn:
        return recommend.posting_summary(conn, job_id)


def names(groups):
    return [(g["importance"], [e["name"] for e in g["entries"]]) for g in groups]


def test_summary_have_and_dont_have(db):
    python = write(db, userdata.add_profile_skill, "Python", "proficient")
    containers = write(db, userdata.add_profile_skill, "Containers", "expert")
    mark(db, BANK, "Python")
    mark(db, BANK, "AWS")
    mark(db, BANK, "Docker", "preferred")
    store_judgment(db, "aws", "AWS", {})
    store_judgment(db, "docker", "Docker", {containers: "general"})
    found = summary_of(db, BANK)
    assert round(found["score"]["score"], 2) == 0.46
    assert names(found["have"]) == [("required", ["Python"]), ("preferred", ["Docker"])]
    [[python_entry], [docker_entry]] = [g["entries"] for g in found["have"]]
    assert (python_entry["skill_id"], python_entry["relation"], python_entry["level"], python_entry["same"]) == (
        python, "same", "proficient", True)
    assert (docker_entry["skill_id"], docker_entry["skill_name"], docker_entry["relation"], docker_entry["level"]) == (
        containers, "Containers", "general", "expert")
    assert names(found["dont_have"]) == [("required", ["AWS"])]
    assert found["dont_have"][0]["entries"][0]["reason"] == "no-link"
    assert (found["have_count"], found["dont_have_count"], found["has_profile_skills"]) == (2, 1, True)
    with db.connect() as conn:
        insights = {p["job_id"]: p for p in recommend.recommendations(conn)["postings"]}
    assert insights[BANK]["score"] == found["score"]["score"]


def test_summary_credit_from_a_weaker_link(db):
    fine_tuning = write(db, userdata.add_profile_skill, "LLM fine-tuning", "missing")
    llms = write(db, userdata.add_profile_skill, "Large language models", "proficient")
    mark(db, BANK, "LoRA")
    store_judgment(db, "lora", "LoRA", {fine_tuning: "general", llms: "related"})
    [group] = summary_of(db, BANK)["have"]
    [entry] = group["entries"]
    assert (entry["skill_id"], entry["skill_name"], entry["relation"], entry["same"]) == (
        llms,
        "Large language models",
        "related",
        False,
    )


def test_summary_linked_only_to_missing_skills(db):
    kubernetes = write(db, userdata.add_profile_skill, "Kubernetes", "missing")
    mark(db, BANK, "Kubernetes")
    found = summary_of(db, BANK)
    assert found["have"] == []
    [entry] = found["dont_have"][0]["entries"]
    assert (entry["reason"], entry["skill_id"], entry["skill_name"]) == ("missing", kubernetes, "Kubernetes")


def test_summary_not_judged_then_no_link(db):
    write(db, userdata.add_profile_skill, "Python", "proficient")
    mark(db, BANK, "Terraform", "required")
    mark(db, BANK, "Ansible", "required")
    write(db, userdata.set_link_override, "Ansible", None)
    entries = {e["name"]: e["reason"] for g in summary_of(db, BANK)["dont_have"] for e in g["entries"]}
    assert entries == {"Ansible": "no-link", "Terraform": "not-judged"}
    store_judgment(db, "terraform", "Terraform", {})
    entries = {e["name"]: e["reason"] for g in summary_of(db, BANK)["dont_have"] for e in g["entries"]}
    assert entries["Terraform"] == "no-link"


def test_summary_groups_and_order(db):
    write(db, userdata.add_profile_skill, "Python", "proficient")
    write(db, userdata.add_profile_skill, "Go", "learning")
    mark(db, BANK, "Go", None)
    mark(db, BANK, "Python", "required")
    mark(db, BANK, "Rust", "preferred")
    found = summary_of(db, BANK)
    assert names(found["have"]) == [("required", ["Python"]), (None, ["Go"])]
    assert names(found["dont_have"]) == [("preferred", ["Rust"])]


def test_summary_without_skills(db):
    found = summary_of(db, BANK)
    assert found["score"]["score"] is None and found["have"] == [] and found["dont_have"] == []
    assert found["has_profile_skills"] is False
