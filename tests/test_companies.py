"""Companies and contacts: writers and company page query (11.1), pages and safe link rendering (11.2)."""

import pytest
from sqlalchemy import func, select

from jobhunt import queries, userdata
from jobhunt.db import companies, contact_emails
from jobhunt.userdata import UserDataError

from .conftest import add_posting, get, post

BANK, AI, ECON = 1, 2, 3  # keys in the order the advisory fixture imports them


@pytest.fixture
def advisory(engine):
    """Two stored postings that name Example Advisory (in different cases) and one that doesn't."""
    assert add_posting(engine, "data-automation.json", company="Example Advisory") == BANK
    assert add_posting(engine, "senior-ai-engineer.json", company="example  advisory") == AI
    assert add_posting(engine, "health-economist.json") == ECON
    return engine


def write(engine, fn, *args, **kwargs):
    with engine.begin() as conn:
        return fn(conn, *args, **kwargs)


def text(response) -> str:
    return response.get_data(as_text=True)


# --- Writers and company page query (11.1) ---


def test_company_by_key(advisory):
    first = write(advisory, userdata.get_or_create_company, "Example Advisory")
    again = write(advisory, userdata.get_or_create_company, " example ADVISORY ")
    assert first.id == again.id
    with advisory.connect() as conn:
        assert conn.execute(select(func.count()).select_from(companies)).scalar_one() == 1


def test_company_page(advisory):
    company = write(advisory, userdata.get_or_create_company, "Example Advisory")
    write(
        advisory,
        userdata.update_company,
        company.id,
        "Example Advisory",
        None,
        "https://careers.example.com/",
        "Mid-size firm",
    )
    app_id = write(advisory, userdata.create_application, "Auditor", "EXAMPLE ADVISORY")
    write(advisory, userdata.create_application, "Other", "Acme")
    with advisory.connect() as conn:
        page = queries.company_page(conn, company.id)
    assert page["company"].careers_url == "https://careers.example.com/"
    assert sorted(p["job_id"] for p in page["postings"]) == [BANK, AI]
    assert [a["id"] for a in page["applications"]] == [app_id]
    with advisory.connect() as conn:
        assert queries.company_page(conn, 999) is None
        overview = queries.companies_overview(conn)
    assert (overview[0]["postings"], overview[0]["applications"], overview[0]["contacts"]) == (2, 1, 0)


def test_rename_cannot_clash(advisory):
    write(advisory, userdata.get_or_create_company, "Example Advisory")
    acme = write(advisory, userdata.get_or_create_company, "Acme")
    with pytest.raises(UserDataError):
        write(advisory, userdata.update_company, acme.id, "example advisory", None, None, None)


def test_recruiter_contact(advisory):
    company = write(advisory, userdata.get_or_create_company, "Example Advisory")
    app_id = write(advisory, userdata.start_application, BANK)
    contact_id = write(
        advisory, userdata.save_contact, None, "Jane Doe", ["jane@advisory.example", " ", "JANE@advisory.example"],
        role="Recruiter", company_id=company.id,
    )
    write(advisory, userdata.link_contact, app_id, contact_id)
    write(advisory, userdata.link_contact, app_id, contact_id)  # linking twice is harmless
    with advisory.connect() as conn:
        page = queries.company_page(conn, company.id)
        detail = queries.application_detail(conn, app_id)
    assert [c["name"] for c in page["contacts"]] == ["Jane Doe"]
    assert page["contacts"][0]["emails"] == ["jane@advisory.example"]
    assert [c["name"] for c in detail["contacts"]] == ["Jane Doe"]

    write(
        advisory,
        userdata.save_contact,
        contact_id,
        "Jane Doe",
        ["jane@advisory.example", "jd@home.example"],
        role="Recruiter",
    )
    with advisory.connect() as conn:
        assert len(conn.execute(select(contact_emails)).all()) == 2
    write(advisory, userdata.unlink_contact, app_id, contact_id)
    with advisory.connect() as conn:
        assert queries.application_detail(conn, app_id)["contacts"] == []


def test_contact_needs_name(advisory):
    with pytest.raises(UserDataError):
        write(advisory, userdata.save_contact, None, "  ", [])


# --- Pages (11.2) ---


def test_company_name_offers_create_then_links(client, advisory):
    html = text(get(client, f"/postings/{BANK}"))
    assert '<a href="/companies/lookup?name=Example+Advisory">Example Advisory</a>' in html
    response = get(client, "/companies/lookup?name=Example+Advisory")
    assert response.headers["Location"].endswith("/companies?name=Example+Advisory#new-company")
    assert "There is no record for “Example Advisory” yet." in text(get(client, "/companies?name=Example+Advisory"))

    created = post(client, "/companies", {"name": "Example Advisory"})
    company_url = created.headers["Location"]
    assert get(client, "/companies/lookup?name=example+advisory").headers["Location"] == company_url


def test_company_page_scenario(client, advisory):
    company_url = post(client, "/companies", {"name": "Example Advisory"}).headers["Location"]
    company_id = company_url.rsplit("/", 1)[1]
    post(client, f"/companies/{company_id}/edit", {"name": "Example Advisory", "careers_url": "https://careers.example.com/"})
    html = text(get(client, company_url))
    assert '<a href="https://careers.example.com/" target="_blank"' in html
    for url in ("https://jobs.example.com/view/A-1001", "https://jobs.example.com/view/A-1003"):
        assert f'class="original-link" href="{url}" target="_blank"' in html
    assert "https://careers.example.org/jobs/1004" not in html and f'href="/postings/{ECON}"' not in html


def test_contact_email_is_mailto(client, advisory):
    company_id = post(client, "/companies", {"name": "Example Advisory"}).headers["Location"].rsplit("/", 1)[1]
    app_id = post(client, f"/postings/{BANK}/application").headers["Location"].rsplit("/", 1)[1]
    post(
        client,
        "/contacts",
        {
            "name": "Jane Doe",
            "emails": "jane@advisory.example",
            "role": "Recruiter",
            "company_id": company_id,
            "app_id": app_id,
        },
    )
    for url in (f"/applications/{app_id}", f"/companies/{company_id}"):
        html = text(get(client, url))
        assert "Jane Doe" in html and '<a href="mailto:jane@advisory.example">jane@advisory.example</a>' in html


def test_javascript_url_is_plain_text(client, advisory):
    company_id = post(client, "/companies", {"name": "Evil"}).headers["Location"].rsplit("/", 1)[1]
    post(client, f"/companies/{company_id}/edit", {"name": "Evil", "website_url": "javascript:alert(1)"})
    contact = post(
        client, "/contacts", {"name": "Mallory", "profile_url": "JavaScript:alert(2)", "company_id": company_id}
    )
    app = post(client, "/applications", {"title": "T", "company": "Evil", "url": "javascript:alert(3)"})
    for response_url in (
        f"/companies/{company_id}",
        contact.headers["Location"],
        app.headers["Location"],
        "/applications",
    ):
        html = text(get(client, response_url))
        assert 'href="javascript:' not in html.lower()
    assert '<span class="unsafe-url">javascript:alert(1)</span>' in text(get(client, f"/companies/{company_id}"))


def test_https_and_mailto_urls_are_links(client, advisory):
    app = post(client, "/applications", {"title": "T", "company": "C", "url": "mailto:jobs@c.example"})
    assert '<a href="mailto:jobs@c.example" target="_blank"' in text(get(client, app.headers["Location"]))
