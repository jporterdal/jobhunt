"""Read models for the web interface: posting list and filters, detail, diff, skills (no Flask, no writes)."""

from __future__ import annotations

import difflib
import json
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from datetime import date
from types import SimpleNamespace

from sqlalchemy import case, distinct, exists, func, or_, select
from sqlalchemy.engine import Connection

from .db import (
    application_contacts,
    application_documents,
    application_events,
    applications,
    captures,
    claim_records,
    claims,
    companies,
    contact_emails,
    contacts,
    dismiss_reasons,
    document_runs,
    documents,
    enrichment_salaries,
    enrichment_skills,
    highlight_claims,
    highlights,
    link_judgments,
    link_relations,
    llm_jobs,
    posting_dismissal_reasons,
    posting_dismissals,
    posting_enrichments,
    posting_skill_marks,
    posting_snapshots,
    posting_tags,
    posting_triage,
    postings,
    profile_details,
    profile_rejections,
    record_lines,
    record_sources,
    records,
    rejected_suggestions,
    skill_aliases,
    skill_link_overrides,
    skills,
    tags,
    tailored_cv_items,
    tailored_cvs,
)
from .db import profile_suggestions as document_suggestions
from .userdata import (
    CLOSED_STATUSES,
    DETAIL_KINDS,
    LINK_RELATIONS,
    OPEN_STATUSES,
    RECORD_KINDS,
    SKILL_LEVELS,
    STATUSES,
    collapse,
    ground_quote,
    identity_claim,
    identity_cover,
    identity_ground,
    identity_highlight,
    identity_level,
    identity_line,
    identity_part_of,
    identity_record,
    identity_source,
    level_rank,
    name_key,
    quote_found,
    record_identity,
    record_label,
)

SORTS = ("last_seen", "first_seen", "posted", "interest")
DISMISSED_MODES = ("hidden", "included", "only")
WORKPLACE_TYPES = ("On-site", "Hybrid", "Remote")
STATUS_FILTERS = ("any", "none") + STATUSES
LABELLED_FILTERS = ("yes", "no")

# Core fields compared in the snapshot diff, besides the description text; every detail key in either snapshot is
# compared too. The posted date is left out: a parser may estimate it again at each capture, so it drifts.
DIFF_FIELDS = (
    "title",
    "company",
    "location",
    "workplace_type",
    "employment_type",
)


def detail_label(name: str) -> str:
    """A detail's name made readable: `contract_length` -> "Contract length"."""
    words = " ".join(name.replace("_", " ").replace("-", " ").split())
    return words[:1].upper() + words[1:]


def snapshot_details(snapshot) -> tuple[dict, dict]:
    """(details, volatile details) of a snapshot row."""
    return json.loads(snapshot.details_json), json.loads(snapshot.volatile_json)


@dataclass(frozen=True)
class ListFilters:
    q: str = ""
    tag: str = ""
    min_interest: int | None = None
    unrated: bool = False
    workplace: str = ""
    status: str = ""
    dismissed: str = "hidden"
    sort: str = "last_seen"
    labelled: str = ""  # skill labelling flagged complete: "yes", "no" or either

    @classmethod
    def from_args(cls, args: Mapping[str, str]) -> ListFilters:
        """Parse query parameters; anything unrecognized falls back to the default."""

        def choice(name: str, allowed: tuple[str, ...], default: str = "") -> str:
            value = args.get(name, "")
            return value if value in allowed else default

        try:
            min_interest = int(args.get("min_interest", ""))
        except ValueError:
            min_interest = None
        return cls(
            q=args.get("q", "").strip(),
            tag=args.get("tag", "").strip(),
            min_interest=min_interest if min_interest in range(1, 6) else None,
            unrated=args.get("unrated", "") in ("1", "on", "true"),
            workplace=choice("workplace", WORKPLACE_TYPES),
            status=choice("status", STATUS_FILTERS),
            dismissed=choice("dismissed", DISMISSED_MODES, "hidden"),
            sort=choice("sort", SORTS, "last_seen"),
            labelled=choice("labelled", LABELLED_FILTERS),
        )

    def to_args(self) -> dict[str, str]:
        """Non-default values only, so URLs stay short and equal lists have equal URLs."""
        default = ListFilters()
        out = {}
        for f in fields(self):
            value = getattr(self, f.name)
            if value != getattr(default, f.name):
                out[f.name] = "1" if value is True else str(value)
        return out

    def with_(self, **changes) -> ListFilters:
        return replace(self, **changes)


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _latest_snapshots():
    """(job_id, snapshot_id) of each posting's newest snapshot."""
    return (
        select(posting_snapshots.c.job_id, func.max(posting_snapshots.c.id).label("snapshot_id"))
        .group_by(posting_snapshots.c.job_id)
        .subquery("newest")
    )


def _open_dismissals():
    return (
        select(posting_dismissals.c.job_id, posting_dismissals.c.id)
        .where(posting_dismissals.c.restored_at.is_(None))
        .subquery("open_dismissals")
    )


def tags_by_posting(conn: Connection, job_ids: list[int]) -> dict[int, list]:
    out: dict[str, list] = defaultdict(list)
    if not job_ids:
        return out
    rows = conn.execute(
        select(posting_tags.c.job_id, tags.c.id, tags.c.name)
        .join(tags, tags.c.id == posting_tags.c.tag_id)
        .where(posting_tags.c.job_id.in_(job_ids))
        .order_by(tags.c.name)
    )
    for row in rows:
        out[row.job_id].append({"id": row.id, "name": row.name})
    return out


def posting_list(conn: Connection, filters: ListFilters = ListFilters()) -> list[dict]:
    """One dict per posting, from its latest snapshot plus the user's data, filtered and sorted."""
    newest = _latest_snapshots()
    snap = posting_snapshots
    open_dis = _open_dismissals()
    stmt = (
        select(
            postings.c.job_id,
            postings.c.url,
            postings.c.first_seen_at,
            postings.c.last_seen_at,
            snap.c.title,
            snap.c.company,
            snap.c.location,
            snap.c.workplace_type,
            snap.c.posted_on_estimate,
            snap.c.posted_on_precision,
            posting_triage.c.interest,
            posting_triage.c.fit,
            posting_triage.c.skills_complete_at,
            newest.c.snapshot_id,
            open_dis.c.id.label("dismissal_id"),
            applications.c.id.label("application_id"),
            applications.c.status.label("application_status"),
        )
        .select_from(postings)
        .join(newest, newest.c.job_id == postings.c.job_id)
        .join(snap, snap.c.id == newest.c.snapshot_id)
        .outerjoin(posting_triage, posting_triage.c.job_id == postings.c.job_id)
        .outerjoin(open_dis, open_dis.c.job_id == postings.c.job_id)
        .outerjoin(applications, applications.c.job_id == postings.c.job_id)
    )

    if filters.q:
        pattern = f"%{_escape_like(filters.q)}%"
        stmt = stmt.where(
            or_(
                snap.c.title.ilike(pattern, escape="\\"),
                snap.c.company.ilike(pattern, escape="\\"),
                snap.c.description_text.ilike(pattern, escape="\\"),
                postings.c.external_id == filters.q.strip(),
            )
        )
    if filters.tag:
        stmt = stmt.where(
            exists(
                select(posting_tags.c.job_id)
                .join(tags, tags.c.id == posting_tags.c.tag_id)
                .where(posting_tags.c.job_id == postings.c.job_id, tags.c.key == name_key(filters.tag))
            )
        )
    if filters.min_interest is not None:
        stmt = stmt.where(posting_triage.c.interest >= filters.min_interest)
    if filters.unrated:
        stmt = stmt.where(posting_triage.c.interest.is_(None))
    if filters.workplace:
        stmt = stmt.where(snap.c.workplace_type == filters.workplace)
    if filters.status == "any":
        stmt = stmt.where(applications.c.id.is_not(None))
    elif filters.status == "none":
        stmt = stmt.where(applications.c.id.is_(None))
    elif filters.status:
        stmt = stmt.where(applications.c.status == filters.status)
    if filters.dismissed == "hidden":
        stmt = stmt.where(open_dis.c.id.is_(None))
    elif filters.dismissed == "only":
        stmt = stmt.where(open_dis.c.id.is_not(None))
    if filters.labelled == "yes":
        stmt = stmt.where(posting_triage.c.skills_complete_at.is_not(None))
    elif filters.labelled == "no":
        stmt = stmt.where(posting_triage.c.skills_complete_at.is_(None))

    # NULLs last on both databases: order by "is null" first (false sorts before true).
    order = {
        "last_seen": [postings.c.last_seen_at.desc()],
        "first_seen": [postings.c.first_seen_at.desc()],
        "posted": [
            snap.c.posted_on_estimate.is_(None),
            snap.c.posted_on_estimate.desc(),
            postings.c.last_seen_at.desc(),
        ],
        "interest": [
            posting_triage.c.interest.is_(None),
            posting_triage.c.interest.desc(),
            postings.c.last_seen_at.desc(),
        ],
    }[filters.sort]
    stmt = stmt.order_by(*order, postings.c.job_id.desc())

    rows = [dict(row._mapping) for row in conn.execute(stmt)]
    by_job = tags_by_posting(conn, [r["job_id"] for r in rows])
    pay = salary_summaries(conn, [r["job_id"] for r in rows])
    for row in rows:
        row["tags"] = by_job.get(row["job_id"], [])
        row["salary"], row["salary_more"] = pay.get(row["job_id"], (None, 0))
    return rows


def _latest_successful_runs():
    """(job_id, run_id) of each posting's newest successful app run on its latest snapshot. Eval runs (made by
    `jobhunt eval`) never reach the app."""
    newest = _latest_snapshots()
    return (
        select(posting_enrichments.c.job_id, func.max(posting_enrichments.c.id).label("run_id"))
        .join(newest, newest.c.snapshot_id == posting_enrichments.c.snapshot_id)
        .where(posting_enrichments.c.status == "succeeded", posting_enrichments.c.origin == "app")
        .group_by(posting_enrichments.c.job_id)
        .subquery("current_runs")
    )


def salary_summaries(conn: Connection, job_ids: list[int]) -> dict[int, tuple[dict, int]]:
    """job_id -> (first verified range of the latest successful run on the latest snapshot, further ranges)."""
    if not job_ids:
        return {}
    runs = _latest_successful_runs()
    out: dict[str, tuple[dict, int]] = {}
    for row in conn.execute(
        select(runs.c.job_id, enrichment_salaries)
        .join(enrichment_salaries, enrichment_salaries.c.enrichment_id == runs.c.run_id)
        .where(runs.c.job_id.in_(job_ids), enrichment_salaries.c.verified.is_(True))
        .order_by(runs.c.job_id, enrichment_salaries.c.position)
    ):
        if row.job_id in out:
            first, more = out[row.job_id]
            out[row.job_id] = (first, more + 1)
        else:
            out[row.job_id] = (dict(row._mapping), 0)
    return out


def all_tags(conn: Connection) -> list[str]:
    return list(conn.execute(select(tags.c.name).order_by(tags.c.key)).scalars())


def all_dismiss_reasons(conn: Connection) -> list:
    return conn.execute(select(dismiss_reasons).order_by(dismiss_reasons.c.position)).all()


def all_skills(conn: Connection) -> list:
    return conn.execute(select(skills).order_by(skills.c.key)).all()


# --- Posting detail ---


def posting_detail(conn: Connection, job_id: int) -> dict | None:
    posting = conn.execute(select(postings).where(postings.c.job_id == job_id)).first()
    if posting is None:
        return None

    snapshots = conn.execute(
        select(posting_snapshots, captures.c.captured_at)
        .join(captures, captures.c.id == posting_snapshots.c.capture_id)
        .where(posting_snapshots.c.job_id == job_id)
        .order_by(posting_snapshots.c.id)
    ).all()
    capture_rows = conn.execute(
        select(
            captures.c.id,
            captures.c.source_name,
            captures.c.captured_at,
            captures.c.imported_at,
            captures.c.sha256,
        )
        .where(captures.c.job_id == job_id)
        .order_by(captures.c.captured_at, captures.c.id)
    ).all()
    latest = snapshots[-1]

    dismissals = conn.execute(
        select(posting_dismissals)
        .where(posting_dismissals.c.job_id == job_id)
        .order_by(posting_dismissals.c.dismissed_at, posting_dismissals.c.id)
    ).all()
    reasons: dict[int, list[str]] = defaultdict(list)
    if dismissals:
        for row in conn.execute(
            select(posting_dismissal_reasons.c.dismissal_id, dismiss_reasons.c.label)
            .join(dismiss_reasons, dismiss_reasons.c.id == posting_dismissal_reasons.c.reason_id)
            .where(posting_dismissal_reasons.c.dismissal_id.in_([d.id for d in dismissals]))
            .order_by(dismiss_reasons.c.position)
        ):
            reasons[row.dismissal_id].append(row.label)

    levels = skill_levels(conn)
    marks = [
        {
            **row._mapping,
            "found": quote_found(row.quote, latest.description_html),
            "level": levels.get(row.skill_id, (None,))[0],
        }
        for row in conn.execute(
            select(
                posting_skill_marks.c.id,
                posting_skill_marks.c.quote,
                posting_skill_marks.c.snapshot_id,
                posting_skill_marks.c.created_at,
                posting_skill_marks.c.importance,
                posting_skill_marks.c.origin,
                skills.c.id.label("skill_id"),
                skills.c.name.label("skill_name"),
            )
            .join(skills, skills.c.id == posting_skill_marks.c.skill_id)
            .where(posting_skill_marks.c.job_id == job_id)
            .order_by(skills.c.key, posting_skill_marks.c.id)
        )
    ]

    details, volatile = snapshot_details(latest)
    return {
        "posting": posting,
        "latest": latest,
        "details": details,
        "volatile_details": volatile,
        "snapshots": snapshots,
        "captures": capture_rows,
        "triage": conn.execute(select(posting_triage).where(posting_triage.c.job_id == job_id)).first(),
        "tags": tags_by_posting(conn, [job_id]).get(job_id, []),
        "dismissals": [{**d._mapping, "reasons": reasons[d.id]} for d in dismissals],
        "dismissed": any(d.restored_at is None for d in dismissals),
        "marks": marks,
        "application": conn.execute(select(applications).where(applications.c.job_id == job_id)).first(),
    }


def snapshot_diff(conn: Connection, job_id: int, old_id: int, new_id: int) -> dict | None:
    """Changed captured fields and a line diff of the description between two snapshots of one posting."""
    rows = {
        row.id: row
        for row in conn.execute(
            select(posting_snapshots, captures.c.captured_at)
            .join(captures, captures.c.id == posting_snapshots.c.capture_id)
            .where(posting_snapshots.c.job_id == job_id, posting_snapshots.c.id.in_([old_id, new_id]))
        )
    }
    if old_id not in rows or new_id not in rows:
        return None
    old, new = rows[old_id], rows[new_id]
    changed = [
        (detail_label(name), getattr(old, name), getattr(new, name))
        for name in DIFF_FIELDS
        if getattr(old, name) != getattr(new, name)
    ]
    (old_details, _), (new_details, _) = snapshot_details(old), snapshot_details(new)
    changed += [
        (detail_label(name), old_details.get(name), new_details.get(name))
        for name in sorted(set(old_details) | set(new_details))
        if old_details.get(name) != new_details.get(name)
    ]
    old_lines, new_lines = old.description_text.splitlines(), new.description_text.splitlines()
    lines: list[tuple[str, str]] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False).get_opcodes():
        if op == "equal":
            lines += [("equal", line) for line in old_lines[i1:i2]]
        else:
            lines += [("delete", line) for line in old_lines[i1:i2]]
            lines += [("insert", line) for line in new_lines[j1:j2]]
    return {"old": old, "new": new, "fields": changed, "lines": lines}


# --- Skills page ---


def skills_overview(conn: Connection) -> list[dict]:
    """Every skill with its level (its claim's, or for an alias the claim of the skill it stands for), whether it is
    in the profile (has a claim), what it is an alias of, how many postings mark it, and how many of those have
    interest >= 4."""
    high = case((posting_triage.c.interest >= 4, posting_skill_marks.c.job_id))
    stmt = (
        select(
            skills.c.id,
            skills.c.name,
            func.count(distinct(posting_skill_marks.c.job_id)).label("postings"),
            func.count(distinct(high)).label("high_interest"),
        )
        .select_from(skills)
        .outerjoin(posting_skill_marks, posting_skill_marks.c.skill_id == skills.c.id)
        .outerjoin(posting_triage, posting_triage.c.job_id == posting_skill_marks.c.job_id)
        .group_by(skills.c.id, skills.c.name, skills.c.key)
        .order_by(func.count(distinct(posting_skill_marks.c.job_id)).desc(), skills.c.key)
    )
    levels = skill_levels(conn)
    claimed = set(conn.execute(select(claims.c.skill_id)).scalars())
    kept = skills.alias("kept")
    alias_of = dict(
        conn.execute(
            select(skills.c.id, kept.c.name)
            .join(skill_aliases, skill_aliases.c.alias_key == skills.c.key)
            .join(kept, kept.c.id == skill_aliases.c.skill_id)
        ).all()
    )
    return [
        {
            **row._mapping,
            "level": levels.get(row.id, (None, None))[0],
            "level_origin": levels.get(row.id, (None, None))[1],
            "in_profile": row.id in claimed,
            "alias_of": alias_of.get(row.id),
        }
        for row in conn.execute(stmt)
    ]


# --- Model output and the queue ---


def _marked_keys(conn: Connection, job_id: int) -> set[str]:
    return set(
        conn.execute(
            select(skills.c.key)
            .join(posting_skill_marks, posting_skill_marks.c.skill_id == skills.c.id)
            .where(posting_skill_marks.c.job_id == job_id)
        ).scalars()
    )


def eval_set_counts(conn: Connection) -> dict:
    """How many postings flagged complete are in each eval set, and how many holdout postings weren't drawn."""
    rows = conn.execute(
        select(posting_triage.c.eval_set, posting_triage.c.eval_set_origin).where(
            posting_triage.c.skills_complete_at.is_not(None)
        )
    ).all()
    holdout = [origin for name, origin in rows if name == "holdout"]
    return {
        "dev": sum(name == "dev" for name, _ in rows),
        "holdout": len(holdout),
        "holdout_not_drawn": sum(origin != "drawn" for origin in holdout),
    }


def rejected_keys(conn: Connection, job_id: int) -> dict[str, str | None]:
    """Rejected skill keys for a posting, each with its reason (None for rejections made before reasons)."""
    return dict(
        conn.execute(
            select(rejected_suggestions.c.skill_key, rejected_suggestions.c.reason).where(
                rejected_suggestions.c.job_id == job_id
            )
        ).all()
    )


def enrichment_panel(conn: Connection, job_id: int, run_id: int | None = None) -> dict | None:
    """The "Model says" panel: the chosen (or latest) app run with its items, every app run, and per-skill flags.
    None when the posting has no app runs; eval runs are never shown."""
    latest_id = conn.execute(
        select(func.max(posting_snapshots.c.id)).where(posting_snapshots.c.job_id == job_id)
    ).scalar()
    runs = [
        {**row._mapping, "stale": row.snapshot_id != latest_id}
        for row in conn.execute(
            select(
                posting_enrichments.c.id,
                posting_enrichments.c.snapshot_id,
                posting_enrichments.c.model,
                posting_enrichments.c.pipeline,
                posting_enrichments.c.status,
                posting_enrichments.c.error,
                posting_enrichments.c.started_at,
                posting_enrichments.c.finished_at,
            )
            .where(posting_enrichments.c.job_id == job_id, posting_enrichments.c.origin == "app")
            .order_by(posting_enrichments.c.id.desc())
        )
    ]
    if not runs:
        return None
    run = next((r for r in runs if r["id"] == run_id), runs[0])

    marked, rejected = _marked_keys(conn, job_id), rejected_keys(conn, job_id)
    skill_items = [
        {**row._mapping, "marked": row.key in marked, "rejected": row.key in rejected, "reason": rejected.get(row.key)}
        for row in conn.execute(
            select(enrichment_skills)
            .where(enrichment_skills.c.enrichment_id == run["id"])
            .order_by(enrichment_skills.c.position)
        )
    ]
    salary_items = [
        dict(row._mapping)
        for row in conn.execute(
            select(enrichment_salaries)
            .where(enrichment_salaries.c.enrichment_id == run["id"])
            .order_by(enrichment_salaries.c.position)
        )
    ]
    shown = [s for s in skill_items if s["verified"] and not s["rejected"]]
    return {
        "run": run,
        "runs": runs,
        "stale": run["stale"],
        "acceptable": run["status"] == "succeeded" and not run["stale"],
        "salaries": [s for s in salary_items if s["verified"]],
        "unverified_salaries": [s for s in salary_items if not s["verified"]],
        "skills": {imp: [s for s in shown if s["importance"] == imp] for imp in ("required", "preferred")},
        "rejected": [s for s in skill_items if s["verified"] and s["rejected"]],
        "unverified_skills": [s for s in skill_items if not s["verified"]],
    }


def unextracted_ids(conn: Connection, filters: ListFilters, model: str | None, pipeline: str) -> list[str]:
    """Listed, non-dismissed postings with no successful app run for their latest snapshot with this model and
    pipeline, and no queued or running job: what bulk extraction queues. Eval runs don't count."""
    rows = [r for r in posting_list(conn, filters) if r["dismissal_id"] is None]
    if not rows or not model:
        return []
    ids = [r["job_id"] for r in rows]
    done = {
        (row.job_id, row.snapshot_id)
        for row in conn.execute(
            select(posting_enrichments.c.job_id, posting_enrichments.c.snapshot_id).where(
                posting_enrichments.c.job_id.in_(ids),
                posting_enrichments.c.status == "succeeded",
                posting_enrichments.c.origin == "app",
                posting_enrichments.c.model == model,
                posting_enrichments.c.pipeline == pipeline,
            )
        )
    }
    busy = set(
        conn.execute(
            select(llm_jobs.c.job_id).where(llm_jobs.c.job_id.in_(ids), llm_jobs.c.status.in_(("queued", "running")))
        ).scalars()
    )
    return [r["job_id"] for r in rows if (r["job_id"], r["snapshot_id"]) not in done and r["job_id"] not in busy]


def unextracted_count(conn: Connection, filters: ListFilters, model: str | None, pipeline: str) -> int:
    return len(unextracted_ids(conn, filters, model, pipeline))


QUEUE_RECENT = 10


def _job_rows(conn: Connection, *where, limit: int | None = None) -> list[dict]:
    stmt = (
        select(
            llm_jobs, posting_snapshots.c.title, posting_snapshots.c.company, documents.c.label.label("document_label")
        )
        .outerjoin(posting_snapshots, posting_snapshots.c.id == llm_jobs.c.snapshot_id)
        .outerjoin(documents, documents.c.id == llm_jobs.c.document_id)
        .where(*where)
        .order_by(llm_jobs.c.id.desc() if limit else llm_jobs.c.id)
        .limit(limit)
    )
    return [
        {
            **row._mapping,
            "cancelling": row.status == "cancelled" and row.started_at is not None and row.finished_at is None,
        }
        for row in conn.execute(stmt)
    ]


def queue_overview(conn: Connection) -> dict:
    """Running and queued jobs in order, the most recent finished ones, and whether anything is still busy."""
    active = _job_rows(conn, llm_jobs.c.status.in_(("queued", "running")))
    recent = _job_rows(conn, llm_jobs.c.status.not_in(("queued", "running")), limit=QUEUE_RECENT)
    return {
        "active": active,
        "recent": recent,
        "busy": bool(active) or any(j["cancelling"] for j in recent),
        "queued": sum(j["status"] == "queued" for j in active),
        "running": sum(j["status"] == "running" for j in active),
    }


def posting_job(conn: Connection, job_id: int) -> dict | None:
    """The posting's newest extraction job, for the detail page."""
    rows = _job_rows(conn, llm_jobs.c.job_id == job_id, limit=1)
    return rows[0] if rows else None


# --- Applications ---


def is_due(app, today: date | None = None) -> bool:
    """An open application whose next action is due today or earlier."""
    today = today or date.today()
    return bool(
        app["status"] in OPEN_STATUSES
        and app["next_action"]
        and app["next_action_due"] is not None
        and app["next_action_due"] <= today
    )


def _applications(conn: Connection, *where) -> list[dict]:
    last_event = (
        select(application_events.c.application_id, func.max(application_events.c.event_date).label("last_event"))
        .group_by(application_events.c.application_id)
        .subquery("last_event")
    )
    stmt = (
        select(applications, postings.c.url.label("posting_url"), last_event.c.last_event)
        .outerjoin(postings, postings.c.job_id == applications.c.job_id)
        .outerjoin(last_event, last_event.c.application_id == applications.c.id)
        .where(*where)
        .order_by(applications.c.updated_at.desc(), applications.c.id.desc())
    )
    rows = [dict(row._mapping) for row in conn.execute(stmt)]
    for row in rows:
        row["due"] = is_due(row)
    return rows


def applications_board(conn: Connection) -> dict:
    """Open statuses in pipeline order, then closed ones, plus open next actions by due date."""
    apps = _applications(conn)
    by_status = {status: [a for a in apps if a["status"] == status] for status in STATUSES}
    next_actions = sorted(
        (a for a in apps if a["status"] in OPEN_STATUSES and a["next_action"]),
        key=lambda a: (a["next_action_due"] is None, a["next_action_due"] or date.max, a["id"]),
    )
    return {
        "open": [(s, by_status[s]) for s in OPEN_STATUSES],
        "closed": [(s, by_status[s]) for s in CLOSED_STATUSES],
        "closed_count": sum(len(by_status[s]) for s in CLOSED_STATUSES),
        "next_actions": next_actions,
        "count": len(apps),
    }


def manual_applications(conn: Connection) -> list[dict]:
    """Applications not linked to any posting, for linking later."""
    return _applications(conn, applications.c.job_id.is_(None))


def contacts_with_emails(conn: Connection, *where) -> list[dict]:
    rows = [
        dict(row._mapping)
        for row in conn.execute(
            select(contacts, companies.c.name.label("company_name"))
            .outerjoin(companies, companies.c.id == contacts.c.company_id)
            .where(*where)
            .order_by(contacts.c.name, contacts.c.id)
        )
    ]
    emails: dict[int, list[str]] = defaultdict(list)
    if rows:
        for row in conn.execute(
            select(contact_emails)
            .where(contact_emails.c.contact_id.in_([r["id"] for r in rows]))
            .order_by(contact_emails.c.id)
        ):
            emails[row.contact_id].append(row.email)
    for row in rows:
        row["emails"] = emails[row["id"]]
    return rows


def application_detail(conn: Connection, app_id: int) -> dict | None:
    found = _applications(conn, applications.c.id == app_id)
    if not found:
        return None
    app = found[0]
    posting = None
    if app["job_id"]:
        snapshot = conn.execute(
            select(posting_snapshots.c.title, posting_snapshots.c.company)
            .where(posting_snapshots.c.job_id == app["job_id"])
            .order_by(posting_snapshots.c.id.desc())
            .limit(1)
        ).first()
        posting = {
            "job_id": app["job_id"],
            "url": app["posting_url"],
            "title": snapshot.title,
            "company": snapshot.company,
        }
    linked_docs = conn.execute(
        select(documents)
        .join(application_documents, application_documents.c.document_id == documents.c.id)
        .where(application_documents.c.application_id == app_id)
        .order_by(documents.c.uploaded_at.desc())
    ).all()
    linked_contact_ids = select(application_contacts.c.contact_id).where(
        application_contacts.c.application_id == app_id
    )
    return {
        "app": app,
        "posting": posting,
        "events": conn.execute(
            select(application_events)
            .where(application_events.c.application_id == app_id)
            .order_by(application_events.c.event_date, application_events.c.id)
        ).all(),
        "documents": linked_docs,
        "contacts": contacts_with_emails(conn, contacts.c.id.in_(linked_contact_ids)),
        "all_documents": conn.execute(select(documents).order_by(documents.c.uploaded_at.desc())).all(),
        "all_contacts": contacts_with_emails(conn),
    }


# --- Documents ---


def documents_list(conn: Connection) -> list[dict]:
    links = (
        select(application_documents.c.document_id, func.count().label("applications"))
        .group_by(application_documents.c.document_id)
        .subquery("links")
    )
    return [
        dict(row._mapping)
        for row in conn.execute(
            select(documents, func.coalesce(links.c.applications, 0).label("applications"))
            .outerjoin(links, links.c.document_id == documents.c.id)
            .order_by(documents.c.uploaded_at.desc(), documents.c.id.desc())
        )
    ]


def document_detail(conn: Connection, document_id: int) -> dict | None:
    doc = conn.execute(select(documents).where(documents.c.id == document_id)).first()
    if doc is None:
        return None
    linked = conn.execute(
        select(applications)
        .join(application_documents, application_documents.c.application_id == applications.c.id)
        .where(application_documents.c.document_id == document_id)
        .order_by(applications.c.company, applications.c.title)
    ).all()
    jobs = _job_rows(conn, llm_jobs.c.document_id == document_id, limit=1)
    offered = profile_suggestions(conn)
    pending = sum(document_id in s["document_ids"] for kind in SUGGESTION_KINDS for s in offered[kind])
    return {"doc": doc, "applications": linked, "suggestions": pending, "profile_job": jobs[0] if jobs else None}


# --- Companies ---


def company_by_name(conn: Connection, name: str):
    return conn.execute(select(companies).where(companies.c.key == name_key(name))).first()


def companies_overview(conn: Connection) -> list[dict]:
    """Every company record with how many postings, applications and contacts match it."""
    rows = [dict(row._mapping) for row in conn.execute(select(companies).order_by(companies.c.key))]
    posting_keys = [name_key(r["company"]) for r in posting_list(conn, ListFilters(dismissed="included"))]
    app_keys = [name_key(c) for c in conn.execute(select(applications.c.company)).scalars()]
    contact_counts = dict(
        conn.execute(select(contacts.c.company_id, func.count()).group_by(contacts.c.company_id)).all()
    )
    for row in rows:
        row["postings"] = posting_keys.count(row["key"])
        row["applications"] = app_keys.count(row["key"])
        row["contacts"] = contact_counts.get(row["id"], 0)
    return rows


def company_page(conn: Connection, company_id: int) -> dict | None:
    """The company with the postings and applications whose company name matches its key (design D4)."""
    company = conn.execute(select(companies).where(companies.c.id == company_id)).first()
    if company is None:
        return None
    matching_postings = [
        r for r in posting_list(conn, ListFilters(dismissed="included")) if name_key(r["company"]) == company.key
    ]
    matching_apps = [a for a in _applications(conn) if name_key(a["company"]) == company.key]
    return {
        "company": company,
        "postings": matching_postings,
        "applications": matching_apps,
        "contacts": contacts_with_emails(conn, contacts.c.company_id == company_id),
    }


def contact_detail(conn: Connection, contact_id: int) -> dict | None:
    found = contacts_with_emails(conn, contacts.c.id == contact_id)
    if not found:
        return None
    linked = conn.execute(
        select(applications)
        .join(application_contacts, application_contacts.c.application_id == applications.c.id)
        .where(application_contacts.c.contact_id == contact_id)
        .order_by(applications.c.company, applications.c.title)
    ).all()
    return {"contact": found[0], "applications": linked}


def all_companies(conn: Connection) -> list:
    return conn.execute(select(companies).order_by(companies.c.key)).all()


# --- The profile ---


def resolve_skill(conn: Connection, key: str):
    """The skill a key stands for in the profile: the skill it is an alias of, else the skill with that key, else
    None."""
    row = conn.execute(
        select(skills)
        .join(skill_aliases, skill_aliases.c.skill_id == skills.c.id)
        .where(skill_aliases.c.alias_key == key)
    ).first()
    return row if row is not None else conn.execute(select(skills).where(skills.c.key == key)).first()


def profile_skills(conn: Connection) -> list:
    """Every skill with a claim (the profile's skills), by key: id, name and key, with the claim's level,
    level_origin and claim_id."""
    return conn.execute(
        select(skills.c.id, skills.c.name, skills.c.key, claims.c.level, claims.c.level_origin,
               claims.c.id.label("claim_id"))
        .join(claims, claims.c.skill_id == skills.c.id)
        .order_by(skills.c.key)
    ).all()


def same_identity(conn: Connection, profile: list | None = None) -> dict[str, object]:
    """key -> the profile skill (a profile_skills row) a posting skill with that key is the same as: the profile
    skill with that key, or the one the key is an alias of."""
    profile = profile_skills(conn) if profile is None else profile
    by_id = {s.id: s for s in profile}
    out = {
        row.alias_key: by_id[row.skill_id]
        for row in conn.execute(select(skill_aliases))
        if row.skill_id in by_id
    }
    out.update({s.key: s for s in profile})
    return out


def skill_levels(conn: Connection) -> dict[int, tuple[str, str]]:
    """skill id -> (level, level_origin) for every skill whose identity has a claim: its own claim's, or, for a
    skill that is an alias, the claim of the skill it stands for."""
    claimed = {
        row.skill_id: (row.level, row.level_origin)
        for row in conn.execute(select(claims.c.skill_id, claims.c.level, claims.c.level_origin))
    }
    out = dict(claimed)
    for row in conn.execute(
        select(skills.c.id, skill_aliases.c.skill_id.label("kept"))
        .join(skill_aliases, skill_aliases.c.alias_key == skills.c.key)
    ):
        if row.kept in claimed and row.id not in claimed:
            out[row.id] = claimed[row.kept]
    return out


def record_sort_key(record: Mapping) -> tuple:
    """Within a kind (design D3): ongoing records first, then by end date (else start date), newest first, then
    records without dates; ties in creation order. Partial dates ('2022', '2022-09') compare as year and month."""
    date = record["end_date"] or record["start_date"]
    group = 0 if record["ongoing"] else (1 if date else 2)
    newest = 0
    if date:
        year, _, month = date.partition("-")
        newest = -(int(year) * 100 + int(month or 0))
    return group, newest, record["id"]


def _effective_disclosure(record_id: int, rows: Mapping[int, dict]) -> tuple[str, bool]:
    """(effective disclosure, private only through its context): private when the record or any record it is part
    of, directly or through others, is private."""
    seen, current = set(), rows[record_id]["part_of_id"]
    own = rows[record_id]["disclosure"]
    while current is not None and current not in seen and current in rows:
        seen.add(current)
        if rows[current]["disclosure"] == "private":
            return "private", own != "private"
        current = rows[current]["part_of_id"]
    return own, False


def profile(conn: Connection) -> dict:
    """The profile page's data: details in kind order; records grouped by kind (RECORD_KINDS order), sorted by
    record_sort_key, each with its lines, sources, effective disclosure, the record it is part of, the records
    part of it and the claims it grounds; claims grouped by level, highest first, each with its grounds, the
    highlights covering it, its aliases and the ungrounded and no-highlight flags; highlights in creation order with
    the claims they cover; counts; and choices of records and claims for the edit forms."""
    details = sorted(
        (dict(r._mapping) for r in conn.execute(select(profile_details))),
        key=lambda d: (DETAIL_KINDS.index(d["kind"]) if d["kind"] in DETAIL_KINDS else len(DETAIL_KINDS), d["id"]),
    )
    rows = {
        r.id: {**r._mapping, "label": record_label(r), "lines": [], "sources": [], "dependents": [], "grounds": []}
        for r in conn.execute(select(records))
    }
    for line in conn.execute(select(record_lines).order_by(record_lines.c.position, record_lines.c.id)):
        rows[line.record_id]["lines"].append(dict(line._mapping))
    for source in conn.execute(
        select(record_sources, documents.c.label.label("document_label"))
        .outerjoin(documents, documents.c.id == record_sources.c.document_id)
        .order_by(record_sources.c.position, record_sources.c.id)
    ):
        rows[source.record_id]["sources"].append(dict(source._mapping))
    for r in rows.values():
        parent = rows.get(r["part_of_id"])
        r["part_of"] = {"id": parent["id"], "label": parent["label"]} if parent else None
        if parent:
            parent["dependents"].append({"id": r["id"], "label": r["label"]})
        r["effective_disclosure"], r["private_through_context"] = _effective_disclosure(r["id"], rows)
        r["context_lost"] = r["context_lost_at"] is not None

    claim_rows = {
        r.claim_id: {**r._mapping, "skill_id": r.id, "grounds": [], "highlights": [], "aliases": []}
        for r in conn.execute(
            select(skills.c.id, skills.c.name, skills.c.key, claims.c.id.label("claim_id"), claims.c.level,
                   claims.c.level_origin, claims.c.origin)
            .join(claims, claims.c.skill_id == skills.c.id)
            .order_by(skills.c.key)
        )
    }
    by_skill = {c["skill_id"]: c for c in claim_rows.values()}
    for g in conn.execute(select(claim_records).order_by(claim_records.c.created_at, claim_records.c.record_id)):
        claim, record = claim_rows[g.claim_id], rows[g.record_id]
        claim["grounds"].append({**g._mapping, "record_label": record["label"]})
        record["grounds"].append({"skill_id": claim["skill_id"], "name": claim["name"], "quote": g.quote})
    highlight_rows = {
        h.id: {**h._mapping, "claims": []} for h in conn.execute(select(highlights).order_by(highlights.c.id))
    }
    for c in conn.execute(
        select(highlight_claims).order_by(highlight_claims.c.created_at, highlight_claims.c.claim_id)
    ):
        claim, highlight = claim_rows[c.claim_id], highlight_rows[c.highlight_id]
        claim["highlights"].append({**c._mapping, "text": highlight["text"]})
        highlight["claims"].append({**c._mapping, "skill_id": claim["skill_id"], "name": claim["name"]})
    for a in conn.execute(
        select(skill_aliases, skills.c.name.label("alias_name"))
        .outerjoin(skills, skills.c.key == skill_aliases.c.alias_key)
        .order_by(skill_aliases.c.alias_key)
    ):
        if a.skill_id in by_skill:
            by_skill[a.skill_id]["aliases"].append({"key": a.alias_key, "name": a.alias_name or a.alias_key})
    for claim in claim_rows.values():
        claim["ungrounded"] = not claim["grounds"] and claim["level"] != "missing"
        claim["no_highlight"] = not claim["highlights"]

    grouped = [
        (kind, sorted((r for r in rows.values() if r["kind"] == kind), key=record_sort_key)) for kind in RECORD_KINDS
    ]
    grouped = [(kind, group) for kind, group in grouped if group]
    claim_list = list(claim_rows.values())
    return {
        "details": details,
        "records": grouped,
        "claims": [
            (level, [c for c in claim_list if c["level"] == level])
            for level in reversed(SKILL_LEVELS) if any(c["level"] == level for c in claim_list)
        ],
        "highlights": list(highlight_rows.values()),
        "counts": {
            "records": len(rows),
            "by_kind": {kind: len(group) for kind, group in grouped},
            "claims": len(claim_list),
            "ungrounded": sum(c["ungrounded"] for c in claim_list),
            "no_highlight": sum(c["no_highlight"] for c in claim_list),
            "highlights": len(highlight_rows),
        },
        "record_choices": [{"id": r["id"], "label": f"{kind}: {r['label']}"} for kind, group in grouped for r in group],
        "claim_choices": [{"skill_id": c["skill_id"], "name": c["name"]} for c in claim_list],
    }


def _context_candidates(conn: Connection) -> dict[int, list[tuple]]:
    """claim's skill id -> its grounds and quoted coverages as (created_at, 0 for a ground or 1 for coverage, record
    or highlight id, quote), oldest first."""
    out: dict[int, list[tuple]] = defaultdict(list)
    for row in conn.execute(
        select(claims.c.skill_id, claim_records.c.created_at, claim_records.c.record_id, claim_records.c.quote)
        .join(claims, claims.c.id == claim_records.c.claim_id)
    ):
        out[row.skill_id].append((row.created_at, 0, row.record_id, row.quote))
    for row in conn.execute(
        select(
            claims.c.skill_id, highlight_claims.c.created_at, highlight_claims.c.highlight_id, highlight_claims.c.quote
        )
        .join(claims, claims.c.id == highlight_claims.c.claim_id)
        .where(highlight_claims.c.quote.is_not(None))
    ):
        out[row.skill_id].append((row.created_at, 1, row.highlight_id, row.quote))
    for candidates in out.values():
        candidates.sort(key=lambda c: c[:3])
    return out


def expansion_contexts(conn: Connection) -> dict[int, tuple[tuple[str, int], str]]:
    """skill id -> ((source, id), quote): what gives a profile skill's phrasings their context, the oldest of its
    claim's grounds and quoted highlight coverages by when each was added; on a tie a ground first, then by record
    or highlight id. `source` is 'record' or 'highlight'. Skills with neither are left out."""
    return {
        skill_id: (("record" if c[1] == 0 else "highlight", c[2]), c[3])
        for skill_id, (c, *_) in _context_candidates(conn).items()
    }


def context_lines(conn: Connection) -> dict[int, tuple[str, str]]:
    """skill id -> (quote, line) for the context expansion_contexts chooses: for a ground, the record's description
    line holding the quote, else its title and organisation; for coverage, the highlight's text. Skills without a
    context are left out."""
    contexts = expansion_contexts(conn)
    if not contexts:
        return {}
    wanted_records = {ref[1] for ref, _ in contexts.values() if ref[0] == "record"}
    lines: dict[int, list[str]] = defaultdict(list)
    titles: dict[int, str] = {}
    if wanted_records:
        for row in conn.execute(select(records).where(records.c.id.in_(wanted_records))):
            titles[row.id] = ground_quote(row)
        for row in conn.execute(
            select(record_lines.c.record_id, record_lines.c.text)
            .where(record_lines.c.record_id.in_(wanted_records))
            .order_by(record_lines.c.position, record_lines.c.id)
        ):
            lines[row.record_id].append(row.text)
    texts = dict(conn.execute(select(highlights.c.id, highlights.c.text)).all())
    out: dict[int, tuple[str, str]] = {}
    for skill_id, ((source, ref), quote) in contexts.items():
        if source == "highlight":
            line = texts.get(ref)
        else:
            needle = collapse(quote).casefold()
            line = next((t for t in lines[ref] if needle in collapse(t).casefold()), None) or titles.get(ref)
        out[skill_id] = (quote, line or quote)
    return out


def profile_rejections_list(conn: Connection) -> list:
    """Remembered rejections, newest first."""
    return conn.execute(
        select(profile_rejections).order_by(profile_rejections.c.created_at.desc(), profile_rejections.c.id.desc())
    ).all()


def stale_override_count(conn: Connection) -> int:
    """Link overrides whose profile skill has left the profile; they are ignored."""
    return conn.execute(
        select(func.count())
        .select_from(skill_link_overrides)
        .outerjoin(claims, claims.c.skill_id == skill_link_overrides.c.skill_id)
        .where(skill_link_overrides.c.skill_id.is_not(None), claims.c.id.is_(None))
    ).scalar_one()


# --- Document suggestions for the profile ---
#
# A succeeded document run stores its verified suggestions (profile_suggestions). What is offered is worked out
# here on each read, against the profile as it is now (design D6): nothing about pending state is stored.

SUGGESTION_KINDS = ("record", "claim", "part_of", "highlight")  # in dependency order


class _Profile:
    """The profile's identities, for matching suggestions."""

    def __init__(self, conn: Connection):
        self.rejected = set(conn.execute(select(profile_rejections.c.identity)).scalars())
        self.aliases = {
            row.alias_key: row.key
            for row in conn.execute(
                select(skill_aliases.c.alias_key, skills.c.key).join(skills, skills.c.id == skill_aliases.c.skill_id)
            )
        }
        self.names = dict(conn.execute(select(skills.c.key, skills.c.name)).all())
        self.records: dict[str, int] = {}
        self.record_labels: dict[int, str] = {}
        identity_of: dict[int, str] = {}
        self.part_of: dict[int, int | None] = {}
        for row in conn.execute(select(records).order_by(records.c.id)):
            identity_of[row.id] = record_identity(row)
            self.records.setdefault(identity_of[row.id], row.id)
            self.record_labels[row.id] = record_label(row)
            self.part_of[row.id] = row.part_of_id
        self.lines: dict[int, set[str]] = defaultdict(set)
        for row in conn.execute(select(record_lines.c.record_id, record_lines.c.text)):
            self.lines[row.record_id].add(identity_line(identity_of[row.record_id], row.text))
        self.sources: dict[int, set[str]] = defaultdict(set)
        for row in conn.execute(select(record_sources)):
            self.sources[row.record_id].add(identity_source(identity_of[row.record_id], row.url, row.document_id))
        self.claims = {
            row.key: row
            for row in conn.execute(
                select(skills.c.key, skills.c.name, claims.c.id, claims.c.level, claims.c.level_origin)
                .join(claims, claims.c.skill_id == skills.c.id)
            )
        }
        self.grounds = {
            (r.claim_id, r.record_id) for r in conn.execute(select(claim_records.c.claim_id, claim_records.c.record_id))
        }
        self.highlights: dict[str, int] = {}
        for row in conn.execute(select(highlights.c.id, highlights.c.text).order_by(highlights.c.id)):
            self.highlights.setdefault(identity_highlight(row.text), row.id)
        self.coverage = {
            (r.highlight_id, r.claim_id)
            for r in conn.execute(select(highlight_claims.c.highlight_id, highlight_claims.c.claim_id))
        }

    def resolve(self, name: str) -> str:
        """The key of the skill a suggested skill name stands for (through an alias)."""
        key = name_key(name)
        return self.aliases.get(key, key)


def _offer_runs(conn: Connection) -> list:
    """Each document's latest succeeded run that has suggestions, by document."""
    newest = (
        select(func.max(document_runs.c.id))
        .where(document_runs.c.status == "succeeded",
               exists(select(document_suggestions.c.id).where(document_suggestions.c.run_id == document_runs.c.id)))
        .group_by(document_runs.c.document_id)
    )
    return conn.execute(
        select(document_runs.c.id, document_runs.c.document_id, documents.c.label)
        .join(documents, documents.c.id == document_runs.c.document_id)
        .where(document_runs.c.id.in_(newest))
        .order_by(document_runs.c.document_id)
    ).all()


def _merge(offers: dict[str, dict], offer: dict, combine) -> None:
    """Add an offer, or fold it into the offer with the same identity from another document."""
    kept = offers.get(offer["identity"])
    if kept is None:
        offers[offer["identity"]] = offer
        return
    kept["ids"] += offer["ids"]
    for doc_id, label in zip(offer["document_ids"], offer["documents"], strict=True):
        if doc_id not in kept["document_ids"]:
            kept["document_ids"].append(doc_id)
            kept["documents"].append(label)
    combine(kept, offer)


def _union(kept: list[dict], more: list[dict]) -> None:
    have = {x["identity"] for x in kept}
    kept += [x for x in more if x["identity"] not in have]


def _combine_record(kept: dict, offer: dict) -> None:
    _union(kept["lines"], offer["lines"])
    _union(kept["sources"], offer["sources"])


def _combine_claim(kept: dict, offer: dict) -> None:
    _union(kept["grounds"], offer["grounds"])
    kept["waiting_on"] |= offer["waiting_on"]
    if offer["level"] and level_rank(offer["level"]) > level_rank(kept["level"]):
        kept["level"] = offer["level"]


def _combine_highlight(kept: dict, offer: dict) -> None:
    _union(kept["covers"], offer["covers"])
    kept["waiting_on"] |= offer["waiting_on"]


def _record_fields(payload: dict) -> dict:
    return {f: payload.get(f) for f in ("kind", "title", "organisation", "location", "start_date", "end_date")} | {
        "ongoing": bool(payload.get("ongoing"))
    }


def profile_suggestions(conn: Connection) -> dict:
    """What document runs offer the profile now, by kind (SUGGESTION_KINDS, each a list), plus `count`.

    Each offer: id (its first suggestion row), ids (every row folded into it, from every document), identity,
    status ('new', or 'adds' to an existing row), documents and document_ids, run_id (its first run). A record offer
    has record (fields), lines and sources ({identity, text} / {identity, kind, url}) and existing_id; a claim offer
    name, skill_key, claim_id, current_level, level (the level it sets, or None), grounds ({identity, record_id,
    label, quote}) and waiting (grounds on records not in the profile yet); a part_of offer record_id, part_of_id
    and both labels; a highlight offer text, existing_id, covers ({identity, skill_key, name, claim_id, quote}) and
    waiting (coverage of claims not in the profile yet). Anything whose identity is remembered as rejected, and
    suggestions with nothing left to offer, are left out."""
    state = _Profile(conn)
    rejected = state.rejected
    offers: dict[str, dict[str, dict]] = {kind: {} for kind in SUGGESTION_KINDS}
    for run in _offer_runs(conn):
        rows: dict[str, list] = defaultdict(list)
        for row in conn.execute(
            select(document_suggestions).where(document_suggestions.c.run_id == run.id)
            .order_by(document_suggestions.c.kind, document_suggestions.c.position)
        ):
            rows[row.kind].append((row.id, row.position, json.loads(row.payload_json)))
        base = {"documents": [run.label], "document_ids": [run.document_id], "run_id": run.id}
        record_ids = {
            pos: identity_record(**{f: p.get(f) for f in ("kind", "title", "organisation", "start_date", "end_date")})
            for _, pos, p in rows["record"]
        }
        record_labels = {pos: record_label(SimpleNamespace(**_record_fields(p))) for _, pos, p in rows["record"]}
        highlight_ids = {pos: identity_highlight(p["text"]) for _, pos, p in rows["highlight"]}

        for row_id, pos, p in rows["record"]:
            rid = record_ids[pos]
            if rid in rejected:
                continue
            existing = state.records.get(rid)
            lines = [{"identity": identity_line(rid, t), "text": t} for t in p.get("lines", [])]
            sources = [{"identity": identity_source(rid, s["url"]), **s} for s in p.get("sources", [])]
            lines = [
                x for x in lines if x["identity"] not in rejected and x["identity"] not in state.lines.get(existing, ())
            ]
            sources = [
                x
                for x in sources
                if x["identity"] not in rejected and x["identity"] not in state.sources.get(existing, ())
            ]
            if existing is not None and not lines and not sources:
                continue
            _merge(offers["record"], {
                **base, "id": row_id, "ids": [row_id], "identity": rid, "status": "adds" if existing else "new",
                "record": _record_fields(p), "label": record_labels[pos], "existing_id": existing,
                "lines": lines, "sources": sources,
            }, _combine_record)

        for row_id, _pos, p in rows["claim"]:
            key = state.resolve(p["name"])
            cid = identity_claim(key)
            if cid in rejected:
                continue
            claim = state.claims.get(key)
            grounds, waiting = [], set()
            for g in p.get("grounds", []):
                rid = record_ids.get(g["record"])
                if rid is None or rid in rejected or identity_ground(cid, rid) in rejected:
                    continue
                record_id = state.records.get(rid)
                if record_id is None:
                    waiting.add(rid)
                elif claim is None or (claim.id, record_id) not in state.grounds:
                    if all(x["record_id"] != record_id for x in grounds):
                        grounds.append({"identity": identity_ground(cid, rid), "record_id": record_id,
                                        "label": state.record_labels[record_id], "quote": g["quote"]})
            level = p["level"]
            if claim is not None:
                raise_level = (
                    claim.level_origin == "model" and level_rank(level) > level_rank(claim.level)
                    and identity_level(cid, level) not in rejected
                )
                level = level if raise_level else None
                if not grounds and level is None:
                    continue
            _merge(offers["claim"], {
                **base, "id": row_id, "ids": [row_id], "identity": cid, "status": "adds" if claim else "new",
                "name": claim.name if claim else state.names.get(key, p["name"]), "suggested_name": p["name"],
                "skill_key": key, "claim_id": claim.id if claim else None,
                "current_level": claim.level if claim else None, "level": level, "grounds": grounds,
                "waiting_on": waiting,
            }, _combine_claim)

        for row_id, _pos, p in rows["part_of"]:
            rid, pid = record_ids.get(p["record"]), record_ids.get(p["part_of"])
            if rid is None or pid is None or rid in rejected or pid in rejected:
                continue
            identity = identity_part_of(rid, pid)
            record_id, part_of_id = state.records.get(rid), state.records.get(pid)
            if (
                identity in rejected
                or record_id is None
                or part_of_id is None
                or state.part_of.get(record_id) is not None
            ):
                continue
            _merge(offers["part_of"], {
                **base, "id": row_id, "ids": [row_id], "identity": identity, "status": "new",
                "record_id": record_id, "record_label": state.record_labels[record_id],
                "part_of_id": part_of_id, "part_of_label": state.record_labels[part_of_id],
            }, lambda kept, offer: None)

        covering: dict[int, list[tuple[str, str | None]]] = defaultdict(list)
        for _, _, p in rows["claim"]:
            for c in p.get("coverage", []):
                covering[c["highlight"]].append((p["name"], c.get("quote")))
        for row_id, pos, p in rows["highlight"]:
            hid = highlight_ids[pos]
            if hid in rejected:
                continue
            existing = state.highlights.get(hid)
            covers, waiting = [], set()
            for name, quote in covering[pos]:
                key = state.resolve(name)
                cid = identity_claim(key)
                if cid in rejected or identity_cover(hid, cid) in rejected:
                    continue
                claim = state.claims.get(key)
                if claim is None:
                    waiting.add(cid)
                elif (existing is None or (existing, claim.id) not in state.coverage) and all(
                    x["claim_id"] != claim.id for x in covers
                ):
                    covers.append({"identity": identity_cover(hid, cid), "skill_key": key, "name": claim.name,
                                   "claim_id": claim.id, "quote": quote})
            if existing is not None and not covers:
                continue
            _merge(offers["highlight"], {
                **base, "id": row_id, "ids": [row_id], "identity": hid, "status": "adds" if existing else "new",
                "text": p["text"], "existing_id": existing, "covers": covers, "waiting_on": waiting,
            }, _combine_highlight)

    out: dict = {kind: list(offers[kind].values()) for kind in SUGGESTION_KINDS}
    for offer in out["claim"] + out["highlight"]:
        offer["waiting"] = len(offer.pop("waiting_on"))
    out["count"] = sum(len(out[kind]) for kind in SUGGESTION_KINDS)
    return out


# --- Posting skills and their links to the profile ---

IMPORTANCE_RANK = {"required": 2, "preferred": 1, None: 0}


def posting_skills(conn: Connection, job_id: int | None = None) -> list[dict]:
    """The skills each posting asks for (one posting's when job_id is given): its marks, plus the verified
    suggestions of its latest succeeded app run on its latest snapshot that the user hasn't rejected (for any
    reason). A posting skill is identified by its key; when a mark and a suggestion share one, the mark wins,
    and a skill marked at both importances is required. Rows: job_id, key, name, importance, quote, source
    ('mark' or 'suggestion') and skill_id (marks only), ordered by posting and key."""
    out: dict[tuple[str, str], dict] = {}
    mark_rows = select(
        posting_skill_marks.c.job_id,
        posting_skill_marks.c.importance,
        posting_skill_marks.c.quote,
        skills.c.id.label("skill_id"),
        skills.c.key,
        skills.c.name,
    ).join(skills, skills.c.id == posting_skill_marks.c.skill_id)
    if job_id is not None:
        mark_rows = mark_rows.where(posting_skill_marks.c.job_id == job_id)
    for row in conn.execute(mark_rows.order_by(posting_skill_marks.c.id)):
        kept = out.get((row.job_id, row.key))
        if kept is None:
            out[(row.job_id, row.key)] = {**row._mapping, "source": "mark"}
        elif IMPORTANCE_RANK[row.importance] > IMPORTANCE_RANK[kept["importance"]]:
            kept["importance"] = row.importance

    rejected = {
        (row.job_id, row.skill_key)
        for row in conn.execute(
            select(rejected_suggestions.c.job_id, rejected_suggestions.c.skill_key).where(
                *([rejected_suggestions.c.job_id == job_id] if job_id is not None else [])
            )
        )
    }
    runs = _latest_successful_runs()
    suggestion_rows = (
        select(runs.c.job_id, enrichment_skills.c.key, enrichment_skills.c.name, enrichment_skills.c.importance,
               enrichment_skills.c.quote)
        .join(enrichment_skills, enrichment_skills.c.enrichment_id == runs.c.run_id)
        .where(enrichment_skills.c.verified.is_(True))
    )
    if job_id is not None:
        suggestion_rows = suggestion_rows.where(runs.c.job_id == job_id)
    for row in conn.execute(suggestion_rows.order_by(runs.c.job_id, enrichment_skills.c.position)):
        if (row.job_id, row.key) in rejected:
            continue
        kept = out.get((row.job_id, row.key))
        if kept is None:
            out[(row.job_id, row.key)] = {**row._mapping, "source": "suggestion", "skill_id": None}
        elif kept["source"] == "suggestion" and IMPORTANCE_RANK[row.importance] > IMPORTANCE_RANK[kept["importance"]]:
            kept["importance"] = row.importance
    return [out[k] for k in sorted(out)]


def posting_skill_keys(conn: Connection) -> list[dict]:
    """Every posting skill across postings, by key: a display name (a mark's skill name, else the first
    suggestion's), one quote for context, and the number of postings asking for it, most asked first."""
    by_key: dict[str, dict] = {}
    for row in posting_skills(conn):
        kept = by_key.get(row["key"])
        if kept is None:
            by_key[row["key"]] = {
                "key": row["key"],
                "name": row["name"],
                "quote": row["quote"],
                "jobs": {row["job_id"]},
            }
            continue
        kept["jobs"].add(row["job_id"])
        if row["source"] == "mark":
            kept["name"] = row["name"]
    keys = [{**k, "postings": len(k.pop("jobs"))} for k in by_key.values()]
    return sorted(keys, key=lambda k: (-k["postings"], k["key"]))


def effective_links(conn: Connection, keys: list[str] | None = None) -> dict[str, dict]:
    """posting key -> its link, found in this order: the user's override (ignored, and flagged stale, when its
    skill has left the profile), a profile skill with the same key or of which the key is an alias ('same'), the
    latest succeeded judgment
    (relations to skills outside the profile ignored; same > specific > general > related, then similarity),
    else no link. Each value: key, skill_id, skill_name, relation, source ('user', 'same', 'model' or None),
    stale_override (the override's skill name when it is stale), and options: every link a match credit may come
    from ({skill_id, relation}), found in the same order: the override's one link (none for "no link"), the
    same-key skill's, else every usable relation of the latest judgment, strongest first; and judged, whether the
    key has a succeeded judgment."""
    from .enrich.links import latest_judgments

    if keys is None:
        keys = [k["key"] for k in posting_skill_keys(conn)]
    profile_list = profile_skills(conn)
    profile = {s.id: s for s in profile_list}
    by_key = same_identity(conn, profile_list)
    overrides = {
        row.posting_key: row
        for row in conn.execute(
            select(skill_link_overrides, skills.c.name.label("skill_name"))
            .outerjoin(skills, skills.c.id == skill_link_overrides.c.skill_id)
            .where(skill_link_overrides.c.posting_key.in_(keys))
        )
    }
    judged = latest_judgments(conn, keys)
    relations: dict[int, list] = defaultdict(list)
    if judged:
        for row in conn.execute(
            select(link_relations).where(link_relations.c.judgment_id.in_([j.id for j in judged.values()]))
        ):
            relations[row.judgment_id].append(row)

    out = {}
    for key in keys:
        link = {
            "key": key, "skill_id": None, "skill_name": None, "relation": None, "source": None, "stale_override": None,
            "options": [], "judged": key in judged,
        }
        override = overrides.get(key)
        if override is not None:
            if override.skill_id is None:
                out[key] = link | {"source": "user"}
                continue
            if override.skill_id in profile:
                out[key] = link | {
                    "skill_id": override.skill_id, "skill_name": profile[override.skill_id].name,
                    "relation": override.relation, "source": "user",
                    "options": [{"skill_id": override.skill_id, "relation": override.relation}],
                }
                continue
            link["stale_override"] = override.skill_name
        if key in by_key:
            out[key] = link | {
                "skill_id": by_key[key].id, "skill_name": by_key[key].name, "relation": "same", "source": "same",
                "options": [{"skill_id": by_key[key].id, "relation": "same"}],
            }
            continue
        judgment = judged.get(key)
        if judgment is not None:
            usable = sorted(
                (r for r in relations[judgment.id] if r.relation in LINK_RELATIONS and r.skill_id in profile),
                key=lambda r: (LINK_RELATIONS.index(r.relation), -r.similarity),
            )
            if usable:
                best = usable[0]
                link |= {
                    "skill_id": best.skill_id, "skill_name": profile[best.skill_id].name, "relation": best.relation,
                    "source": "model", "options": [{"skill_id": r.skill_id, "relation": r.relation} for r in usable],
                }
        out[key] = link
    return out


def latest_embed_model(conn: Connection) -> str | None:
    """The embedding model of the newest succeeded link judgment, whose vectors are known to be stored; None with
    no judgment."""
    return conn.execute(
        select(link_judgments.c.embed_model)
        .where(link_judgments.c.status == "succeeded")
        .order_by(link_judgments.c.id.desc())
        .limit(1)
    ).scalar()


def effective_link(conn: Connection, posting_key: str) -> dict:
    return effective_links(conn, [posting_key])[posting_key]


def links_overview(conn: Connection) -> list[dict]:
    """Every posting skill, most asked first, with its link: the links page."""
    keys = posting_skill_keys(conn)
    links = effective_links(conn, [k["key"] for k in keys])
    return [{**k, "link": links[k["key"]]} for k in keys]


def linked_posting_skills(conn: Connection) -> dict[int, list[dict]]:
    """profile skill id -> the posting skills linked to it ({key, name, postings, relation, source})."""
    out: dict[int, list[dict]] = defaultdict(list)
    for row in links_overview(conn):
        link = row["link"]
        if link["skill_id"] is not None:
            out[link["skill_id"]].append(
                {"key": row["key"], "name": row["name"], "postings": row["postings"], "relation": link["relation"],
                 "source": link["source"]}
            )
    return out


# --- Tailored CVs ---


def posting_heading(conn: Connection, job_id: int) -> dict | None:
    """A posting's job_id, url, and the title and company of its latest snapshot; None when there is none."""
    newest = _latest_snapshots()
    row = conn.execute(
        select(postings.c.job_id, postings.c.url, posting_snapshots.c.title, posting_snapshots.c.company)
        .join(newest, newest.c.job_id == postings.c.job_id)
        .join(posting_snapshots, posting_snapshots.c.id == newest.c.snapshot_id)
        .where(postings.c.job_id == job_id)
    ).first()
    return None if row is None else dict(row._mapping)


def tailored_cvs_for_posting(conn: Connection, job_id: int) -> list:
    """A posting's saved CVs, newest first: id, created_at, match_score, method."""
    t = tailored_cvs
    return conn.execute(
        select(t.c.id, t.c.created_at, t.c.match_score, t.c.method)
        .where(t.c.job_id == job_id)
        .order_by(t.c.created_at.desc(), t.c.id.desc())
    ).all()


def _payload_record_ids(payload: dict) -> list[int]:
    own = payload.get("record_ids") or ([payload["id"]] if "id" in payload else [])
    return own + [i for child in payload.get("children", ()) for i in _payload_record_ids(child)]


def _item_label(source_kind: str, payload: dict) -> str:
    if source_kind in ("detail", "highlight"):
        return payload["text"]
    return " — ".join(p for p in (payload["title"], payload["organisation"]) if p) or f"(untitled {payload['kind']})"


def tailored_cv(conn: Connection, cv_id: int) -> dict | None:
    """A saved CV: its row, the posting (job_id, url, title and company of its latest snapshot), its items in
    print order (section by cvdoc's SECTION_ORDER, header first, then position), each with its payload, a label,
    whether it is first or last in its section, `deleted` (a profile row it was copied from no longer exists) and
    `private_now` (a record on it is now private, itself or through its context), and `content` for cvdoc's layout
    (produced on the day it was saved, local time). None when there is no such CV."""
    from .cvdoc.layout import SECTION_ORDER
    from .cvdoc.model import content_from_json

    cv = conn.execute(select(tailored_cvs).where(tailored_cvs.c.id == cv_id)).first()
    if cv is None:
        return None
    posting = posting_heading(conn, cv.job_id)
    order = {key: i for i, key in enumerate(("header",) + SECTION_ORDER)}
    rows = sorted(
        conn.execute(select(tailored_cv_items).where(tailored_cv_items.c.cv_id == cv_id)),
        key=lambda r: (order.get(r.section, len(order)), r.position, r.id),
    )
    record_rows = {
        r.id: dict(r._mapping) for r in conn.execute(select(records.c.id, records.c.disclosure, records.c.part_of_id))
    }
    existing = {
        "detail": set(conn.execute(select(profile_details.c.id)).scalars()),
        "highlight": set(conn.execute(select(highlights.c.id)).scalars()),
    }
    items = []
    for row in rows:
        payload = content_from_json(row.payload_json, cv.content_version)
        if row.source_kind in existing:
            ids, deleted = [], row.source_id not in existing[row.source_kind]
        else:
            ids = _payload_record_ids(payload)
            deleted = any(i not in record_rows for i in ids)
        items.append({
            "id": row.id, "section": row.section, "position": row.position, "source_kind": row.source_kind,
            "source_id": row.source_id, "payload": payload, "label": _item_label(row.source_kind, payload),
            "deleted": deleted,
            "private_now": any(i in record_rows and _effective_disclosure(i, record_rows)[0] == "private" for i in ids),
        })
    for i, item in enumerate(items):
        item["first"] = i == 0 or items[i - 1]["section"] != item["section"]
        item["last"] = i == len(items) - 1 or items[i + 1]["section"] != item["section"]
    return {
        "cv": cv,
        "posting": posting,
        "items": items,
        "content": {
            "produced": cv.created_at.astimezone().date().isoformat(),
            "left_out": json.loads(cv.choice_json).get("left_out", []),
            "items": [{k: item[k] for k in ("section", "source_kind", "source_id", "payload")} for item in items],
        },
    }
