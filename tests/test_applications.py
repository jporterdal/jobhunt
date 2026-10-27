"""Applications: writers and status from events (9.1, 9.2), application page and board (9.3, 9.4)."""

import re
from datetime import date, timedelta

import pytest
from sqlalchemy import func, select

from jobhunt import queries, userdata
from jobhunt.db import application_events, applications
from jobhunt.userdata import UserDataError

from .conftest import add_posting, get, post

BANK, AI = 1, 2  # keys in the order the db fixture imports them


@pytest.fixture
def db(engine):
    assert add_posting(engine) == BANK
    assert add_posting(engine, "senior-ai-engineer.json") == AI
    return engine


def write(engine, fn, *args, **kwargs):
    with engine.begin() as conn:
        return fn(conn, *args, **kwargs)


def app_row(engine, app_id):
    with engine.connect() as conn:
        return conn.execute(select(applications).where(applications.c.id == app_id)).one()


def text(response) -> str:
    return response.get_data(as_text=True)


# --- Writers (9.1) ---


def test_start_from_posting_copies_fields(db):
    app_id = write(db, userdata.start_application, BANK)
    app = app_row(db, app_id)
    assert app.job_id == BANK
    assert app.title == "Analytics Manager, Reporting Automation (Example City)" and app.company == "Example Bank"
    assert app.url == "https://jobs.example.com/view/A-1001"
    assert app.status == "interested" and app.status_date is None


def test_one_application_per_posting(db):
    first = write(db, userdata.start_application, BANK)
    assert write(db, userdata.start_application, BANK) == first
    with db.connect() as conn:
        assert conn.execute(select(func.count()).select_from(applications)).scalar_one() == 1


def test_manual_application(db):
    app_id = write(db, userdata.create_application, "Data Engineer", " Acme ", "https://acme.example/careers/42")
    app = app_row(db, app_id)
    assert (app.job_id, app.title, app.company, app.url) == (None, "Data Engineer", "Acme", "https://acme.example/careers/42")
    write(db, userdata.create_application, "Analyst", "Beta")  # many manual applications may exist
    with pytest.raises(UserDataError):
        write(db, userdata.create_application, "", "Acme")


def test_link_later_keeps_history(db):
    app_id = write(db, userdata.create_application, "Data Engineer", "Acme")
    write(db, userdata.add_event, app_id, "applied", date(2026, 9, 28))
    write(db, userdata.link_application, app_id, AI)
    app = app_row(db, app_id)
    assert app.job_id == AI and app.title == "Data Engineer" and app.status == "applied"
    with db.connect() as conn:
        assert len(conn.execute(select(application_events)).all()) == 1


def test_link_refused_when_posting_has_application(db):
    write(db, userdata.start_application, BANK)
    manual = write(db, userdata.create_application, "X", "Y")
    with pytest.raises(UserDataError):
        write(db, userdata.link_application, manual, BANK)
    with pytest.raises(UserDataError):
        write(db, userdata.link_application, manual, 123)
    assert app_row(db, manual).job_id is None


def test_edit_fields_and_next_action(db):
    app_id = write(db, userdata.create_application, "X", "Y")
    write(db, userdata.update_application, app_id, "Data Engineer", "Acme", "", "CAD 120-140k")
    write(db, userdata.set_next_action, app_id, "Follow up", date(2026, 10, 9))
    app = app_row(db, app_id)
    assert (app.title, app.url, app.compensation_notes) == ("Data Engineer", None, "CAD 120-140k")
    assert (app.next_action, app.next_action_due) == ("Follow up", date(2026, 10, 9))
    write(db, userdata.set_next_action, app_id, "", date(2026, 10, 9))
    assert (app_row(db, app_id).next_action, app_row(db, app_id).next_action_due) == (None, None)


# --- Events and status (9.2) ---


def events_scenario(db):
    app_id = write(db, userdata.start_application, BANK)
    write(db, userdata.add_event, app_id, "applied", date(2026, 9, 28))
    screening = write(db, userdata.add_event, app_id, "screening", date(2026, 10, 3))
    return app_id, screening


def assert_cache_matches_events(db, app_id):
    app = app_row(db, app_id)
    with db.connect() as conn:
        assert (app.status, app.status_date) == userdata.status_from_events(conn, app_id)


def test_progressing(db):
    app_id, _ = events_scenario(db)
    assert app_row(db, app_id).status == "screening"
    assert app_row(db, app_id).status_date == date(2026, 10, 3)
    assert_cache_matches_events(db, app_id)


def test_back_dated_event(db):
    app_id, _ = events_scenario(db)
    write(db, userdata.add_event, app_id, "interested", date(2026, 9, 25))
    assert app_row(db, app_id).status == "screening"
    with db.connect() as conn:
        events = queries.application_detail(conn, app_id)["events"]
    assert [e.kind for e in events] == ["interested", "applied", "screening"]
    assert_cache_matches_events(db, app_id)


def test_deleting_a_mistake(db):
    app_id, screening = events_scenario(db)
    write(db, userdata.delete_event, app_id, screening)
    assert app_row(db, app_id).status == "applied"
    assert_cache_matches_events(db, app_id)


def test_notes_and_same_day_order(db):
    app_id, _ = events_scenario(db)
    write(db, userdata.add_event, app_id, "note", date(2026, 10, 5), "recruiter called")
    assert app_row(db, app_id).status == "screening"
    write(db, userdata.add_event, app_id, "interviewing", date(2026, 10, 5))
    write(db, userdata.add_event, app_id, "rejected", date(2026, 10, 5))
    assert app_row(db, app_id).status == "rejected"  # same date: later entry wins
    assert_cache_matches_events(db, app_id)


def test_deleting_every_event_returns_to_interested(db):
    app_id = write(db, userdata.start_application, BANK)
    event = write(db, userdata.add_event, app_id, "applied", date(2026, 9, 28))
    write(db, userdata.delete_event, app_id, event)
    assert (app_row(db, app_id).status, app_row(db, app_id).status_date) == ("interested", None)


def test_unknown_event_kind(db):
    app_id = write(db, userdata.start_application, BANK)
    with pytest.raises(UserDataError):
        write(db, userdata.add_event, app_id, "hired", date(2026, 9, 28))


# --- Application page (9.3) ---


def test_start_from_posting_page(client, db):
    html = text(get(client, f"/postings/{BANK}"))
    assert "Start application" in html
    response = post(client, f"/postings/{BANK}/application")
    assert response.status_code == 303
    app_url = response.headers["Location"]
    page = text(get(client, app_url))
    assert "Analytics Manager, Reporting Automation (Example City)" in page
    assert 'href="https://jobs.example.com/view/A-1001" target="_blank"' in page

    html = text(get(client, f"/postings/{BANK}"))
    assert "Start application" not in html and app_url.split("8000")[-1] in html
    assert '<span class="status status-interested">interested</span>' in html
    row = text(get(client, "/")).split(f'data-job-id="{BANK}"')[1].split("</tr>")[0]
    assert '<span class="status status-interested">interested</span>' in row


def test_add_and_delete_event_through_page(client, db):
    app_id = int(post(client, f"/postings/{BANK}/application").headers["Location"].rsplit("/", 1)[1])
    post(client, f"/applications/{app_id}/events", {"kind": "applied", "event_date": "2026-09-28", "note": "via site"})
    post(client, f"/applications/{app_id}/events", {"kind": "screening", "event_date": "2026-10-03"})
    assert app_row(db, app_id).status == "screening"
    html = text(get(client, f"/applications/{app_id}"))
    event_ids = re.findall(rf"/applications/{app_id}/events/(\d+)/delete", html)
    post(client, f"/applications/{app_id}/events/{event_ids[-1]}/delete")
    assert app_row(db, app_id).status == "applied"
    row = text(get(client, "/")).split(f'data-job-id="{BANK}"')[1].split("</tr>")[0]
    assert "status-applied" in row
    assert post(client, f"/applications/{app_id}/events", {"kind": "applied", "event_date": "28/9"}).status_code == 400


def test_overdue_highlight(client, db):
    app_id = write(db, userdata.start_application, BANK)
    write(db, userdata.add_event, app_id, "applied", date.today() - timedelta(days=3))
    post(
        client,
        f"/applications/{app_id}/next-action",
        {"next_action": "Follow up with recruiter", "next_action_due": (date.today() - timedelta(days=1)).isoformat()},
    )
    page = text(get(client, f"/applications/{app_id}"))
    assert '<p class="due">Follow up with recruiter' in page
    board = text(get(client, "/applications"))
    assert f'<div class="card is-due" data-app-id="{app_id}">' in board
    assert '<li class="due">' in board


def test_not_due_when_closed_or_future(db):
    app_id = write(db, userdata.start_application, BANK)
    write(db, userdata.set_next_action, app_id, "Prepare", date.today() + timedelta(days=2))
    with db.connect() as conn:
        assert not queries.application_detail(conn, app_id)["app"]["due"]
    write(db, userdata.set_next_action, app_id, "Prepare", date.today())
    write(db, userdata.add_event, app_id, "rejected", date.today())
    with db.connect() as conn:
        assert not queries.application_detail(conn, app_id)["app"]["due"]


def test_manual_application_page_and_link_later(client, db):
    response = post(client, "/applications", {"title": "Data Engineer", "company": "Acme", "url": "https://acme.example/careers/42"})
    app_id = int(response.headers["Location"].rsplit("/", 1)[1])
    page = text(get(client, f"/applications/{app_id}"))
    assert '<a href="https://acme.example/careers/42" target="_blank"' in page
    detail = text(get(client, f"/postings/{AI}"))
    assert f'<option value="{app_id}">Data Engineer — Acme</option>' in detail
    post(client, f"/postings/{AI}/link-application", {"app_id": str(app_id)})
    page = text(get(client, f"/applications/{app_id}"))
    assert 'href="https://jobs.example.com/view/A-1003" target="_blank"' in page


# --- Board (9.4) ---


def test_board_grouping(client, db):
    applied = write(db, userdata.create_application, "A", "Acme", "https://acme.example/a")
    write(db, userdata.add_event, applied, "applied", date(2026, 9, 28))
    interviewing = write(db, userdata.start_application, BANK)
    write(db, userdata.add_event, interviewing, "interviewing", date(2026, 10, 1))
    rejected = write(db, userdata.create_application, "R", "Rho")
    write(db, userdata.add_event, rejected, "rejected", date(2026, 9, 30))

    html = text(get(client, "/applications"))
    open_part, closed_part = html.split('<details id="closed-statuses">')
    assert open_part.index('data-status="applied"') < open_part.index('data-status="interviewing"')
    assert f'data-app-id="{applied}"' in open_part.split('data-status="applied"')[1].split("</section>")[0]
    assert f'data-app-id="{interviewing}"' in open_part.split('data-status="interviewing"')[1].split("</section>")[0]
    assert f'data-app-id="{rejected}"' in closed_part.split('data-status="rejected"')[1].split("</section>")[0]
    assert "<summary>Closed (1)</summary>" in closed_part
    assert 'href="https://jobs.example.com/view/A-1001" target="_blank"' in open_part
    assert 'href="https://acme.example/a" target="_blank"' in open_part
    assert "last event 2026-10-01" in open_part


def test_board_next_actions_sorted_by_due(db):
    later = write(db, userdata.create_application, "Later", "L")
    sooner = write(db, userdata.create_application, "Sooner", "S")
    undated = write(db, userdata.create_application, "Undated", "U")
    write(db, userdata.set_next_action, later, "x", date(2026, 11, 1))
    write(db, userdata.set_next_action, sooner, "x", date(2026, 10, 5))
    write(db, userdata.set_next_action, undated, "x", None)
    with db.connect() as conn:
        board = queries.applications_board(conn)
    assert [a["title"] for a in board["next_actions"]] == ["Sooner", "Later", "Undated"]
