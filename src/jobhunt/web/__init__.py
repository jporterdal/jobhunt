"""Local web interface: server-rendered Flask + Jinja2, htmx for inline edits, no JavaScript build."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from flask import Flask, current_app, render_template, request
from markdown_it import MarkdownIt
from markupsafe import Markup
from sqlalchemy.engine import Connection, Engine

from ..queries import detail_label
from ..userdata import SKILL_LEVELS, get_setting

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
LINK_SCHEMES = ("http", "https", "mailto")

_markdown = MarkdownIt("commonmark", {"html": False})


def create_app(
    engine: Engine,
    inbox: Path,
    documents_dir: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    ollama=None,
    parsers=None,
) -> Flask:
    """`ollama` is the model client (enrich.ollama.OllamaClient), or None when no address is configured. `parsers`
    is a parsers.Installed; by default the installed parsers are loaded once, here."""
    from ..parsers import installed
    from ..userdata import UserDataError
    from . import applications, cvs, guard, llm, postings, profile, triage

    app = Flask(__name__)
    app.config.update(
        ENGINE=engine,
        INBOX=Path(inbox),
        DOCUMENTS_DIR=Path(documents_dir),
        MAX_CONTENT_LENGTH=MAX_UPLOAD_BYTES,
        OLLAMA=ollama,
        PARSERS=parsers if parsers is not None else installed(),
    )
    guard.install(app, guard.allowed_hosts(host, port))

    app.jinja_env.filters.update(
        markdown=render_markdown,
        safe_url=safe_url,
        dt=format_datetime,
        d=format_date,
        size=format_size,
        salary=format_salary,
        salary_short=format_salary_short,
        partial_date=format_partial_date,
        detail_name=detail_label,
        detail_value=format_detail,
    )
    app.jinja_env.globals.update(list_url=list_url, skill_levels=SKILL_LEVELS)

    for module in (postings, triage, applications, llm, profile, cvs):
        app.register_blueprint(module.bp)

    @app.context_processor
    def demo_label():
        # `jobhunt demo` marks its databases, so a page never passes demo data off as the user's own.
        with reading() as conn:
            return {"demo_data": get_setting(conn, "demo.created_at") is not None}

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("404.html"), 404

    @app.errorhandler(UserDataError)
    def bad_input(error):
        # Raised inside writing(), so the transaction has already been rolled back.
        return render_template("error.html", message=str(error).capitalize() + "."), 400

    @app.errorhandler(413)
    def too_large(_error):
        return render_template("error.html", message="That file is larger than the 25 MB upload limit."), 413

    return app


# --- Database access for route handlers ---


@contextmanager
def reading() -> Iterator[Connection]:
    engine: Engine = current_app.config["ENGINE"]
    with engine.connect() as conn:
        yield conn


@contextmanager
def writing() -> Iterator[Connection]:
    engine: Engine = current_app.config["ENGINE"]
    with engine.begin() as conn:
        yield conn


def is_htmx() -> bool:
    return request.headers.get("HX-Request") == "true"


# --- Template helpers ---


def render_markdown(text: str | None) -> Markup:
    """Notes as markdown. Raw HTML is escaped, and markdown-it refuses javascript: links."""
    return Markup(_markdown.render(text or ""))


def safe_url(url: str | None) -> str | None:
    """The URL if it may be rendered as a link (http, https, mailto), else None so it shows as text."""
    if not url:
        return None
    try:
        scheme = urlsplit(url.strip()).scheme.lower()
    except ValueError:
        return None
    return url.strip() if scheme in LINK_SCHEMES else None


def format_datetime(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M UTC") if value else ""


def format_date(value: date | None) -> str:
    return value.isoformat() if value else ""


MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def format_partial_date(value: str | None) -> str:
    """'2025-03' -> 'Mar 2025'; '2022' stays."""
    if not value:
        return ""
    year, _, month = value.partition("-")
    return f"{MONTH_NAMES[int(month) - 1]} {year}" if month else year


def format_detail(value) -> str:
    """A detail's value as text: a list joined with commas, true and false as yes and no, none as a dash."""
    if value is None or value == "" or value == []:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


def format_size(size: int) -> str:
    for unit in ("bytes", "KB", "MB"):
        if size < 1024 or unit == "MB":
            return f"{size} {unit}" if unit == "bytes" else f"{size:.1f} {unit}"
        size /= 1024
    return str(size)


PERIODS = {"year": "yr", "month": "mo", "biweekly": "2 wk", "week": "wk", "day": "day", "hour": "hr"}
CURRENCY_SIGNS = {"USD": "$", "CAD": "$", "AUD": "$", "NZD": "$", "SGD": "$", "EUR": "€", "GBP": "£"}


def _amount(value: float | None, short: bool) -> str:
    if value is None:
        return "?"
    if short and value >= 1000:
        return f"{value / 1000:.0f}k" if value % 1000 == 0 else f"{value / 1000:.1f}k"
    return f"{value:,.0f}" if value == int(value) else f"{value:,.2f}"


def _range(row, short: bool) -> str:
    low, high = row["min_amount"], row["max_amount"]
    if low is not None and high is not None and low != high:
        return f"{_amount(low, short)}–{_amount(high, short)}"
    return _amount(low if low is not None else high, short)


def format_salary(row) -> str:
    """A salary range in full: "175,000–200,000 USD per year"."""
    period = "" if row["period"] == "unclear" else f" per {row['period']}"
    return f"{_range(row, False)} {row['currency']}".strip() + period


def format_salary_short(row) -> str:
    """For the posting list: "$175k–200k/yr" (or "175k–200k EUR/yr" without a known sign)."""
    sign = CURRENCY_SIGNS.get(row["currency"])
    text = f"{sign}{_range(row, True)}" if sign else f"{_range(row, True)} {row['currency']}".strip()
    period = PERIODS.get(row["period"])
    return f"{text}/{period}" if period else text


def list_url(filters, **changes) -> str:
    args = filters.with_(**changes).to_args() if changes else filters.to_args()
    return "/" + (f"?{urlencode(args)}" if args else "")
