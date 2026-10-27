"""Flask test-client tests: skeleton, guard, browsing postings, import action, triage UI."""

import gzip
import re
import shutil
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from jobhunt import userdata
from jobhunt.db import captures, claims, dismiss_reasons, posting_skill_marks, posting_tags, posting_triage, skills

from .conftest import BASE_URL, add_posting, get, post, posting_file

BANK, SIMILAR, AI, ECON = 1, 2, 3, 4  # keys in the order the three fixture (then ECON) imports them
URLS = {
    BANK: "https://jobs.example.com/view/A-1001",
    SIMILAR: "https://careers.example.org/jobs/1002",
    AI: "https://jobs.example.com/view/A-1003",
    ECON: "https://careers.example.org/jobs/1004",
}


def at(day: int) -> datetime:
    return datetime(2026, 9, day, 15, 0, tzinfo=UTC)


@pytest.fixture
def three(engine):
    assert add_posting(engine, "data-automation.json", captured_at=at(20)) == BANK
    assert add_posting(engine, "innovation-lab.json", captured_at=at(21)) == SIMILAR
    assert add_posting(engine, "senior-ai-engineer.json", captured_at=at(22)) == AI
    return engine


def text(response) -> str:
    return response.get_data(as_text=True)


def write(engine, fn, *args, **kwargs):
    with engine.begin() as conn:
        return fn(conn, *args, **kwargs)


def count(engine, table):
    with engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(table)).scalar_one()


def reason_id(engine, key):
    with engine.connect() as conn:
        return conn.execute(select(dismiss_reasons.c.id).where(dismiss_reasons.c.key == key)).scalar_one()


def row_order(html: str) -> list[int]:
    return [int(k) for k in re.findall(r'<tr class="[^"]*" data-job-id="(\d+)"', html)]


# --- Skeleton (6.1) ---


def test_home_renders_with_navigation(client):
    html = text(get(client, "/"))
    for section in ("Postings", "Applications", "Companies", "Skills", "Insights"):
        assert f">{section}</a>" in html
    assert "htmx.min.js" in html and "app.css" in html
    assert "No postings yet" in html


def test_no_demo_label_on_real_data(client):
    assert "Demo data" not in text(get(client, "/"))


def test_demo_label_shows_on_demo_databases(engine, client):
    from jobhunt.userdata import set_setting

    write(engine, set_setting, "demo.created_at", at(1))
    for path in ("/", "/profile", "/no/such/page"):
        assert 'class="demo-label"' in text(get(client, path))


def test_unknown_url_is_404(client):
    response = get(client, "/no/such/page")
    assert response.status_code == 404 and "Not found" in text(response)


def test_static_assets_served(client):
    assert get(client, "/static/htmx.min.js").status_code == 200
    css = text(get(client, "/static/app.css"))
    assert all(name in css for name in (".src-captured", ".src-user", ".src-derived"))


@pytest.mark.parametrize("path", ["/", "/insights", "/skills", "/applications", "/companies", "/documents"])
def test_every_page_renders(client, three, path):
    assert get(client, path).status_code == 200


# --- Guard (6.2) ---


def test_wrong_host_rejected(client):
    assert client.get("/", headers={"Host": "attacker.example:8000"}).status_code == 403
    assert client.get("http://attacker.example:8000/").status_code == 403


def test_loopback_names_accepted(client):
    for host in ("127.0.0.1:8000", "localhost:8000", "[::1]:8000"):
        assert client.get("/", headers={"Host": host}).status_code == 200


def test_cross_origin_post_rejected_without_change(client, three):
    response = post(client, f"/postings/{BANK}/tags", {"name": "pwned"}, origin="http://evil.example")
    assert response.status_code == 403
    assert count(three, posting_tags) == 0


def test_post_without_origin_or_referer_rejected(client, three):
    response = post(client, f"/postings/{BANK}/tags", {"name": "ml"}, origin=None)
    assert response.status_code == 403
    assert count(three, posting_tags) == 0


def test_post_with_same_origin_referer_accepted(client, three):
    response = post(client, f"/postings/{BANK}/tags", {"name": "ml"}, origin=None, headers={"Referer": f"{BASE_URL}/"})
    assert response.status_code == 303
    assert count(three, posting_tags) == 1


def test_same_origin_post_succeeds(client, three):
    assert post(client, f"/postings/{BANK}/tags", {"name": "ml"}).status_code == 303
    assert count(three, posting_tags) == 1


# --- Posting list (7.1) ---


def test_list_default_order_and_links(client, three):
    html = text(get(client, "/"))
    assert row_order(html) == [AI, SIMILAR, BANK]
    for url in (URLS[AI], URLS[SIMILAR], URLS[BANK]):
        assert (
            f'<a class="original-link" href="{url}" target="_blank" rel="noopener noreferrer">Original posting ↗</a>'
            in html
        )


def test_filtered_url(client, three):
    write(three, userdata.set_rating, BANK, "interest", 4)
    write(three, userdata.set_rating, AI, "interest", 2)
    html = text(get(client, "/?q=example&min_interest=3"))
    assert row_order(html) == [BANK]
    assert 'value="example"' in html  # the URL state is shown in the controls


def test_htmx_list_refresh_returns_rows_only(client, three):
    response = get(client, "/?workplace=On-site", headers={"HX-Request": "true", "HX-Target": "posting-rows"})
    html = text(response)
    assert "<html" not in html and row_order(html) == [BANK]


def test_filter_form_pushes_url(client):
    html = text(get(client, "/"))
    assert 'hx-push-url="true"' in html and 'hx-target="#posting-rows"' in html


def test_dismissed_hidden_by_default(client, three):
    write(three, userdata.dismiss, SIMILAR, [reason_id(three, "other")])
    assert row_order(text(get(client, "/"))) == [AI, BANK]
    assert row_order(text(get(client, "/?dismissed=only"))) == [SIMILAR]


# --- Posting detail (7.2) ---


def test_detail_page(client, three):
    html = text(get(client, f"/postings/{BANK}"))
    assert "Analytics Manager, Reporting Automation (Example City)" in html
    assert "Example Bank" in html and "Example City, EX" in html
    assert "This role drives data automation" in html
    assert "2026-09-20 15:00 UTC" in html  # first and last seen
    assert 'href="https://jobs.example.com/view/A-1001" target="_blank"' in html
    assert 'class="panel src-captured"' in html and 'class="panel src-user"' in html


def test_detail_unknown_job_is_404(client, three):
    assert get(client, "/postings/123").status_code == 404
    assert get(client, "/postings/abc").status_code == 404
    assert get(client, "/postings/A-1001").status_code == 404  # an external ID is not a key
    assert post(client, "/postings/abc/tags", {"name": "ml"}).status_code == 404


def test_detail_shows_source_external_id_and_details(client, three):
    html = text(get(client, f"/postings/{BANK}"))
    assert "<th>Source</th><td>jobs.example.com</td><th>External ID</th><td>A-1001</td>" in html
    assert "<th>Reposted</th><td colspan=\"3\">yes</td>" in html
    assert "<th>Apply method</th><td colspan=\"3\">external</td>" in html
    assert "<th>Applicants</th><td colspan=\"3\">30 applicants</td>" in html  # a volatile detail
    assert '<span class="kind-label">imported</span>' in html


def test_original_posting_link_on_every_posting_page(client, three):
    link = (
        f'<a class="original-link" href="{URLS[BANK]}" target="_blank" rel="noopener noreferrer">Original posting ↗</a>'
    )
    app_id = write(three, userdata.start_application, BANK)
    for url in (f"/postings/{BANK}", "/applications", f"/applications/{app_id}", f"/postings/{BANK}/cv"):
        assert link in text(get(client, url)), url
    for url in ("/", f"/postings/{BANK}", "/applications", f"/postings/{BANK}/cv", "/insights", "/applications/new"):
        assert "linked" + "in" not in text(get(client, url)).lower(), url


def test_capture_download_is_original_bytes(client, three):
    with three.connect() as conn:
        capture = conn.execute(select(captures).where(captures.c.job_id == BANK)).one()
    html = text(get(client, f"/postings/{BANK}"))
    url = f"/postings/{BANK}/captures/{capture.id}"
    assert url in html
    response = get(client, url)
    assert response.status_code == 200
    assert response.data == gzip.decompress(capture.raw_gz)
    assert b'"external_id": "A-1001"' in response.data
    assert "attachment" in response.headers["Content-Disposition"]
    assert get(client, f"/postings/{AI}/captures/{capture.id}").status_code == 404


def test_description_markup_rendered_but_notes_escaped(client, three):
    write(three, userdata.set_notes, BANK, "<script>alert(1)</script>")
    html = text(get(client, f"/postings/{BANK}"))
    assert "<strong>What will you do?</strong>" in html
    assert "<script>alert(1)</script>" not in html


# --- Snapshot diff (7.3) ---


def test_diff_offered_and_rendered(client, engine):
    base = "Intro paragraph.\nOld requirement.\nClosing paragraph."
    add_posting(engine, captured_at=at(20), description_text=base)
    add_posting(engine, captured_at=at(25), tag="b", description_text=base.replace("Old", "New"))
    html = text(get(client, f"/postings/{BANK}"))
    assert "Show differences" in html
    ids = re.findall(r'name="old" value="(\d+)"', html)
    response = get(client, f"/postings/{BANK}/diff?old={ids[0]}&new={ids[1]}")
    diff = text(response)
    assert response.status_code == 200
    assert '<div class="delete">− Old requirement.</div>' in diff
    assert '<div class="insert">+ New requirement.</div>' in diff
    assert '<div class="equal">  Intro paragraph.</div>' in diff


def test_no_diff_for_single_snapshot(client, three):
    html = text(get(client, f"/postings/{BANK}"))
    assert "Show differences" not in html and "/diff" not in html


# --- Import action (7.4) ---


def test_import_from_browser(web, engine, tmp_path):
    app, client = web
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    shutil.copyfile(posting_file("data-automation.json"), inbox / "new.json")
    (inbox / "bad.html").write_text("<html><body>A saved page no parser reads</body></html>")

    html = text(post(client, "/import"))
    assert re.search(r'<td>new</td>\s*<td class="small">new.json</td>', html)
    assert f'href="/postings/{BANK}"' in html
    assert 'class="original-link" href="https://jobs.example.com/view/A-1001" target="_blank"' in html
    assert "Original posting ↗" in html
    assert re.search(r"<td>rejected</td>\s*<td class=\"small\">bad.html</td>", html)
    assert "not recognised by any installed parser (" in html and "posting-file@1" in html
    assert not (inbox / "new.json").exists() and not (inbox / "bad.html").exists()
    assert (inbox / "processed" / "new.json").exists() and (inbox / "rejected" / "bad.html").exists()


def test_import_missing_inbox(client, engine, tmp_path):
    response = post(client, "/import")
    assert response.status_code == 404
    assert f"Inbox folder not found: {tmp_path / 'inbox'}" in text(response)


def test_import_is_post_only(client):
    assert get(client, "/import").status_code == 405


# --- Insights: recommendations and answers (add-recommendations 3.1, 3.2) ---


def test_detail_without_model_output(client, three):
    html = text(get(client, f"/postings/{BANK}"))
    assert 'class="panel src-derived" id="model-says"' in html and "No model output for this posting yet" in html


def table(html: str, name: str) -> str:
    start = html.index(f'<table class="{name}">')
    return html[start:html.index("</table>", start)]


def table_row(html: str, marker: str) -> str:
    at = html.index(marker)
    return html[html.rindex("<tr", 0, at):html.index("</tr>", at)]


def test_recommendations_shown(client, three):
    write(three, userdata.add_profile_skill, "Python", "proficient")
    write(three, userdata.add_skill_mark, BANK, "Python", "Design", importance="required")
    write(three, userdata.add_skill_mark, BANK, "Kubernetes", "Design", importance="preferred")
    html = text(get(client, "/insights"))
    postings_table, skills_table = table(html, "recommended-postings"), table(html, "recommended-skills")
    row = table_row(postings_table, f'data-job-id="{BANK}"')
    assert f'href="/postings/{BANK}"' in row and f'class="original-link" href="{URLS[BANK]}"' in row
    assert ">57%<" in row and "1 of 2" in row and "Kubernetes" in row  # 2 × 0.85 / 3
    assert "2 postings without skills" in html
    kubernetes = table_row(skills_table, "<td>Kubernetes</td>")
    assert ">+28<" in kubernetes  # 0.85 / 3
    assert "Have it" in kubernetes and "Don’t have it" in kubernetes and f'href="/postings/{BANK}"' in kubernetes
    assert "<td>Python</td>" not in skills_table  # proficient already
    assert "Nothing to recommend" not in html


def test_empty_profile(client, three):
    write(three, userdata.add_skill_mark, BANK, "Kubernetes", "Design", importance="required")
    html = text(get(client, "/insights"))
    assert "Your profile has no skills yet" in html and 'href="/profile"' in html
    assert "No posting has skills yet" not in html and "recommended-postings" not in html


def test_no_posting_skills(client, three):
    write(three, userdata.add_profile_skill, "Python", "proficient")
    html = text(get(client, "/insights"))
    assert "No posting has skills yet" in html and "Your profile has no skills yet" not in html


def suggest_aws(engine):
    """A profile skill, and AWS on the AI posting as a suggestion only (no skills row)."""
    from .conftest import add_run

    write(engine, userdata.add_profile_skill, "Python", "proficient")
    add_run(engine, AI, skills=[("AWS", "required", "AWS")])


def test_dont_have_it_for_a_suggestion(client, three):
    from jobhunt.db import llm_jobs

    suggest_aws(three)
    write(three, userdata.set_setting, "llm.model", "gemma4:12b")
    assert 'value="AWS"' in table(text(get(client, "/insights")), "recommended-skills")
    response = post(client, "/insights/skill", {"name": "AWS", "level": "missing"})
    assert response.status_code == 303 and response.headers["Location"].endswith("/insights")
    with three.connect() as conn:
        aws = conn.execute(
            select(claims).join(skills, skills.c.id == claims.c.skill_id).where(skills.c.key == "aws")
        ).one()
        kinds = conn.execute(select(llm_jobs.c.kind, llm_jobs.c.status)).all()
    assert (aws.level, aws.level_origin) == ("missing", "user")
    assert ("links", "queued") in kinds
    row = table_row(table(text(get(client, "/insights")), "recommended-skills"), "<td>AWS</td>")
    assert "<option selected>missing</option>" in row and "Have it" not in row  # now a profile skill at missing


def test_have_it_at_a_level(client, three):
    suggest_aws(three)
    post(client, "/insights/skill", {"name": "AWS", "level": "familiar"})
    html = text(get(client, "/insights"))
    assert ">50%<" in table_row(table(html, "recommended-postings"), f'data-job-id="{AI}"')  # credit 0.5
    assert "<option selected>familiar</option>" in table_row(table(html, "recommended-skills"), "<td>AWS</td>")


def test_answer_rejects_bad_input(client, three):
    suggest_aws(three)
    for data in ({"name": "AWS", "level": "guru"}, {"name": "AWS", "level": ""}, {"name": "  ", "level": "missing"}):
        assert post(client, "/insights/skill", data).status_code == 400
    assert count(three, skills) == 1  # Python only


def test_answer_cross_origin_rejected(client, three):
    response = post(client, "/insights/skill", {"name": "AWS", "level": "missing"}, origin="http://evil.example")
    assert response.status_code == 403 and count(three, skills) == 0


def pool_fine_tuning(engine):
    """Python in the profile, `fine-tuning` marked on BANK and `LLM fine-tuning` on AI, Kubernetes on SIMILAR, and
    stored name vectors from one judgment's model: the two fine-tuning names pool (0.857, one inside the other)."""
    from jobhunt.enrich import derived
    from jobhunt.enrich.links import PIPELINE, Planned

    write(engine, userdata.add_profile_skill, "Python", "proficient")
    write(engine, userdata.add_skill_mark, BANK, "fine-tuning", "Design", importance="required")
    write(engine, userdata.add_skill_mark, AI, "LLM fine-tuning", "Design", importance="required")
    write(engine, userdata.add_skill_mark, SIMILAR, "Kubernetes", "Design", importance="required")
    model = "nomic-embed-text:latest"
    with engine.begin() as conn:
        derived.save_embeddings(conn, model, {
            "fine-tuning": [1.0, 0.0], "llm fine-tuning": [0.857, (1 - 0.857 ** 2) ** 0.5], "kubernetes": [0.0, 1.0],
        })
        derived.save_judgment(conn, Planned("kubernetes", "Kubernetes", None, []), "gemma4:12b", model, PIPELINE,
                              "succeeded", None, {}, {})


def test_pooled_row_lists_its_other_names(client, three):
    pool_fine_tuning(three)
    skills_table = table(text(get(client, "/insights")), "recommended-skills")
    pooled = table_row(skills_table, "<td>fine-tuning<")
    assert "also: LLM fine-tuning" in pooled and 'value="fine-tuning"' in pooled
    assert "<td>LLM fine-tuning</td>" not in skills_table
    assert "also:" not in table_row(skills_table, "<td>Kubernetes</td>")


def test_answering_a_pool(client, three):
    from jobhunt.db import llm_jobs

    pool_fine_tuning(three)
    write(three, userdata.set_setting, "llm.model", "gemma4:12b")
    post(client, "/insights/skill", {"name": "fine-tuning", "level": "missing"})
    with three.connect() as conn:
        added = conn.execute(
            select(claims).join(skills, skills.c.id == claims.c.skill_id).where(skills.c.key == "fine-tuning")
        ).one()
        kinds = conn.execute(select(llm_jobs.c.kind, llm_jobs.c.status)).all()
    assert (added.level, added.level_origin) == ("missing", "user")
    assert ("links", "queued") in kinds
    skills_table = table(text(get(client, "/insights")), "recommended-skills")
    assert "<option selected>missing</option>" in table_row(skills_table, "<td>fine-tuning</td>")
    assert "also:" not in table_row(skills_table, "<td>LLM fine-tuning</td>")  # apart until a judgment links it


# --- Insights: workplace filter (filter-insights-by-workplace 2.1–2.4) ---
# BANK is On-site; SIMILAR and AI are Hybrid.


def python_everywhere(engine):
    write(engine, userdata.add_profile_skill, "Python", "proficient")
    for job in (BANK, SIMILAR):
        write(engine, userdata.add_skill_mark, job, "Python", "Design", importance="required")
    write(engine, userdata.add_skill_mark, BANK, "Kubernetes", "Design", importance="required")


def test_workplace_filter_from_the_url(client, three):
    python_everywhere(three)
    hybrid = text(get(client, "/insights?workplace=Hybrid"))
    assert f'data-job-id="{BANK}"' not in table(hybrid, "recommended-postings")
    assert "<td>Kubernetes</td>" not in table(hybrid, "recommended-skills")
    assert f'data-job-id="{BANK}"' in table(text(get(client, "/insights?workplace=Moon")), "recommended-postings")


def test_workplace_checkboxes_and_column(client, three):
    python_everywhere(three)
    html = text(get(client, "/insights"))
    assert all(f'name="workplace" value="{w}" checked' in html for w in ("On-site", "Hybrid", "Remote"))
    assert ">On-site<" in table_row(table(html, "recommended-postings"), f'data-job-id="{BANK}"')
    narrowed = text(get(client, "/insights?workplace=Hybrid&workplace=Remote"))
    assert 'value="On-site" >' in narrowed
    assert 'value="Hybrid" checked' in narrowed and 'value="Remote" checked' in narrowed


def test_posting_without_a_workplace_type_shows_a_dash(client, three):
    write(three, userdata.add_profile_skill, "Python", "proficient")
    write(three, userdata.add_skill_mark, AI, "Python", "Design", importance="required")
    add_posting(three, "senior-ai-engineer.json", captured_at=at(23), tag="no type", workplace_type=None)
    row = table_row(table(text(get(client, "/insights")), "recommended-postings"), f'data-job-id="{AI}"')
    assert ">—<" in row


def test_answer_keeps_the_filter(client, three):
    suggest_aws(three)
    response = post(
        client, "/insights/skill", {"name": "AWS", "level": "missing", "next": "/insights?workplace=Hybrid"}
    )
    assert response.status_code == 303 and response.headers["Location"].endswith("/insights?workplace=Hybrid")
    response = post(client, "/insights/skill", {"name": "Go", "level": "missing", "next": "//evil.example"})
    assert response.status_code == 303 and response.headers["Location"].endswith("/insights")


def test_answer_forms_carry_the_filter(client, three):
    write(three, userdata.add_profile_skill, "AWS", "learning")
    write(three, userdata.add_skill_mark, SIMILAR, "AWS", "Design", importance="required")
    write(three, userdata.add_skill_mark, SIMILAR, "Kubernetes", "Design", importance="required")
    skills_table = table(text(get(client, "/insights?workplace=Hybrid")), "recommended-skills")
    hybrid = 'name="next" value="/insights?workplace=Hybrid"'
    assert table_row(skills_table, "<td>Kubernetes</td>").count(hybrid) == 2  # have it, don't have it
    assert hybrid in table_row(skills_table, "<td>AWS</td>")  # the level form
    both = table(text(get(client, "/insights?workplace=Remote&workplace=Hybrid&x=1")), "recommended-skills")
    assert 'name="next" value="/insights?workplace=Hybrid&amp;workplace=Remote"' in both
    unfiltered = table(text(get(client, "/insights?workplace=Moon")), "recommended-skills")
    assert 'name="next" value="/insights"' in unfiltered


def test_nothing_of_the_chosen_workplace_types(client, three):
    python_everywhere(three)
    write(three, userdata.dismiss, BANK, [reason_id(three, "other")])
    on_site = text(get(client, "/insights?workplace=On-site"))
    for name in ("recommended-postings", "recommended-skills"):
        assert "No posting of the chosen workplace types" in table(on_site, name)
    assert "No posting of the chosen workplace types" not in text(get(client, "/insights"))


# --- Ratings, tags, notes (8.1) ---


HX = {"HX-Request": "true"}


def test_rating_fragment_and_reload(client, three):
    response = post(client, f"/postings/{BANK}/rating", {"field": "interest", "value": "4"}, headers=dict(HX))
    fragment = text(response)
    assert response.status_code == 200 and "<html" not in fragment
    assert fragment.count('class="on"') == 4
    html = text(get(client, f"/postings/{BANK}"))
    assert 'aria-label="interest 4" aria-pressed="true"' in html
    assert 'aria-pressed="true"' not in html.split('class="rating-label">fit')[1].split("</form>")[0]


def test_clearing_rating_lists_as_unrated(client, three):
    post(client, f"/postings/{BANK}/rating", {"field": "interest", "value": "4"})
    assert BANK not in row_order(text(get(client, "/?unrated=1")))
    post(client, f"/postings/{BANK}/rating", {"field": "interest", "value": ""})
    with three.connect() as conn:
        assert conn.execute(select(posting_triage.c.interest)).scalar_one() is None
    assert BANK in row_order(text(get(client, "/?unrated=1")))


def test_bad_rating_rejected(client, three):
    assert post(client, f"/postings/{BANK}/rating", {"field": "interest", "value": "9"}).status_code == 400
    assert post(client, f"/postings/{BANK}/rating", {"field": "mood", "value": "3"}).status_code == 400
    assert count(three, posting_triage) == 0


def test_compact_rating_in_list_row(client, three):
    html = text(get(client, "/"))
    assert f'id="ratings-{BANK}-row"' in html
    fragment = text(
        post(client, f"/postings/{BANK}/rating", {"field": "interest", "value": "2", "compact": "1"}, headers=dict(HX))
    )
    assert f'id="ratings-{BANK}-row"' in fragment and "fit" not in fragment


def test_tag_add_and_remove(client, three):
    fragment = text(post(client, f"/postings/{BANK}/tags", {"name": " ML "}, headers=dict(HX)))
    assert '<span class="chip">ML' in fragment
    text(post(client, f"/postings/{AI}/tags", {"name": "ml"}, headers=dict(HX)))
    assert count(three, posting_tags) == 2
    with three.connect() as conn:
        tag_id = conn.execute(select(posting_tags.c.tag_id)).scalars().first()
    fragment = text(post(client, f"/postings/{BANK}/tags/{tag_id}/remove", headers=dict(HX)))
    assert '<span class="chip">' not in fragment
    assert count(three, posting_tags) == 1


def test_existing_tags_suggested(client, three):
    post(client, f"/postings/{BANK}/tags", {"name": "remote-ok"})
    html = text(get(client, f"/postings/{AI}"))
    assert '<datalist id="tag-suggestions"><option value="remote-ok"></datalist>' in html


def test_markdown_note(client, three):
    fragment = text(post(client, f"/postings/{BANK}/notes", {"notes": "**Ask** about <b>visa</b>"}, headers=dict(HX)))
    assert "<strong>Ask</strong>" in fragment
    assert "&lt;b&gt;visa&lt;/b&gt;" in fragment and "<b>visa</b>" not in fragment


def test_markdown_note_refuses_javascript_links(client, three):
    post(client, f"/postings/{BANK}/notes", {"notes": "[x](javascript:alert(1))"})
    assert 'href="javascript:' not in text(get(client, f"/postings/{BANK}"))


# --- Dismiss and restore (8.2) ---


def test_dismiss_and_restore(client, three):
    response = post(
        client,
        f"/postings/{BANK}/dismiss",
        {
            "reason": [str(reason_id(three, "too senior")), str(reason_id(three, "location or on-site"))],
            "comment": "far",
        },
    )
    assert response.status_code == 303
    assert BANK not in row_order(text(get(client, "/")))
    assert row_order(text(get(client, "/?dismissed=only"))) == [BANK]
    html = text(get(client, f"/postings/{BANK}"))
    assert "Too senior, Location or on-site" in html and "Restore" in html

    post(client, f"/postings/{BANK}/restore")
    assert BANK in row_order(text(get(client, "/")))
    post(client, f"/postings/{BANK}/dismiss", {"reason": str(reason_id(three, "compensation"))})
    html = text(get(client, f"/postings/{BANK}"))
    history = html.split("<h3>History</h3>")[1]
    assert history.count("Dismissed") == 2 and "Restored" in history and "Compensation" in history


def test_dismiss_with_new_reason(client, three):
    post(client, f"/postings/{BANK}/dismiss", {"new_reason": "Contract only"})
    html = text(get(client, f"/postings/{AI}"))
    assert "Contract only" in html  # now offered as a reason everywhere
    assert BANK not in row_order(text(get(client, "/")))


def test_dismiss_without_reason_changes_nothing(client, three):
    assert post(client, f"/postings/{BANK}/dismiss", {"comment": "x"}).status_code == 400
    assert BANK in row_order(text(get(client, "/")))


# --- Skill marks (8.3) ---


def test_mark_create_and_remove(client, three):
    response = post(client, f"/postings/{BANK}/marks", {"skill": "Automation", "quote": "drives  data\nautomation"})
    assert response.status_code == 303
    html = text(get(client, f"/postings/{BANK}"))
    assert "<strong>Automation</strong>" in html and "“drives data automation”" in html
    assert "not found in current description" not in html
    assert (
        '<script type="application/json" id="mark-quotes">'
        '[{"importance": null, "quote": "drives data automation"}]</script>'
    ) in html
    assert "marks.js" in html and 'id="mark-popup"' in html

    with three.connect() as conn:
        mark_id = conn.execute(select(posting_skill_marks.c.id)).scalar_one()
    post(client, f"/postings/{BANK}/marks/{mark_id}/remove")
    assert count(three, posting_skill_marks) == 0


def test_mark_not_found_label(client, engine):
    add_posting(engine, captured_at=at(20))
    post(client, f"/postings/{BANK}/marks", {"skill": "Automation", "quote": "drives data automation"})
    add_posting(
        engine, captured_at=at(25), tag="v2", description_html="<p>Rewritten.</p>", description_text="Rewritten."
    )
    assert "not found in current description" in text(get(client, f"/postings/{BANK}"))


def test_skill_level_shown_on_every_posting(client, three):
    post(client, f"/postings/{BANK}/marks", {"skill": "Kubernetes", "quote": "Design"})
    post(client, f"/postings/{AI}/marks", {"skill": "kubernetes", "quote": "Design"})
    with three.connect() as conn:
        skill_id = conn.execute(select(skills.c.id)).scalar_one()
    response = post(client, f"/skills/{skill_id}/level", {"level": "missing", "next": f"/postings/{BANK}"})
    assert response.status_code == 303 and response.headers["Location"].endswith(f"/postings/{BANK}")
    for job in (BANK, AI):
        assert "<option selected>missing</option>" in text(get(client, f"/postings/{job}"))


def test_level_redirect_stays_on_site(client, three):
    post(client, f"/postings/{BANK}/marks", {"skill": "Go", "quote": "Design"})
    with three.connect() as conn:
        skill_id = conn.execute(select(skills.c.id)).scalar_one()
    response = post(client, f"/skills/{skill_id}/level", {"level": "proficient", "next": "//evil.example/"})
    assert response.headers["Location"].endswith("/skills")


# --- Skills page (8.4) ---


def test_skills_page_counts(client, engine):
    keys = [
        add_posting(engine, f) for f in ("data-automation.json", "senior-ai-engineer.json", "health-economist.json")
    ]
    for job, interest in zip(keys, (4, 5, 3), strict=True):
        post(client, f"/postings/{job}/marks", {"skill": "PyTorch", "quote": "a"})
        post(client, f"/postings/{job}/rating", {"field": "interest", "value": str(interest)})
    html = text(get(client, "/skills"))
    row = html.split(">PyTorch</a>")[1].split("</tr>")[0]
    assert '<td class="postings-count">3</td>' in row and '<td class="high-count">2</td>' in row


# --- Skill summary and the collapsible marks panel (summarize-posting-skills) ---


def test_detail_shows_skill_summary(client, three):
    python = write(three, userdata.add_profile_skill, "Python", "proficient")
    write(three, userdata.add_skill_mark, BANK, "Python", "Design", importance="required")
    write(three, userdata.add_skill_mark, BANK, "Terraform", "Design", importance="required")
    html = text(get(client, f"/postings/{BANK}"))
    start = html.index('id="skill-summary"')
    summary = html[start:html.index("</section>", start)]
    assert "42%" in summary and "1 of 2 skills without a link" in summary
    assert f'<a href="/profile#skill-{python}">Python</a>' in summary and "(same, proficient)" in summary
    assert "Terraform —" in summary and "not judged yet" in summary
    assert html.index('id="skill-summary"') < html.index('class="grid2"')


def test_summary_messages(client, three):
    assert "no skills yet" in text(get(client, f"/postings/{BANK}"))
    write(three, userdata.add_skill_mark, BANK, "Terraform", "Design")
    html = text(get(client, f"/postings/{BANK}"))
    assert "profile has no skills yet" in html and 'href="/profile"' in html


def test_marks_panel_collapsed_with_heading(client, three):
    html = text(get(client, f"/postings/{BANK}"))
    assert "Skills asked for (none marked)" in html and "Select text in the description to mark a skill." in html
    write(three, userdata.add_skill_mark, BANK, "Terraform", "Design")
    write(three, userdata.add_skill_mark, BANK, "AWS", "Design")
    write(three, userdata.set_skills_complete, BANK, True)
    html = text(get(client, f"/postings/{BANK}"))
    assert "Skills asked for (2 marked · labelling complete)" in html
    details = html.index("<details>", html.index('id="marks-panel"'))
    assert html.index("Your marks on this posting") < details  # description outside the <details>
    assert "<details open" not in html[html.index('id="marks-panel"'):]
    assert html.index('id="marks"') > details


def test_mark_actions_land_on_the_panel_and_refresh_the_summary(client, three):
    response = post(client, f"/postings/{BANK}/marks", {"skill": "Automation", "quote": "drives data automation"})
    assert response.headers["Location"].endswith("#marks-panel")
    html = text(get(client, f"/postings/{BANK}"))
    assert html.count('hx-select-oob="#skill-summary,#marks-heading"') == 3  # importance, level, labelled
    with three.connect() as conn:
        skill_id = conn.execute(select(skills.c.id)).scalar_one()
    write(three, userdata.set_skill_level, skill_id, "familiar")
    summary = text(get(client, f"/postings/{BANK}"))
    summary = summary[summary.index('id="skill-summary"'):]
    assert "(same, familiar)" in summary[:summary.index("</section>")]
