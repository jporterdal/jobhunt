"""The MCP server's tools as plain functions over the read models (no `mcp` import, no Flask, no writes).

Each tool takes a connection and its checked arguments and returns one JSON-ready dict built from named fields of
a read model's rows, so a column added to a read model later never reaches a client unnoticed. A field with no
value is left out. Nothing here returns profile details, records, highlights, documents, notes, contacts,
application events, saved CVs, captured files, earlier snapshots, volatile details or unverified suggestions.
`mcp_server.py` registers these for the scopes named at start-up.
"""

from __future__ import annotations

import dataclasses
import sys
from datetime import date, datetime
from typing import Any, NotRequired

from sqlalchemy.engine import Connection

from . import queries, recommend

if sys.version_info >= (3, 12):
    from typing import TypedDict
else:  # pydantic, which reads these for the output schemas, needs this one before 3.12 (sqlalchemy installs it)
    from typing_extensions import TypedDict

SEARCH_LIMIT_DEFAULT = 20
SEARCH_LIMIT_MAX = 50
DESCRIPTION_LIMIT = 20_000

# Scope -> the tools it offers, in listing order. No scope means "all": a later scope can't widen an old setting.
SCOPES: dict[str, tuple[str, ...]] = {
    "postings": ("search_postings", "get_posting"),
    "profile": ("posting_fit", "profile_skills", "recommendations"),
}

SCOPE_SUMMARIES = {
    "postings": "stored postings (title, company, location, description, original URL) with your interest, fit, "
    "tags, dismissals and application status",
    "profile": "your profile's skill names, levels and aliases, each posting's match score and skill links, and the "
    "Insights ranking",
}


class NotFound(Exception):
    """A posting id that doesn't exist. The message holds the id only."""

    def __init__(self, job_id: int):
        super().__init__(f"No posting with id {job_id}.")
        self.job_id = job_id


# --- Result types (the server's output schemas) ---


class PostingRef(TypedDict):
    job_id: int
    title: str
    company: str
    url: str


class PostingSummary(PostingRef):
    location: NotRequired[str]
    workplace_type: NotRequired[str]
    posted_on: NotRequired[str]
    first_seen: str
    last_seen: str
    interest: NotRequired[int]
    fit: NotRequired[int]
    tags: list[str]
    dismissed: bool
    application_status: NotRequired[str]


# Each tool's result type has `warnings`: the server puts first the arguments it left out of a call (see
# mcp_server._sift). The functions here never set it.
class FiltersUsed(TypedDict, total=False):
    q: str
    tag: str
    min_interest: int
    unrated: bool
    workplace: str
    status: str
    dismissed: str


class TotalWithout(TypedDict, total=False):
    q: int
    tag: int
    min_interest: int
    unrated: int
    workplace: int
    status: int
    dismissed: int


class SearchResult(TypedDict):
    warnings: NotRequired[list[str]]
    total: int
    filters_used: NotRequired[FiltersUsed]
    total_without: NotRequired[TotalWithout]
    offset: int
    next_offset: NotRequired[int]
    postings: list[PostingSummary]


class Posting(PostingSummary):
    warnings: NotRequired[list[str]]
    source: str
    employment_type: NotRequired[str]
    posted_precision: NotRequired[str]
    snapshots: int
    details: dict[str, Any]
    description: str
    description_chars: int
    description_truncated: NotRequired[bool]


class HaveEntry(TypedDict):
    name: str
    importance: NotRequired[str]
    source: str
    credit: float
    profile_skill: str
    level: str
    relation: str
    link_source: NotRequired[str]


class DontHaveEntry(TypedDict):
    name: str
    importance: NotRequired[str]
    source: str
    reason: str
    profile_skill: NotRequired[str]


class FitResult(PostingRef):
    warnings: NotRequired[list[str]]
    score: NotRequired[float]
    skills: int
    unlinked: int
    has_profile_skills: bool
    have: list[HaveEntry]
    dont_have: list[DontHaveEntry]


class ProfileSkill(TypedDict):
    name: str
    level: str
    level_origin: str
    aliases: list[str]


class ProfileSkillsResult(TypedDict):
    warnings: NotRequired[list[str]]
    count: int
    skills: list[ProfileSkill]


class Gap(TypedDict):
    name: str
    importance: NotRequired[str]
    credit: float


class RankedPosting(PostingRef):
    workplace_type: NotRequired[str]
    interest: NotRequired[int]
    score: float
    value: float
    gaps: list[Gap]


class ImprovedPosting(PostingRef):
    rise: float


class SkillGain(TypedDict):
    name: str
    level: NotRequired[str]
    also: list[str]
    gain: float
    improved: int
    postings: list[ImprovedPosting]


class ConsideredWithout(TypedDict):
    workplace: int


class RecommendationsResult(TypedDict):
    warnings: NotRequired[list[str]]
    workplaces: NotRequired[list[str]]
    considered: int
    considered_without: NotRequired[ConsideredWithout]
    no_skills: int
    has_posting_skills: bool
    has_profile_skills: bool
    postings: list[RankedPosting]
    skills: list[SkillGain]


# --- Helpers ---


def _iso(value: date | datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _pick(**fields) -> dict:
    """The named fields, leaving out those with no value (None)."""
    return {name: value for name, value in fields.items() if value is not None}


def _ref(row) -> dict:
    return {"job_id": row["job_id"], "title": row["title"], "company": row["company"], "url": row["url"]}


def _choice(name: str, value: str, allowed: tuple[str, ...]) -> str:
    if value not in allowed:
        raise ValueError(f"{name}: expected one of {', '.join(allowed)}")
    return value


def _posting_detail(conn: Connection, job_id: int) -> dict:
    detail = queries.posting_detail(conn, job_id)
    if detail is None:
        raise NotFound(job_id)
    return detail


# --- The tools ---


def search_postings(
    conn: Connection,
    q: str = "",
    tag: str = "",
    min_interest: int | None = None,
    unrated: bool = False,
    workplace: str | None = None,
    status: str | None = None,
    dismissed: str = "hidden",
    sort: str = "last_seen",
    limit: int = SEARCH_LIMIT_DEFAULT,
    offset: int = 0,
) -> dict:
    """The postings list with its filters and sort, `limit` postings from `offset`."""
    if min_interest is not None and min_interest not in range(1, 6):
        raise ValueError("min_interest: expected 1 to 5")
    if not 1 <= limit <= SEARCH_LIMIT_MAX:
        raise ValueError(f"limit: expected 1 to {SEARCH_LIMIT_MAX}")
    if offset < 0:
        raise ValueError("offset: expected 0 or more")
    filters = queries.ListFilters(
        q=q.strip(),
        tag=tag.strip(),
        min_interest=min_interest,
        unrated=unrated,
        workplace="" if workplace is None else _choice("workplace", workplace, queries.WORKPLACE_TYPES),
        status="" if status is None else _choice("status", status, queries.STATUS_FILTERS),
        dismissed=_choice("dismissed", dismissed, queries.DISMISSED_MODES),
        sort=_choice("sort", sort, queries.SORTS),
    )
    rows = queries.posting_list(conn, filters)
    page = rows[offset:offset + limit]
    used = _filters_used(filters)
    return _pick(
        total=len(rows),
        filters_used=used or None,
        total_without={
            name: len(queries.posting_list(conn, dataclasses.replace(filters, **{name: _NEUTRAL[name]})))
            for name in used
        } or None,
        offset=offset,
        next_offset=offset + limit if offset + limit < len(rows) else None,
        postings=[_summary(row) for row in page],
    )


# Each ListFilters field that can leave postings out, with the value that leaves none out. Sort, limit and offset
# only order or page the matches, so they're never in `filters_used`. `dismissed` is "hidden" by default: that is a
# filter too, and is named when applied.
_NEUTRAL = {"q": "", "tag": "", "min_interest": None, "unrated": False, "workplace": "", "status": "",
            "dismissed": "included"}


def _filters_used(filters: queries.ListFilters) -> dict:
    """The filters of `filters` that can leave postings out, by argument name, in the tool's argument order."""
    return {name: getattr(filters, name) for name, neutral in _NEUTRAL.items() if getattr(filters, name) != neutral}


def _summary(row) -> dict:
    """A posting_list row as a PostingSummary."""
    return _ref(row) | _pick(
        location=row["location"],
        workplace_type=row["workplace_type"],
        posted_on=_iso(row["posted_on_estimate"]),
        first_seen=_iso(row["first_seen_at"]),
        last_seen=_iso(row["last_seen_at"]),
        interest=row["interest"],
        fit=row["fit"],
        tags=[t["name"] for t in row["tags"]],
        dismissed=row["dismissal_id"] is not None,
        application_status=row["application_status"],
    )


def get_posting(conn: Connection, job_id: int) -> dict:
    """One posting's latest version, its description as plain text (cut at DESCRIPTION_LIMIT characters)."""
    detail = _posting_detail(conn, job_id)
    posting, latest, triage, application = detail["posting"], detail["latest"], detail["triage"], detail["application"]
    text = latest.description_text
    return _pick(
        job_id=posting.job_id,
        title=latest.title,
        company=latest.company,
        url=posting.url,
        location=latest.location,
        workplace_type=latest.workplace_type,
        posted_on=_iso(latest.posted_on_estimate),
        first_seen=_iso(posting.first_seen_at),
        last_seen=_iso(posting.last_seen_at),
        interest=triage.interest if triage else None,
        fit=triage.fit if triage else None,
        tags=[t["name"] for t in detail["tags"]],
        dismissed=detail["dismissed"],
        application_status=application.status if application else None,
        source=posting.source,
        employment_type=latest.employment_type,
        posted_precision=latest.posted_on_precision if latest.posted_on_estimate else None,
        snapshots=len(detail["snapshots"]),
        details=dict(detail["details"]),
        description=text[:DESCRIPTION_LIMIT],
        description_chars=len(text),
        description_truncated=True if len(text) > DESCRIPTION_LIMIT else None,
    )


def posting_fit(conn: Connection, job_id: int) -> dict:
    """A posting's match score and its Have / Don't have lists, as on its page, with each link's source."""
    detail = _posting_detail(conn, job_id)
    summary = recommend.posting_summary(conn, job_id)
    have = [e for group in summary["have"] for e in group["entries"]]
    dont_have = [e for group in summary["dont_have"] for e in group["entries"]]
    links = queries.effective_links(conn, [e["key"] for e in have]) if have else {}
    return {
        "job_id": job_id,
        "title": detail["latest"].title,
        "company": detail["latest"].company,
        "url": detail["posting"].url,
    } | _pick(
        score=summary["score"]["score"],
        skills=summary["score"]["skills"],
        unlinked=summary["score"]["unlinked"],
        has_profile_skills=summary["has_profile_skills"],
        have=[
            _pick(
                name=e["name"], importance=e["importance"], source=e["source"], credit=e["credit"],
                profile_skill=e["skill_name"], level=e["level"], relation=e["relation"],
                link_source=links[e["key"]]["source"],
            )
            for e in have
        ],
        dont_have=[
            _pick(
                name=e["name"], importance=e["importance"], source=e["source"], reason=e["reason"],
                profile_skill=e.get("skill_name"),
            )
            for e in dont_have
        ],
    )


def profile_skills(conn: Connection) -> dict:
    """Every profile skill with its level, the level's origin and its aliases; highest level first, then name."""
    skills = [
        {
            "name": claim["name"],
            "level": claim["level"],
            "level_origin": claim["level_origin"],
            "aliases": [alias["name"] for alias in claim["aliases"]],
        }
        for _level, group in queries.profile(conn)["claims"]
        for claim in group
    ]
    return {"count": len(skills), "skills": skills}


def recommendations(conn: Connection, workplace: list[str] | None = None) -> dict:
    """The Insights lists: postings to look at first and skills to gain, for the workplace types given (none or
    all three: no filter)."""
    chosen = [_choice("workplace", w, queries.WORKPLACE_TYPES) for w in workplace or ()]
    workplaces = recommend.workplace_choice(chosen)
    result = recommend.recommendations(conn, workplaces)
    return _pick(
        workplaces=[w for w in queries.WORKPLACE_TYPES if w in workplaces] if workplaces else None,
        considered=result["considered"],
        considered_without=(
            {"workplace": recommend.recommendations(conn, None)["considered"]} if workplaces else None
        ),
        no_skills=result["no_skills"],
        has_posting_skills=result["has_posting_skills"],
        has_profile_skills=result["has_profile_skills"],
        postings=[
            _ref(p) | _pick(
                workplace_type=p["workplace_type"], interest=p["interest"], score=p["score"], value=p["value"],
                gaps=[_pick(name=g["name"], importance=g["importance"], credit=g["credit"]) for g in p["gaps"]],
            )
            for p in result["postings"]
        ],
        skills=[
            _pick(
                name=s["name"], level=s["level"], also=list(s["also"]), gain=s["gain"], improved=s["improved"],
                postings=[_ref(p) | {"rise": p["rise"]} for p in s["postings"]],
            )
            for s in result["skills"]
        ],
    )


TOOLS = {
    "search_postings": search_postings,
    "get_posting": get_posting,
    "posting_fit": posting_fit,
    "profile_skills": profile_skills,
    "recommendations": recommendations,
}


def result_items(name: str, result: dict) -> int:
    """Rows in a result's main list, 1 for a single posting (a tool span's `jobhunt.mcp.result.items`)."""
    if name == "get_posting":
        return 1
    if name == "posting_fit":
        return len(result["have"]) + len(result["dont_have"])
    return len(result["postings"] if "postings" in result else result["skills"])
