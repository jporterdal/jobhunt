"""Web tests for the profile page and its actions, the suggestions and rejections pages, the links page, document
"Add to profile", the skills page's levels and the queue's subjects."""

import re

import pytest
from sqlalchemy import func, select

from jobhunt import queries, userdata
from jobhunt.db import (
    USER_TABLES,
    claim_records,
    claims,
    highlight_claims,
    highlights,
    llm_jobs,
    profile_details,
    profile_rejections,
    record_lines,
    record_sources,
    records,
    skill_aliases,
    skill_link_overrides,
    skills,
)
from jobhunt.enrich import cv, jobs, links
from jobhunt.enrich.ollama import ModelInfo

from .conftest import add_posting, get, post
from .fakes import FakeOllama
from .test_cv_pipeline import CV_TEXT
from .test_documents import make_odt, odt_paragraphs
from .test_profile import rows
from .test_profile_jobs import model_client
from .test_profile_suggestions import add_run, cl, rec
from .test_userdata import write
from .test_web_llm import make_client, text

BANK, SIMILAR, AI = 1, 2, 3  # keys in the order the three fixture imports them


@pytest.fixture
def three(engine):
    assert add_posting(engine, "data-automation.json") == BANK
    assert add_posting(engine, "innovation-lab.json") == SIMILAR
    assert add_posting(engine, "senior-ai-engineer.json") == AI
    write(engine, userdata.set_setting, "llm.model", "gemma4:12b")
    return engine


@pytest.fixture
def ollama():
    return FakeOllama()


@pytest.fixture
def client(three, tmp_path, ollama):
    return make_client(three, tmp_path, ollama)


def skill_id(engine, key):
    with engine.connect() as conn:
        return conn.execute(select(skills.c.id).where(skills.c.key == key)).scalar_one()


def counts(engine):
    with engine.connect() as conn:
        return {
            t.name: conn.execute(select(func.count()).select_from(t)).scalar_one() for t in USER_TABLES + (llm_jobs,)
        }


def a_profile(engine):
    """Details, two projects, two terms of a course and a degree; seven skills at three levels, two ungrounded; a
    highlight; a private record and a context link."""
    write(engine, userdata.add_detail, "name", "Jane Doe")
    write(engine, userdata.add_detail, "contact", "jane@example.com", "Email")
    ids = {}
    for key, kind, title, start, end in (
        ("parking", "project", "city-parking", None, "2026"), ("tidyplots", "project", "tidyplots", None, "2024"),
        ("fall", "course", "COMP 1000", "2026-09", "2026-12"), ("winter", "course", "COMP 1000", "2026-01", "2026-04"),
        ("phd", "degree", "PhD Computer Science", None, "2022"),
    ):
        ids[key] = write(
            engine, userdata.add_record, {"kind": kind, "title": title, "start_date": start, "end_date": end}
        )
    write(engine, userdata.add_line, ids["parking"], "Technologies: Python, Flask")
    write(engine, userdata.add_source, ids["parking"], "https://github.com/janedoe/city-parking")
    write(engine, userdata.set_disclosure, ids["tidyplots"], "private")
    write(engine, userdata.set_part_of, ids["tidyplots"], ids["phd"])
    for name, level, grounds in (
        ("Python", "expert", ("parking", "tidyplots")),
        ("Flask", "proficient", ("parking",)),
        ("Teaching", "proficient", ("fall", "winter")),
        ("NumPy", "proficient", ()),
        ("Leadership", "familiar", ()),
        ("AWS", "missing", ()),
        ("Docker", "familiar", ("parking",)),
    ):
        sid = write(engine, userdata.add_profile_skill, name, level)
        for g in grounds:
            write(engine, userdata.add_ground, sid, ids[g], name)
    highlight = write(engine, userdata.add_highlight, "8+ years experience with Python (incl. NumPy)")
    write(engine, userdata.add_coverage, highlight, skill_id(engine, "python"), "Python")
    write(engine, userdata.add_coverage, highlight, skill_id(engine, "numpy"), "NumPy")
    return ids


def block(html, start, end="</li>"):
    at = html.index(start)
    return html[at:html.index(end, at)]


# --- The profile page (7.1) ---


def test_viewing_the_profile(client, three):
    ids = a_profile(three)
    html = text(get(client, "/profile"))
    assert re.findall(r"<h3>(\w+) <span", html) == ["course", "project", "degree"]
    assert html.index(f'id="record-{ids["fall"]}"') < html.index(f'id="record-{ids["winter"]}"')
    assert html.index(f'id="record-{ids["parking"]}"') < html.index(f'id="record-{ids["tidyplots"]}"')
    assert re.findall(r"<h3>(\w+)</h3>", html) == ["expert", "proficient", "familiar", "missing"]
    assert html.count('id="skill-') == 7
    assert html.count(">ungrounded</span>") == 2  # NumPy and Leadership; AWS is at missing
    assert ">no highlight</span>" in block(html, f'id="skill-{skill_id(three, "docker")}"')
    assert ">no highlight</span>" not in block(html, f'id="skill-{skill_id(three, "numpy")}"')
    assert "5 records (2 course, 2 project, 1 degree)" in " ".join(html.split())
    assert "7 skills, 2 ungrounded" in html and "1 highlight" in html
    tidyplots = block(html, f'id="record-{ids["tidyplots"]}"', "<details")
    assert '<span class="small private">private</span>' in tidyplots
    assert f'Part of <a href="#record-{ids["phd"]}">PhD Computer Science (2022)</a>' in tidyplots
    assert 'href="https://github.com/janedoe/city-parking"' in html and "Technologies: Python, Flask" in html
    assert re.search(r'action="/profile/sources/\d+/edit"', html)
    assert "Jane Doe" in html and "Email:" in html
    assert cv.PART_OF_GUIDELINE in html  # on the part-of form
    assert 'aria-current="page"' in html[html.index('href="/profile"') - 5:html.index('href="/profile"') + 40]


def test_private_through_context_and_lost_context_shown(client, three):
    project = write(three, userdata.add_record, {"kind": "project", "title": "secret", "disclosure": "private"})
    award = write(three, userdata.add_record, {"kind": "award", "title": "an award"})
    write(three, userdata.set_part_of, award, project)
    assert "private through its context" in text(get(client, "/profile"))
    write(three, userdata.delete_record, project)
    html = text(get(client, "/profile"))
    assert "lost-context" in block(html, f'id="record-{award}"', "</details>")


def test_profile_get_pages_are_read_only(client, three):
    a_profile(three)
    add_run(three, write(three, userdata.add_document, *_stored()), [rec("ml_basics")], [cl("Keras")])
    before = counts(three)
    for path in ("/profile", "/profile/suggestions", "/profile/rejections", "/profile/links",
                 "/profile/suggestions?kind=record&accepted=3"):
        assert get(client, path).status_code == 200
    assert counts(three) == before


def _stored(label="CV", kind="cv", sha="d" * 64):
    from jobhunt.documents import StoredFile

    return StoredFile(sha, 10, "cv.odt", "application/vnd.oasis.opendocument.text", "text", "extracted"), label, kind


def test_empty_profile_points_at_documents(client):
    html = text(get(client, "/profile"))
    assert "Upload your CV" in html and "Suggestions (0)" in html


def test_detail_actions(client, three):
    assert (
        post(client, "/profile/details", {"kind": "headline", "text": "PhD Computer Science"})
        .headers["Location"]
        .endswith("#detail-1")
    )
    [d] = rows(three, profile_details)
    post(client, f"/profile/details/{d.id}/edit", {"kind": "contact", "label": "Email", "text": "jane@example.com"})
    assert (rows(three, profile_details)[0].kind, rows(three, profile_details)[0].label) == ("contact", "Email")
    assert post(client, f"/profile/details/{d.id}/delete").headers["Location"].endswith("#details")
    assert rows(three, profile_details) == []
    assert post(client, "/profile/details", {"kind": "hobby", "text": "chess"}).status_code == 400


def test_record_actions(client, three):
    response = post(client, "/profile/records", {"kind": "project", "title": "city-parking", "disclosure": "public"})
    [r] = rows(three, records)
    assert response.status_code == 303 and response.headers["Location"].endswith(f"#record-{r.id}")
    post(
        client,
        f"/profile/records/{r.id}/edit",
        {"kind": "event", "title": "parking hackathon", "start_date": "2026-09", "ongoing": "1"},
    )
    assert (rows(three, records)[0].kind, rows(three, records)[0].start_date, rows(three, records)[0].ongoing) == (
        "event",
        "2026-09",
        True,
    )
    post(client, f"/profile/records/{r.id}/disclosure", {"disclosure": "private"})
    assert rows(three, records)[0].disclosure == "private"
    other = write(three, userdata.add_record, {"kind": "award", "title": "Best Design"})
    assert (
        post(client, f"/profile/records/{other}/part-of", {"part_of_id": str(r.id)})
        .headers["Location"]
        .endswith(f"#record-{other}")
    )
    assert {x.id: x.part_of_id for x in rows(three, records)}[other] == r.id
    assert post(client, f"/profile/records/{r.id}/part-of", {"part_of_id": str(other)}).status_code == 400  # a cycle
    assert post(client, f"/profile/records/{r.id}/delete").headers["Location"].endswith("#records")
    assert rows(three, records)[0].context_lost_at is not None
    post(client, f"/profile/records/{other}/dismiss-lost-context")
    assert rows(three, records)[0].context_lost_at is None
    assert post(client, "/profile/records", {"kind": "project"}).status_code == 400


def test_line_and_source_actions(client, three):
    parking = write(three, userdata.add_record, {"kind": "project", "title": "city-parking"})
    for line in ("first", "second"):
        assert (
            post(client, f"/profile/records/{parking}/lines", {"text": line})
            .headers["Location"]
            .endswith(f"#record-{parking}")
        )
    first, second = rows(three, record_lines)
    assert (
        post(client, f"/profile/lines/{second.id}/move", {"direction": "up", "record_id": parking})
        .headers["Location"]
        .endswith(f"#record-{parking}")
    )
    assert [ln.text for ln in sorted(rows(three, record_lines), key=lambda ln: ln.position)] == ["second", "first"]
    post(client, f"/profile/lines/{first.id}/edit", {"text": "first, edited", "record_id": parking})
    post(client, f"/profile/lines/{second.id}/delete", {"record_id": parking})
    assert [ln.text for ln in rows(three, record_lines)] == ["first, edited"]
    post(client, f"/profile/records/{parking}/sources", {"url": "https://github.com/x/parking", "kind": ""})
    [source] = rows(three, record_sources)
    assert source.kind == "repo"
    post(
        client,
        f"/profile/sources/{source.id}/edit",
        {"url": "https://parking.example.org", "kind": "site", "record_id": parking},
    )
    assert rows(three, record_sources)[0].url == "https://parking.example.org"
    post(client, f"/profile/sources/{source.id}/delete", {"record_id": parking})
    assert rows(three, record_sources) == []


def test_skill_ground_and_alias_actions(client, three):
    parking = write(three, userdata.add_record, {"kind": "project", "title": "city-parking"})
    assert post(client, "/profile/skills", {"name": "Python", "level": "expert"}).status_code == 303
    python = skill_id(three, "python")
    assert (
        post(client, f"/profile/skills/{python}/grounds", {"record_id": str(parking), "quote": ""})
        .headers["Location"]
        .endswith(f"#skill-{python}")
    )
    [ground] = rows(three, claim_records)
    assert ground.quote == "city-parking"
    assert post(client, f"/profile/skills/{python}/grounds", {"record_id": ""}).status_code == 400
    post(client, f"/profile/skills/{python}/grounds/{parking}/remove")
    assert rows(three, claim_records) == []
    post(client, "/profile/skills", {"name": "Python 3", "level": "proficient"})
    py3 = skill_id(three, "python 3")
    assert (
        post(client, f"/profile/skills/{py3}/merge", {"into": str(python)})
        .headers["Location"]
        .endswith(f"#skill-{python}")
    )
    assert [(a.alias_key, a.skill_id) for a in rows(three, skill_aliases)] == [("python 3", python)]
    assert "Also: Python 3" in text(get(client, "/profile"))
    post(client, "/profile/aliases/remove", {"alias_key": "python 3", "skill_id": str(python)})
    assert rows(three, skill_aliases) == []
    post(client, f"/profile/skills/{python}/rename", {"name": "Python (language)"})
    post(client, f"/skills/{python}/level", {"level": "proficient", "next": "/profile"})
    assert rows(three, claims)[0].level == "proficient"
    assert post(client, f"/profile/skills/{python}/remove").headers["Location"].endswith("#skills")
    assert rows(three, claims) == []


def test_highlight_actions(client, three):
    post(client, "/profile/skills", {"name": "CI/CD", "level": "familiar"})
    cicd = skill_id(three, "ci/cd")
    response = post(client, "/profile/highlights", {"text": "Familiar with CI/CD"})
    [h] = rows(three, highlights)
    assert response.headers["Location"].endswith(f"#highlight-{h.id}")
    post(client, f"/profile/highlights/{h.id}/coverage", {"skill_id": str(cicd), "quote": "CI/CD"})
    assert [(c.claim_id, c.quote) for c in rows(three, highlight_claims)] == [(rows(three, claims)[0].id, "CI/CD")]
    post(client, f"/profile/highlights/{h.id}/edit", {"text": "Familiar with serverless CI/CD"})
    post(client, f"/profile/highlights/{h.id}/coverage/{cicd}/remove")
    assert rows(three, highlight_claims) == []
    assert post(client, f"/profile/highlights/{h.id}/delete").headers["Location"].endswith("#highlights")
    assert rows(three, highlights) == []


def test_htmx_edit_returns_the_page_main(client, three):
    response = post(
        client,
        "/profile/records",
        {"kind": "project", "title": "Projects"},
        headers={"HX-Request": "true"},
        follow_redirects=True,
    )
    assert response.status_code == 200 and "<main>" in text(response) and "Projects" in text(response)


def new_post_routes(app):
    """Every POST route of the profile pages and "Add to profile", with placeholder ids filled in."""
    out = []
    for rule in app.url_map.iter_rules():
        if "POST" not in rule.methods:
            continue
        if not (rule.endpoint.startswith("profile.") or rule.endpoint == "applications.add_to_profile"):
            continue
        out.append(re.sub(r"<int:\w+>", "1", rule.rule))
    return out


def test_every_new_post_route_checks_origin(three, tmp_path):
    from jobhunt.web import create_app

    app = create_app(
        three, tmp_path / "inbox", tmp_path / "documents", host="127.0.0.1", port=8000, ollama=FakeOllama()
    )
    app.config["TESTING"] = True
    client = app.test_client()
    a_profile(three)
    routes = new_post_routes(app)
    assert len(routes) >= 35
    before = counts(three)
    for url in routes:
        assert post(client, url, {"name": "x", "text": "x"}, origin=None).status_code == 403, url
        assert post(client, url, {"name": "x", "text": "x"}, origin="http://evil.example").status_code == 403, url
    assert counts(three) == before


# --- Suggestions (7.2) and rejections (7.3) ---


@pytest.fixture
def suggested(three):
    doc = write(three, userdata.add_document, *_stored())
    add_run(
        three,
        doc,
        [rec("city-parking", lines=["Technologies: Flask"]), rec("ml_basics")],
        [cl("Flask", grounds=[(0, "Flask")]), cl("(1+1)-ES")],
        part_of=[(1, 0)],
        highlights_=["Familiar with Flask"],
    )
    return three


def test_suggestions_page_lists_four_groups(client, suggested):
    html = text(get(client, "/profile/suggestions"))
    groups = re.findall(r'id="group-(\w+)"', html)
    assert groups == ["record", "claim", "part_of", "highlight"]
    assert "Accept all (2)" in block(html, 'id="group-record"', "</section>")
    assert "1 ground waiting for records" in html and "Technologies: Flask" in html and "CV" in html
    assert "Accept all" not in block(html, 'id="group-part_of"', "</section>")  # waits for both records


def test_accepting_and_rejecting_from_the_page(client, suggested):
    with suggested.connect() as conn:
        found = queries.profile_suggestions(conn)
    flask = next(o for o in found["claim"] if o["name"] == "Flask")
    es = next(o for o in found["claim"] if o["name"] == "(1+1)-ES")
    response = post(client, f"/profile/suggestions/{flask['id']}/accept")
    assert response.status_code == 303 and response.headers["Location"].endswith("/profile/suggestions#group-claim")
    assert rows(suggested, claims)[0].level_origin == "model"
    post(client, f"/profile/suggestions/{es['id']}/reject", {"kind": "claim"})
    assert [r.label for r in rows(suggested, profile_rejections)] == ["(1+1)-ES"]
    assert post(client, f"/profile/suggestions/{es['id']}/accept").status_code == 400  # no longer offered


def test_accept_all_reports_the_count(client, suggested):
    response = post(client, "/profile/suggestions/accept-all", {"kind": "record"}, follow_redirects=True)
    html = text(response)
    assert "Accepted 2 record suggestions." in html and len(rows(suggested, records)) == 2
    assert "Accept all (1)" in block(html, 'id="group-part_of"', "</section>")  # now both records exist
    assert post(client, "/profile/suggestions/accept-all", {"kind": "everything"}).status_code == 400


def test_nothing_to_review(client, suggested):
    for kind in ("record", "claim", "part_of", "highlight", "claim", "highlight"):
        post(client, "/profile/suggestions/accept-all", {"kind": kind})
    assert 'id="nothing"' in text(get(client, "/profile/suggestions"))
    assert "Suggestions (0)" in text(get(client, "/profile"))


def test_rejections_page_lists_and_forgets(client, three):
    write(three, userdata.add_profile_skill, "Chain", "familiar")
    post(client, f"/profile/skills/{skill_id(three, 'chain')}/remove")
    [rejection] = rows(three, profile_rejections)
    html = text(get(client, "/profile/rejections"))
    assert f'id="rejection-{rejection.id}"' in html and "Chain" in html
    assert post(client, f"/profile/rejections/{rejection.id}/forget").status_code == 303
    assert rows(three, profile_rejections) == []
    assert get(client, "/profile/history").status_code == 404


def test_links_page_states_stale_overrides(client, three):
    docker = write(three, userdata.add_profile_skill, "Docker", "proficient")
    podman = write(three, userdata.add_profile_skill, "Podman", "proficient")
    write(three, userdata.set_link_override, "containers", docker, "general")
    write(three, userdata.set_link_override, "oci", podman, "related")
    write(three, userdata.remove_profile_skill, podman)
    assert "1 of your links is stale" in text(get(client, "/profile/links"))


# --- Links (unchanged) ---


def test_most_asked_skills_first(client, three):
    for job in (BANK, SIMILAR, AI):
        write(three, userdata.add_skill_mark, job, "Python", "Design")
    write(three, userdata.add_skill_mark, AI, "Dask", "Design")
    html = text(get(client, "/profile/links"))
    assert html.index("Python") < html.index("Dask")
    assert re.search(r"Python</td>\s*<td class=\"postings-count\">3</td>", html)


def test_link_override_actions(client, three):
    write(three, userdata.add_skill_mark, AI, "MLOps", "Design")
    post(client, "/profile/skills", {"name": "Docker", "level": "proficient"})
    docker = skill_id(three, "docker")
    post(client, "/profile/links/override", {"posting_skill": "mlops", "skill": str(docker), "relation": "related"})
    html = text(get(client, "/profile/links"))
    assert "<strong>Docker</strong>" in html and ">yours<" in html
    post(client, "/profile/links/override", {"posting_skill": "mlops", "skill": "none"})
    [override] = rows_of(three, skill_link_overrides)
    assert override.skill_id is None
    post(client, "/profile/links/clear", {"posting_skill": "mlops"})
    assert rows_of(three, skill_link_overrides) == []
    assert post(client, "/profile/links/override", {"posting_skill": "mlops", "skill": "?"}).status_code == 400


def rows_of(engine, table):
    with engine.connect() as conn:
        return conn.execute(select(table)).all()


def test_rejudge_all(client, three):
    write(three, userdata.add_profile_skill, "Docker", "proficient")
    write(three, jobs.cancel_all)
    assert post(client, "/profile/links/rejudge").status_code == 303
    queued = [j for j in rows_of(three, llm_jobs) if j.status == "queued"]
    assert [(j.kind, j.pipeline) for j in queued] == [("links", links.PIPELINE + links.ALL_SCOPE)]


def test_no_embedding_model_notice(three, tmp_path):
    client = make_client(three, tmp_path, FakeOllama(models=[ModelInfo("gemma4:12b", "d1", 1, ("completion",))]))
    assert "No embedding model is installed" in text(get(client, "/profile/links"))
    client = make_client(three, tmp_path, FakeOllama())
    assert 'id="links-notice"' not in text(get(client, "/profile/links"))


def test_profile_skill_shows_linked_posting_skills(client, three):
    write(three, userdata.add_skill_mark, AI, "python", "Python")
    write(three, userdata.add_skill_mark, BANK, "Python", "Design")
    write(three, userdata.set_skill_level, skill_id(three, "python"), "expert")
    html = text(get(client, "/profile"))
    assert "Postings ask for:" in html and "python (2)" in html  # named as the first mark typed it


# --- Existing pages (9.3) and uploads (8.2) ---


def upload(client, data, filename, kind, label=""):
    from io import BytesIO

    return post(client, "/documents", {"file": (BytesIO(data), filename), "kind": kind, "label": label},
                content_type="multipart/form-data")


def document_jobs(engine):
    return [j for j in rows_of(engine, llm_jobs) if j.kind == "document"]


def test_uploading_a_cv_queues_its_extraction(client, three):
    response = upload(client, make_odt(odt_paragraphs(*CV_TEXT.split("\n"))), "cv.odt", "cv")
    assert response.status_code == 303
    [job] = document_jobs(three)
    assert (job.status, job.model) == ("queued", "gemma4:12b")


def test_adding_another_document(client, three):
    upload(client, make_odt(odt_paragraphs("SKILLS", "Rust and Go")), "notes.odt", "other", "Notes")
    assert document_jobs(three) == []
    with three.connect() as conn:
        from jobhunt.db import documents

        doc_id = conn.execute(select(documents.c.id)).scalar_one()
    html = text(get(client, f"/documents/{doc_id}"))
    assert "Add to profile" in html and "disabled" not in html[html.index('id="profile"'):html.index("Add to profile")]
    assert post(client, f"/documents/{doc_id}/add-to-profile").status_code == 303
    assert len(document_jobs(three)) == 1


def test_document_without_text(client, three):
    upload(client, b"\x89PNG\r\n\x1a\n" + b"\x00" * 32, "photo.png", "cv")
    assert document_jobs(three) == []
    html = text(get(client, "/documents/1"))
    assert "Add to profile" not in html and "Only a document with extracted text" in html
    assert post(client, "/documents/1/add-to-profile").status_code == 400


def test_add_to_profile_disabled_while_offline(three, tmp_path):
    client = make_client(three, tmp_path, FakeOllama("offline"))
    upload(client, b"SKILLS\nRust", "notes.txt", "other")
    html = text(get(client, "/documents/1"))
    assert re.search(r"<button type=\"submit\" disabled[^>]*>Add to profile", html)
    assert post(client, "/documents/1/add-to-profile").status_code == 400
    assert document_jobs(three) == []


def test_document_page_counts_its_suggestions(client, three):
    upload(client, make_odt(odt_paragraphs(*CV_TEXT.split("\n"))), "cv.odt", "other")
    write(three, jobs.enqueue_document, 1)
    assert jobs.run_next(three, model_client()) == "done"
    html = text(get(client, "/documents/1"))
    assert "Latest extraction: done" in html and "suggestions to review" in html and "Merged" not in html


def test_setting_a_level(client, three):
    write(three, userdata.add_skill_mark, BANK, "Kubernetes", "Design")
    write(three, userdata.add_skill_mark, AI, "kubernetes", "Design")
    response = post(
        client, f"/skills/{skill_id(three, 'kubernetes')}/level", {"level": "missing", "next": f"/postings/{BANK}"}
    )
    assert response.status_code == 303
    for job in (BANK, AI):
        assert "<option selected>missing</option>" in text(get(client, f"/postings/{job}"))
    html = text(get(client, "/profile"))
    assert '<h3>missing</h3>' in html and "Kubernetes" in html


def test_skills_page_levels_and_membership(client, three):
    for job in (BANK, SIMILAR, AI):
        write(three, userdata.add_skill_mark, job, "PyTorch", "Design")
    write(three, userdata.set_rating, BANK, "interest", 4)
    write(three, userdata.set_rating, AI, "interest", 5)
    write(three, userdata.add_skill_mark, BANK, "Dask", "Design")
    write(three, userdata.set_skill_level, skill_id(three, "pytorch"), "familiar")
    html = text(get(client, "/skills"))
    row = html[html.index(">PyTorch<"):html.index("</tr>", html.index(">PyTorch<"))]
    assert re.search(r'postings-count">3<', row) and re.search(r'high-count">2<', row) and "in profile" in row
    options = re.findall(r"<option[^>]*>(\w+)</option>", row)
    assert options == ["unset", "missing", "learning", "familiar", "proficient", "expert"]
    dask = html[html.index(">Dask<"):html.index("</tr>", html.index(">Dask<"))]
    assert "in profile" not in dask


def test_queue_shows_each_jobs_subject(client, three):
    write(three, jobs.enqueue, BANK)
    upload(client, make_odt(odt_paragraphs(*CV_TEXT.split("\n"))), "cv.odt", "cv", "CV v3")
    client_model = model_client()
    for _ in range(2):
        jobs.run_next(three, client_model)
    with three.connect() as conn:
        offer = queries.profile_suggestions(conn)["claim"][0]
    post(client, f"/profile/suggestions/{offer['id']}/accept")  # queues link judging
    jobs.run_next(three, client_model)
    html = text(get(client, "/llm/queue"))
    subjects = re.findall(r'<a href="([^"]+)"[^>]*>([^<]+)</a>', html)
    assert [href for href, _ in subjects] == ["/profile/links", "/documents/1", f"/postings/{BANK}#model-says"]
    assert [label for _, label in subjects][:2] == ["skill links", "CV v3"]
