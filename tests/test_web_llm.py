"""Web tests for model features: status badge, settings, extraction and queue, the "Model says" panel,
salary in the list, mark importance and the labelled flag, and the guard on the new routes."""

import re

import pytest
from sqlalchemy import select

from jobhunt import userdata
from jobhunt.db import (
    app_settings,
    enrichment_skills,
    llm_jobs,
    metadata,
    posting_skill_marks,
    posting_triage,
    rejected_suggestions,
)
from jobhunt.enrich import jobs
from jobhunt.enrich.ollama import ModelInfo
from jobhunt.enrich.pipeline import SalaryItem, SkillItem

from .conftest import add_posting, add_run, get, post
from .fakes import FakeOllama, label_lines, skill
from .test_userdata import all_rows, count, write

BANK, SIMILAR, AI = 1, 2, 3  # keys in the order the three fixture imports them
PAY_TEXT = (
    "Pay: The base salary in the range of $175,000 – $200,000 USD (Example Metro, EX), "
    "$110,000 – $130,000 CAD (Example City, EX)."
)


def make_client(engine, tmp_path, ollama):
    from jobhunt.web import create_app

    app = create_app(engine, tmp_path / "inbox", tmp_path / "documents", host="127.0.0.1", port=8000, ollama=ollama)
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture
def ollama():
    return FakeOllama()


@pytest.fixture
def three(engine):
    assert add_posting(engine, "data-automation.json") == BANK
    assert add_posting(engine, "innovation-lab.json") == SIMILAR
    assert add_posting(engine, "senior-ai-engineer.json") == AI
    return engine


@pytest.fixture
def client(three, tmp_path, ollama):
    write(three, userdata.set_setting, "llm.model", "gemma4:12b")
    return make_client(three, tmp_path, ollama)


def text(response) -> str:
    return response.get_data(as_text=True)


def panel_html(client, job_id=BANK, **args):
    query = "&".join(f"{k}={v}" for k, v in args.items())
    html = text(get(client, f"/postings/{job_id}" + (f"?{query}" if query else "")))
    return html[html.index('id="model-says"'):html.index("</section>", html.index('id="model-says"'))]


def jobs_of(engine):
    with engine.connect() as conn:
        return conn.execute(select(llm_jobs.c.job_id, llm_jobs.c.status).order_by(llm_jobs.c.id)).all()


BANK_SKILLS = [
    ("Data lineage", "required", "data lineage"),
    ("Data governance", "required", "data governance"),
    ("LangChain", "preferred", "LangChain"),
    ("Kubernetes", "required", "Kubernetes clusters"),  # unverified
]


# --- Status badge (8.1) ---


@pytest.mark.parametrize(
    "state, model, expected",
    [
        ("offline", "gemma4:12b", "model: offline"),
        ("online", "gemma4:12b", "model: gemma4:12b"),
        ("online", None, "model: none selected"),
        ("online", "llama3:70b", "model: llama3:70b not installed"),
        ("spill", "gemma4:12b", "model: gemma4:12b · partly on CPU (75% on the GPU), slower"),
    ],
)
def test_status_badge(engine, tmp_path, state, model, expected):
    if model:
        write(engine, userdata.set_setting, "llm.model", model)
    client = make_client(engine, tmp_path, FakeOllama(state, detail="75% on the GPU"))
    assert expected in text(get(client, "/llm/status"))


def test_badge_without_ollama_address(engine, tmp_path):
    assert "model: offline" in text(get(make_client(engine, tmp_path, None), "/llm/status"))


def test_badge_loaded_after_the_page(client, ollama):
    html = text(get(client, "/"))
    assert 'hx-get="/llm/status" hx-trigger="load, every 15s"' in html
    assert ">Settings</a>" in html


# --- Settings (8.2) ---


def test_settings_lists_text_models_only(client):
    html = text(get(client, "/settings"))
    options = re.findall(r"<option[^>]*>([^<]+)</option>", html[html.index('name="model"'):html.index("</select>")])
    assert options == ["gemma4:12b", "phi4:latest"]
    assert "http://127.0.0.1:11434" in html and 'name="ollama' not in html  # the address is read-only


def test_settings_persist(client, three, tmp_path, ollama):
    response = post(client, "/settings", {"model": "phi4:latest", "num_ctx": "16384", "segmenter": "rules"})
    assert response.status_code == 303
    restarted = make_client(three, tmp_path, ollama)
    html = text(get(restarted, "/settings"))
    assert "<option selected>phi4:latest</option>" in html and 'value="16384"' in html
    assert "<option selected>rules</option>" in html


@pytest.mark.parametrize(
    "form",
    [
        {"model": "nomic-embed-text:latest", "num_ctx": "8192", "segmenter": "llm-lines"},
        {"model": "gemma4:12b", "num_ctx": "100", "segmenter": "llm-lines"},
        {"model": "gemma4:12b", "num_ctx": "8192", "segmenter": "magic"},
        {"model": "phi4:latest", "num_ctx": "16384", "segmenter": "rules", "skills": "atomic@5"},
    ],
)
def test_invalid_settings_rejected(client, three, form):
    response = post(client, "/settings", form)
    assert response.status_code == 400
    if "skills" in form:
        assert "skill extraction method is not a setting" in text(response)
    with three.connect() as conn:
        assert userdata.settings(conn) == {
            "llm.model": "gemma4:12b",
            "llm.num_ctx": 8192,
            "llm.segmenter": "llm-lines",
            "llm.embed_model": None,
            "eval.holdout_start": None,
            "demo.created_at": None,
        }


def embed_options(html):
    select_html = html[html.index('name="embed_model"'):html.index("</select>", html.index('name="embed_model"'))]
    return re.findall(r"<option([^>]*)>([^<]+)</option>", select_html)


def test_choosing_an_embedding_model(three, tmp_path):
    write(three, userdata.set_setting, "llm.model", "gemma4:12b")
    installed = [
        ModelInfo("gemma4:12b", "d1", 8_000_000_000, ("completion", "thinking")),
        ModelInfo("nomic-embed-text:latest", "d3", 270_000_000, ("embedding",)),
    ]
    client = make_client(three, tmp_path, FakeOllama(models=installed))
    html = text(get(client, "/settings"))
    assert embed_options(html) == [(" selected", "nomic-embed-text:latest")]
    options = re.findall(r"<option[^>]*>([^<]+)</option>", html[html.index('name="model"'):html.index("</select>")])
    assert options == ["gemma4:12b"]
    form = {
        "model": "gemma4:12b",
        "num_ctx": "8192",
        "segmenter": "llm-lines",
        "embed_model": "nomic-embed-text:latest",
    }
    assert post(client, "/settings", form).status_code == 303
    with three.connect() as conn:
        assert userdata.get_setting(conn, "llm.embed_model") == "nomic-embed-text:latest"
    form["embed_model"] = "gemma4:12b"
    assert post(client, "/settings", form).status_code == 400


def test_no_embedding_model_installed(three, tmp_path):
    installed = [ModelInfo("gemma4:12b", "d1", 8_000_000_000, ("completion",))]
    html = text(get(make_client(three, tmp_path, FakeOllama(models=installed)), "/settings"))
    assert 'name="embed_model"' not in html and "No embedding models are installed" in html


def test_embedding_setting_must_name_a_model(engine):
    with pytest.raises(userdata.UserDataError, match="embedding model"):
        write(engine, userdata.set_setting, "llm.embed_model", "  ")


def test_no_skill_method_choice(client, candidate):
    html = text(get(client, "/settings"))
    assert 'name="skills"' not in html and "atomic@5" not in html
    assert "Skills are extracted with <code>atomic@2</code>" in html


def test_stray_skill_method_setting_ignored(client, three, candidate):
    with three.begin() as conn:  # left by an earlier version of the app
        conn.execute(app_settings.insert().values(key="llm.skills", value="atomic@5", updated_at=userdata.utcnow()))
    assert (
        post(client, "/settings", {"model": "gemma4:12b", "num_ctx": "4096", "segmenter": "rules"}).status_code == 303
    )
    with three.connect() as conn:
        assert "llm.skills" not in userdata.settings(conn)
        assert "skills=atomic@2" in jobs.current_pipeline(conn)[1]


def test_holdout_start_and_clear(client, three):
    write(three, userdata.set_skills_complete, BANK, True)
    html = text(get(client, "/settings"))
    assert "all 1 labelled postings are development" in html and 'value="start"' in html
    assert post(client, "/settings/holdout", {"action": "start"}).status_code == 303
    write(three, userdata.set_skills_complete, SIMILAR, True)
    html = text(get(client, "/settings"))
    assert "Held-out set started" in html and "1 development, 1 held-out" in html and 'value="clear"' in html
    assert post(client, "/settings/holdout", {"action": "start"}).status_code == 400  # already started
    assert post(client, "/settings/holdout", {"action": "clear"}).status_code == 303
    with three.connect() as conn:
        assert userdata.get_setting(conn, "eval.holdout_start") is None
    assert "all 2 labelled postings are development" in text(get(client, "/settings"))
    assert post(client, "/settings/holdout", {"action": "other"}).status_code == 400


def test_holdout_needs_same_origin(client, three):
    assert post(client, "/settings/holdout", {"action": "start"}, origin="http://evil.example").status_code == 403
    with three.connect() as conn:
        assert userdata.get_setting(conn, "eval.holdout_start") is None


def test_settings_offline(three, tmp_path):
    write(three, userdata.set_setting, "llm.model", "gemma4:12b")
    client = make_client(three, tmp_path, FakeOllama("offline"))
    html = text(get(client, "/settings"))
    assert "gemma4:12b" in html and "the list of installed models is unavailable" in html
    assert post(client, "/settings", {"num_ctx": "4096", "segmenter": "rules"}).status_code == 303
    assert (
        post(client, "/settings", {"model": "phi4:latest", "num_ctx": "4096", "segmenter": "rules"}).status_code == 400
    )


# --- Extract actions and queue (8.3) ---


def test_extract_one_posting_once(client, three):
    for _ in range(2):
        response = post(client, f"/postings/{BANK}/extract")
        assert response.status_code == 303 and response.headers["Location"].endswith(f"/postings/{BANK}#model-says")
    assert jobs_of(three) == [(BANK, "queued")]
    panel = panel_html(client)
    assert "queued…" in panel and 'hx-trigger="every 3s"' in panel


def test_extract_disabled_while_offline(three, tmp_path):
    write(three, userdata.set_setting, "llm.model", "gemma4:12b")
    client = make_client(three, tmp_path, FakeOllama("offline"))
    panel = panel_html(client)
    assert "Ollama is offline." in panel and re.search(r"<button type=\"submit\" disabled>\s*Extract", panel)
    assert post(client, f"/postings/{BANK}/extract").status_code == 400
    assert "Ollama is offline." in text(get(client, "/"))
    assert post(client, "/extract").status_code == 400
    assert jobs_of(three) == []


def test_extract_disabled_without_installed_model(three, tmp_path):
    write(three, userdata.set_setting, "llm.model", "llama3:70b")
    client = make_client(three, tmp_path, FakeOllama())
    assert "llama3:70b is not installed" in panel_html(client)
    assert post(client, f"/postings/{BANK}/extract").status_code == 400


def test_bulk_count_matches_and_queues(client, three):
    add_run(three, BANK)  # already extracted with the current settings
    html = text(get(client, "/"))
    assert "Extract 2 postings" in html and 'hx-confirm="Queue 2 postings for extraction with gemma4:12b?"' in html
    narrowed = text(get(client, "/?q=research"))
    assert "Extract 1 posting" in narrowed and '<input type="hidden" name="q" value="research">' in narrowed
    rows_only = text(get(client, "/?q=research", headers={"HX-Request": "true", "HX-Target": "posting-rows"}))
    assert 'id="bulk-extract" class="row small" hx-swap-oob="true"' in rows_only and "Extract 1 posting" in rows_only

    response = post(client, "/extract", {"q": "research"})
    assert response.status_code == 303 and response.headers["Location"] == "/?q=research"
    assert jobs_of(three) == [(SIMILAR, "queued")]
    post(client, "/extract")
    assert sorted(jobs_of(three)) == [(SIMILAR, "queued"), (AI, "queued")]
    assert "Extract 0 postings" in text(get(client, "/"))


def test_queue_fragment_polls_while_busy(client, three):
    idle = get(client, "/llm/queue")
    assert idle.status_code == 286 and "hx-trigger" not in text(idle)
    post(client, f"/postings/{BANK}/extract")
    busy = get(client, "/llm/queue")
    assert busy.status_code == 200 and 'hx-trigger="every 3s"' in text(busy)
    assert "0 running, 1 queued" in text(busy)


def test_queue_cancel(client, three):
    post(client, f"/postings/{BANK}/extract")
    post(client, f"/postings/{AI}/extract")
    assert post(client, "/llm/queue/cancel", {"next": "/?q=x"}).headers["Location"] == "/?q=x"
    assert jobs_of(three) == [(BANK, "cancelled"), (AI, "cancelled")]
    assert post(client, "/llm/queue/cancel", {"next": "//evil.example"}).headers["Location"] == "/"


def test_worker_result_appears_in_panel(client, three, ollama):
    ollama.responses = {
        "lines": [label_lines({"data lineage": "required", "governance": "required"})],
        "skills": [
            {"skills": [skill(1, "Data lineage", "data lineage"), skill(2, "Data governance", "data governance")]}
        ],
    }
    post(client, f"/postings/{BANK}/extract")
    assert jobs.run_next(three, ollama) == "done"
    panel = panel_html(client)
    assert "hx-trigger" not in panel.split(">", 1)[0]  # polling stopped
    assert "Data lineage" in panel and "gemma4:12b" in panel


# --- The "Model says" panel (8.4) ---


def test_panel_shows_run(client, three):
    add_posting(three, "senior-ai-engineer.json", tag="axis", description_text=PAY_TEXT)
    add_run(
        three,
        AI,
        skills=[("Python", "required", "Pay")],
        salaries=[
            SalaryItem(175000, 200000, "USD", "year", "Example Metro, EX", "base", "$175,000 - $200,000 USD"),
            SalaryItem(110000, 130000, "CAD", "year", "Example City, EX", "base", "$110,000 - $130,000 CAD"),
        ],
    )
    panel = panel_html(client, AI)
    assert "gemma4:12b" in panel and "seg=llm-lines@2" in panel
    assert "175,000–200,000 USD per year · Example Metro, EX" in panel and "110,000–130,000 CAD per year" in panel
    assert "Required skills" in panel and "“Pay”" in panel


def test_only_eval_runs_show_no_output(client, three):
    add_run(three, skills=BANK_SKILLS, origin="eval")
    panel = panel_html(client)
    assert "No model output for this posting yet." in panel and "Data lineage" not in panel
    assert re.search(r"<button type=\"submit\"\s*>\s*Extract</button>", panel)  # offered, and not "again"


def test_panel_groups_and_hides_unverified(client, three):
    add_run(three, skills=BANK_SKILLS)
    panel = panel_html(client)
    required = panel[panel.index("Required skills"):panel.index("Preferred skills")]
    assert "Data lineage" in required and "Data governance" in required and "Kubernetes" not in required
    assert "LangChain" in panel[panel.index("Preferred skills"):]
    details = panel[panel.index("<details"):]
    assert "Show 1 unverified item" in details and "Kubernetes" in details


def test_model_markup_is_text(client, three):
    add_run(three, skills=[SkillItem("<b>Go</b>", "required", "technical", "data lineage")])
    html = text(get(client, f"/postings/{BANK}"))
    assert "&lt;b&gt;Go&lt;/b&gt;" in html and "<b>Go</b>" not in html


def test_failed_run_shows_error(client, three):
    add_run(three, status="failed", error="skills: no skills were extracted from the required lines")
    assert "This run failed: skills: no skills were extracted from the required lines" in panel_html(client)


def test_run_picker(client, three):
    first = add_run(three, skills=BANK_SKILLS[:1], model="phi4:latest")
    add_run(three, skills=BANK_SKILLS[2:3])
    latest = panel_html(client)
    assert "LangChain" in latest and 'name="run"' in latest
    older = panel_html(client, run=first)
    assert "phi4:latest" in older and "Data lineage" in older and "LangChain" not in older
    fragment = text(get(client, f"/postings/{BANK}/model-says?run={first}"))
    assert fragment.startswith("\n<section") or fragment.lstrip().startswith("<section")
    assert "Data lineage" in fragment


def test_accept_and_already_marked(client, three):
    run_id = add_run(three, skills=BANK_SKILLS)
    with three.connect() as conn:
        item = conn.execute(
            select(enrichment_skills.c.id).where(enrichment_skills.c.name == "Data lineage")
        ).scalar_one()
    response = post(client, f"/suggestions/{item}/accept", {"run": run_id})
    assert response.status_code == 303 and response.headers["Location"].endswith(f"?run={run_id}#model-says")
    [mark] = all_rows(three, posting_skill_marks)
    assert (mark.quote, mark.importance, mark.origin) == ("data lineage", "required", "suggestion")
    panel = panel_html(client)
    assert re.search(r"Data lineage</strong>.*?already marked", panel, re.S)
    assert post(client, f"/suggestions/{item}/accept", {"run": run_id}).status_code == 400
    assert 'hx-select-oob="#skill-summary,#marks,#marks-heading"' in panel


def test_accept_all(client, three):
    run_id = add_run(three, skills=BANK_SKILLS)
    assert (
        post(client, f"/postings/{BANK}/suggestions/accept-all", {"run": run_id, "importance": "required"}).status_code
        == 303
    )
    assert sorted(m.quote for m in all_rows(three, posting_skill_marks)) == ["data governance", "data lineage"]
    assert "Accept all required" not in panel_html(client)


def test_accept_refused_on_stale_run(client, three):
    run_id = add_run(three, skills=BANK_SKILLS)
    add_posting(
        three, tag="v2", description_text="Rewritten. data lineage", description_html="<p>Rewritten. data lineage</p>"
    )
    panel = panel_html(client)
    assert "Made on an older snapshot" in panel and ">Accept<" not in panel and "Accept all" not in panel
    with three.connect() as conn:
        item = conn.execute(
            select(enrichment_skills.c.id).where(enrichment_skills.c.name == "Data lineage")
        ).scalar_one()
    assert post(client, f"/suggestions/{item}/accept", {"run": run_id}).status_code == 400
    assert (
        post(client, f"/postings/{BANK}/suggestions/accept-all", {"run": run_id, "importance": "required"}).status_code
        == 400
    )
    assert count(three, posting_skill_marks) == 0


def test_reject_and_undo(client, three):
    run_id = add_run(three, skills=BANK_SKILLS)
    post(client, f"/postings/{BANK}/rejections", {"skill": "LangChain", "run": run_id, "reason": "not-for-me"})
    assert [(r.skill_key, r.reason) for r in all_rows(three, rejected_suggestions)] == [("langchain", "not-for-me")]
    panel = panel_html(client)
    preferred = panel[panel.index("Preferred skills"):panel.index("<details")]
    assert "LangChain" not in preferred and "1 rejected" in panel
    add_run(three, skills=BANK_SKILLS)  # a later run: still hidden
    assert "1 rejected" in panel_html(client)
    post(client, f"/postings/{BANK}/rejections/delete", {"skill": "langchain", "run": run_id})
    assert count(three, rejected_suggestions) == 0


def rejected_html(client):
    panel = panel_html(client)
    return panel[panel.index("<details"):panel.index("</details>")]


def test_two_reject_actions(client, three):
    run_id = add_run(three, skills=BANK_SKILLS)
    panel = panel_html(client)
    assert panel.count('value="not-a-skill"') == 3 and panel.count('value="not-for-me"') == 3
    assert ">Reject<" not in panel
    post(client, f"/postings/{BANK}/rejections", {"skill": "Data lineage", "run": run_id, "reason": "not-a-skill"})
    post(client, f"/postings/{BANK}/rejections", {"skill": "LangChain", "run": run_id, "reason": "not-for-me"})
    assert sorted((r.skill_key, r.reason) for r in all_rows(three, rejected_suggestions)) == [
        ("data lineage", "not-a-skill"),
        ("langchain", "not-for-me"),
    ]
    rejected = rejected_html(client)
    assert re.search(r"Data lineage .*?not a skill</span>", rejected, re.S)
    assert re.search(r"LangChain .*?not for me</span>", rejected, re.S)
    assert (
        post(client, f"/postings/{BANK}/rejections", {"skill": "Data governance", "reason": "meh"}).status_code == 400
    )
    assert post(client, f"/postings/{BANK}/rejections", {"skill": "Data governance"}).status_code == 400
    assert count(three, rejected_suggestions) == 2


def test_reason_set_on_earlier_rejection(client, three):
    run_id = add_run(three, skills=BANK_SKILLS)
    with three.begin() as conn:  # rejected before reasons existed
        conn.execute(
            rejected_suggestions.insert().values(job_id=BANK, skill_key="langchain", created_at=userdata.utcnow())
        )
    rejected = rejected_html(client)
    assert "no reason</span>" in rejected and "Make it “not a skill”" in rejected and "Make it “not for me”" in rejected
    response = post(
        client, f"/postings/{BANK}/rejections/reason", {"skill": "LangChain", "run": run_id, "reason": "not-for-me"}
    )
    assert response.status_code == 303
    [row] = all_rows(three, rejected_suggestions)
    assert (row.skill_key, row.reason) == ("langchain", "not-for-me")
    rejected = rejected_html(client)
    assert (
        "not for me</span>" in rejected
        and "Make it “not for me”" not in rejected
        and "1 rejected" in panel_html(client)
    )
    assert (
        post(client, f"/postings/{BANK}/rejections/reason", {"skill": "Cursor", "reason": "not-for-me"}).status_code
        == 400
    )
    assert (
        post(client, f"/postings/{BANK}/rejections/reason", {"skill": "LangChain", "reason": "meh"}).status_code == 400
    )


def test_unknown_suggestion_is_404(client, three):
    assert post(client, "/suggestions/999/accept").status_code == 404
    assert post(client, "/postings/123/extract").status_code == 404


# --- Salary in the list (8.5) ---


def test_list_salary_summary(client, three):
    add_posting(three, "senior-ai-engineer.json", tag="axis", description_text=PAY_TEXT)
    add_run(
        three,
        AI,
        salaries=[
            SalaryItem(175000, 200000, "USD", "year", "Example Metro, EX", "base", "$175,000 - $200,000 USD"),
            SalaryItem(110000, 130000, "CAD", "year", "Example City, EX", "base", "$110,000 - $130,000 CAD"),
        ],
    )
    html = text(get(client, "/"))
    row = html[html.index(f'data-job-id="{AI}"'):]
    row = row[:row.index("</tr>")]
    assert re.search(
        r'<span class="src-derived salary"[^>]*>\$175k–200k/yr</span>\s*<span class="muted">\+1 more</span>', row
    )
    bank_row = html[html.index(f'data-job-id="{BANK}"'):]
    assert "salary" not in bank_row[:bank_row.index("</tr>")]


# --- Mark importance and the labelled flag (8.6) ---


def test_mark_with_importance(client, three):
    post(client, f"/postings/{BANK}/marks", {"skill": "Terraform", "quote": "data lineage", "importance": "preferred"})
    post(client, f"/postings/{BANK}/marks", {"skill": "LangChain", "quote": "LangChain", "importance": ""})
    assert [(m.importance, m.origin) for m in all_rows(three, posting_skill_marks)] == [
        ("preferred", "selection"),
        (None, "selection"),
    ]
    html = text(get(client, f"/postings/{BANK}"))
    assert '"importance": "preferred", "quote": "data lineage"' in html
    assert 'name="importance" value="required"' in html  # the popup offers importance


def test_change_mark_importance(client, three):
    post(client, f"/postings/{BANK}/marks", {"skill": "PyTorch", "quote": "data lineage"})
    mark = all_rows(three, posting_skill_marks)[0]
    assert post(client, f"/postings/{BANK}/marks/{mark.id}/importance", {"importance": "required"}).status_code == 303
    assert all_rows(three, posting_skill_marks)[0].importance == "required"
    assert "<option selected>required</option>" in text(get(client, f"/postings/{BANK}"))
    assert post(client, f"/postings/{BANK}/marks/{mark.id}/importance", {"importance": "vital"}).status_code == 400


def test_labelled_toggle_and_filter(client, three):
    html = text(get(client, f"/postings/{BANK}"))
    assert ">Labelling complete</button>" in html
    post(client, f"/postings/{BANK}/labelled", {"complete": "1"})
    assert all_rows(three, posting_triage)[0].skills_complete_at is not None
    assert "Labelling complete since" in text(get(client, f"/postings/{BANK}"))
    listed = text(get(client, "/?labelled=yes"))
    assert re.findall(r'data-job-id="(\d+)"', listed) == [str(BANK)]
    assert '<option value="yes" selected>yes</option>' in listed
    post(client, f"/postings/{BANK}/labelled", {"complete": "0"})
    assert all_rows(three, posting_triage)[0].skills_complete_at is None


# --- Guard on the new routes (8.7) ---


def post_routes(three):
    run_id = add_run(three, skills=BANK_SKILLS)
    with three.connect() as conn:
        item = conn.execute(select(enrichment_skills.c.id)).scalars().first()
    write(three, userdata.add_skill_mark, BANK, "X", "data lineage")
    mark = all_rows(three, posting_skill_marks)[0].id
    return [
        ("/settings", {"num_ctx": "4096", "segmenter": "rules"}),
        (f"/postings/{BANK}/extract", {}),
        ("/extract", {}),
        ("/llm/queue/cancel", {}),
        (f"/suggestions/{item}/accept", {"run": run_id}),
        (f"/postings/{BANK}/suggestions/accept-all", {"run": run_id, "importance": "required"}),
        (f"/postings/{BANK}/rejections", {"skill": "LangChain", "reason": "not-a-skill"}),
        (f"/postings/{BANK}/rejections/reason", {"skill": "LangChain", "reason": "not-for-me"}),
        (f"/postings/{BANK}/rejections/delete", {"skill": "LangChain"}),
        ("/settings/holdout", {"action": "start"}),
        (f"/postings/{BANK}/labelled", {"complete": "1"}),
        (f"/postings/{BANK}/marks/{mark}/importance", {"importance": "required"}),
    ]


def everything(engine):
    with engine.connect() as conn:
        return {t.name: sorted(map(repr, conn.execute(select(t)).all())) for t in metadata.sorted_tables}


def test_new_posts_reject_cross_origin(client, three):
    routes = post_routes(three)
    post(client, f"/postings/{AI}/extract")  # something to cancel
    before = everything(three)
    for url, form in routes:
        assert post(client, url, form, origin="http://evil.example").status_code == 403, url
        assert post(client, url, form, origin=None).status_code == 403, url
    assert everything(three) == before


def test_new_gets_are_read_only(client, three):
    post_routes(three)
    post(client, f"/postings/{AI}/extract")
    before = everything(three)
    for url in ("/llm/status", "/settings", "/llm/queue", f"/postings/{BANK}/model-says", f"/postings/{BANK}", "/"):
        assert get(client, url).status_code in (200, 286), url
    assert everything(three) == before


# --- Skill summary refresh (summarize-posting-skills 4.1, 4.2) ---


def summary_html(html):
    start = html.index('id="skill-summary"')
    return html[start:html.index("</section>", start)]


def test_summary_follows_accept_reject_and_level(client, three):
    write(three, userdata.add_profile_skill, "LangChain", "proficient")
    run_id = add_run(three, skills=BANK_SKILLS)
    summary = summary_html(text(get(client, f"/postings/{BANK}")))
    assert "LangChain" in summary and "Data lineage" in summary
    post(client, f"/postings/{BANK}/rejections", {"skill": "Data lineage", "run": run_id, "reason": "not-a-skill"})
    summary = summary_html(text(get(client, f"/postings/{BANK}")))
    assert "Data lineage" not in summary and "LangChain" in summary
    # the actions ask htmx to refresh the summary with their own panel
    assert 'hx-select-oob="#skill-summary"' in panel_html(client)


def test_panel_response_refreshes_summary_out_of_band(client, three):
    write(three, userdata.add_profile_skill, "LangChain", "proficient")
    html = text(get(client, f"/postings/{BANK}/model-says"))
    assert 'id="skill-summary"' in html and 'hx-swap-oob="true"' in html and "no skills yet" in html
    add_run(three, skills=BANK_SKILLS)
    html = text(get(client, f"/postings/{BANK}/model-says"))
    oob = summary_html(html)
    assert 'hx-swap-oob="true"' in html and "LangChain" in oob and "Data lineage" in oob
    assert 'id="skill-summary"' not in text(get(client, f"/postings/{BANK}")).split('id="model-says"')[1]
