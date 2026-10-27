"""Tailored CV pages: the proposal (read-only), saving, a saved CV's page and edits, the ODT export, and the CV
panels on the posting and application pages."""

import re
from urllib.parse import unquote

import pytest
from sqlalchemy import func, select

from jobhunt import queries, userdata
from jobhunt.db import DERIVED_TABLES, OPERATIONAL_TABLES, USER_TABLES, tailored_cvs
from jobhunt.documents import odt_text
from jobhunt.web.cvs import cv_filename

from .conftest import add_posting, get, post
from .test_userdata import write

JOB = 1  # the posting the setup fixture imports


@pytest.fixture
def setup(web, engine):
    assert add_posting(engine, title='Data / ML "Lead": <AI>?', company="Acme*Co|Ltd") == JOB
    python = write(engine, userdata.add_profile_skill, "Python", "proficient")
    write(engine, userdata.add_profile_skill, "PostgreSQL", "familiar")
    write(engine, userdata.add_skill_mark, JOB, "Python", "Design", importance="required")
    write(engine, userdata.add_skill_mark, JOB, "PostgreSQL", "Design", importance="preferred")
    hid = write(engine, userdata.add_highlight, "Shipped Python services")
    write(engine, userdata.add_coverage, hid, python)
    write(engine, userdata.add_detail, "name", "Ada Lovelace")
    write(engine, userdata.add_record, {"kind": "degree", "title": "PhD Computer Science", "end_date": "2022"})
    secret = write(engine, userdata.add_record, {"kind": "project", "title": "Secret Shop"})
    write(engine, userdata.set_disclosure, secret, "private")
    return {"client": web[1], "engine": engine, "highlight": hid, "secret": secret}


def counts(engine):
    with engine.connect() as conn:
        return {t.name: conn.execute(select(func.count()).select_from(t)).scalar_one()
                for t in USER_TABLES + DERIVED_TABLES + OPERATIONAL_TABLES}


def save(client, data=None):
    response = post(client, f"/postings/{JOB}/cvs", data or {})
    assert response.status_code == 303
    return int(re.search(r"/cvs/(\d+)$", response.headers["Location"]).group(1))


def saved(engine, cv_id):
    with engine.connect() as conn:
        return queries.tailored_cv(conn, cv_id)


# --- The proposal (7.1) ---


def test_proposal_page(setup):
    client, engine = setup["client"], setup["engine"]
    before = counts(engine)
    response = get(client, f"/postings/{JOB}/cv")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert counts(engine) == before
    assert "Match score: <strong>" in html  # (2 × 0.85 + 0.5) / 3 = 73%
    assert "73%" in html
    assert re.search(rf'name="h" value="{setup["highlight"]}" checked', html)  # the ticked highlight
    assert re.search(r'data-gap="postgresql"[^>]*><strong>PostgreSQL</strong>', html)
    assert "no highlight covers it" in html
    assert 'class="cv-preview"' in html and "Ada Lovelace" in html and "Skills &amp; Experience" in html
    assert "Secret Shop" not in html  # private: neither offered nor printed
    assert "Download" not in html and ".odt" not in html  # only a saved CV is exported
    assert 'href="https://jobs.example.com/view/A-1001"' in html


def test_proposal_choices_from_the_url_and_htmx_fragment(setup):
    client = setup["client"]
    hid = setup["highlight"]
    response = get(client, f"/postings/{JOB}/cv?tuned=1&a_h={hid}", headers={"HX-Request": "true"})
    html = response.get_data(as_text=True)
    assert html.lstrip().startswith('<div id="proposal">') and "<html" not in html
    assert re.search(rf'name="h" value="{hid}"\s+aria-label', html)  # unticked now
    assert f'name="x_h" value="{hid}"' in html
    assert "Shipped Python services</li>" not in html  # gone from the preview


def test_proposal_for_an_unknown_posting(setup):
    assert get(setup["client"], "/postings/123/cv").status_code == 404


# --- Saving and the saved CV (7.2) ---


def test_saving(setup):
    client, engine = setup["client"], setup["engine"]
    cv_id = save(client, {"tuned": "1", "r": str(setup["secret"]), "budget": "5"})
    cv = saved(engine, cv_id)
    assert [i["label"] for i in cv["items"]] == ["Ada Lovelace", "Shipped Python services", "PhD Computer Science"]
    assert cv["cv"].method == "cv-rank@1"
    html = get(client, f"/cvs/{cv_id}").get_data(as_text=True)
    assert "Secret Shop" not in html  # a private record id in the form is ignored
    assert f'href="/cvs/{cv_id}.odt"' in html and "Shipped Python services" in html


def test_saved_cv_actions(setup):
    client, engine = setup["client"], setup["engine"]
    write(engine, userdata.add_detail, "contact", "Example City")
    cv_id = save(client)
    items = {i["label"]: i["id"] for i in saved(engine, cv_id)["items"]}

    response = post(client, f"/cvs/{cv_id}/items/{items['Example City']}/move", {"direction": "up"})
    assert response.status_code == 303 and response.headers["Location"].endswith(
        f"/cvs/{cv_id}#item-{items['Example City']}"
    )
    assert [i["label"] for i in saved(engine, cv_id)["items"]][:2] == ["Example City", "Ada Lovelace"]

    response = post(client, f"/cvs/{cv_id}/items/{items['PhD Computer Science']}/remove")
    assert response.status_code == 303 and response.headers["Location"].endswith(f"/cvs/{cv_id}#items")
    assert "PhD Computer Science" not in [i["label"] for i in saved(engine, cv_id)["items"]]

    response = post(client, f"/cvs/{cv_id}/delete")
    assert response.status_code == 303 and response.headers["Location"].endswith(f"/postings/{JOB}#cvs")
    assert saved(engine, cv_id) is None


def test_deleted_and_private_since_are_marked(setup):
    client, engine = setup["client"], setup["engine"]
    cv_id = save(client)
    phd = next(i["payload"]["id"] for i in saved(engine, cv_id)["items"] if i["source_kind"] == "record")
    write(engine, userdata.set_disclosure, phd, "private")
    write(engine, userdata.delete_highlight, setup["highlight"])
    html = get(client, f"/cvs/{cv_id}").get_data(as_text=True)
    assert "deleted from the profile since" in html and "private now" in html


def test_unknown_cv_is_404(setup):
    client = setup["client"]
    assert get(client, "/cvs/99").status_code == 404
    assert get(client, "/cvs/99.odt").status_code == 404
    assert post(client, "/cvs/99/delete").status_code == 404
    assert post(client, "/cvs/99/items/1/remove").status_code == 404


def test_guard_rejects_a_foreign_origin(setup):
    client, engine = setup["client"], setup["engine"]
    assert post(client, f"/postings/{JOB}/cvs", origin="http://evil.example").status_code == 403
    cv_id = save(client)
    assert post(client, f"/cvs/{cv_id}/delete", origin="http://evil.example").status_code == 403
    with engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(tailored_cvs)).scalar_one() == 1


# --- Export (7.3) ---


def test_export(setup):
    client = setup["client"]
    cv_id = save(client)
    response = get(client, f"/cvs/{cv_id}.odt")
    assert response.status_code == 200
    assert response.mimetype == "application/vnd.oasis.opendocument.text"
    disposition = unquote(response.headers["Content-Disposition"])
    assert disposition.startswith("attachment;")
    assert 'filename="CV - AcmeCoLtd - Data ML Lead AI.odt"' in disposition
    text = odt_text(response.data).split("\n")
    assert text[0] == "Ada Lovelace" and "Skills & Experience" in text and "Shipped Python services" in text


def test_cv_filename():
    assert cv_filename("Acme*Co|Ltd", 'Data / ML "Lead": <AI>?') == "CV - AcmeCoLtd - Data ML Lead AI.odt"
    assert cv_filename("Été_Corp", "x" * 300).startswith("CV - Été_Corp - xxx")
    assert len(cv_filename("A", "x" * 300)) == 120 and cv_filename("A", "x" * 300).endswith(".odt")
    assert cv_filename(None, None) == "CV.odt"


# --- Panels (7.4) ---


def test_posting_page_lists_cvs(setup):
    client = setup["client"]
    html = get(client, f"/postings/{JOB}").get_data(as_text=True)
    assert f'href="/postings/{JOB}/cv"' in html and "No CV saved for this posting yet." in html
    first, second = save(client), save(client)
    html = get(client, f"/postings/{JOB}").get_data(as_text=True)
    assert html.index(f'href="/cvs/{second}"') < html.index(f'href="/cvs/{first}"')
    assert 'href="https://jobs.example.com/view/A-1001" target="_blank"' in html
    assert "Triage" in html and 'id="application-box"' in html and 'id="description"' in html


def test_application_page(setup):
    client, engine = setup["client"], setup["engine"]
    first, second = save(client), save(client)
    app_id = write(engine, userdata.start_application, JOB)
    html = get(client, f"/applications/{app_id}").get_data(as_text=True)
    assert 'id="cvs"' in html
    assert html.index(f'href="/cvs/{second}"') < html.index(f'href="/cvs/{first}"')


def test_application_without_posting_has_no_cv_panel(setup):
    client, engine = setup["client"], setup["engine"]
    app_id = write(engine, userdata.create_application, "Manual role", "Somewhere")
    html = get(client, f"/applications/{app_id}").get_data(as_text=True)
    assert 'id="cvs"' not in html
