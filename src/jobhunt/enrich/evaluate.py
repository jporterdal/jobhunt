"""Measure skill extraction against postings the user has labelled. No Flask.

The labelled set is every posting whose skill labelling is flagged complete. Marks the user selected are the
reference for recall; accepted marks and rejected suggestions are the user's judgments of suggestions, used for
precision only, so accepting a suggestion never spoils a posting for recall. A suggestion nobody judged is
reported as unjudged rather than counted wrong.
Suggestions match marks by skill key first, then by overlapping text, where a mark's quote is placed at every
whole-word occurrence. Every selected mark no suggestion matches is put down to the step that lost it: the
segmenter (its text was in no required or preferred segment), the extractor (it was, but nothing matched), or
neither when its quote is gone from the latest snapshot.
Each posting is scored on its own and the counts are summed into sets: dev, holdout (each posting's set is
stored when its labelling is first flagged complete), and both together.
A window (postings posted, or last flagged complete, within an age of now) adds each set's figures for the
postings inside it beside the figures for all postings; it changes nothing that is run, scored or stored.
"""

from __future__ import annotations

import calendar
import json
import re
from dataclasses import dataclass, field, fields
from datetime import UTC, date, datetime, timedelta
from functools import reduce

from sqlalchemy import func, select
from sqlalchemy.engine import Connection, Engine

from ..db import (
    enrichment_skills,
    posting_enrichments,
    posting_skill_marks,
    posting_triage,
    postings,
    skills,
)
from ..queries import rejected_keys
from ..store import latest_snapshot
from ..userdata import get_setting
from . import derived, validate
from .pipeline import CURRENT_SKILLS, IMPORTANCES, Steps, pipeline_id, run_pipeline, skill_extractors, steps_for


class NoLabelledPostings(Exception):
    pass


class NoModel(Exception):
    pass


class UnknownSkills(ValueError):
    """A skill extraction method this code doesn't have; the message names the available ones."""

    def __init__(self, name: str):
        super().__init__(f"unknown skill extraction method {name!r}; available: {', '.join(skill_extractors())}")


def check_skills(name: str) -> str:
    if name not in skill_extractors():
        raise UnknownSkills(name)
    return name


@dataclass(frozen=True)
class Mark:
    key: str
    name: str
    quote: str
    importance: str | None
    origin: str
    created_at: datetime | None = None


DEV, HOLDOUT = "dev", "holdout"
HOLDOUT_DRAWN = "holdout (drawn)"  # the holdout postings whose set was drawn, shown when some weren't


@dataclass
class Labelled:
    job_id: int
    title: str
    snapshot_id: int
    text: str
    marks: list[Mark]
    set: str = DEV
    set_origin: str = "drawn"  # how the set was decided: drawn, chosen, moved or before-random
    first_run_at: datetime | None = None  # when the posting's first successful run (any model or pipeline) finished
    posted_on: date | None = None  # the latest snapshot's posted date, else the day the posting was first seen
    labelled_at: datetime | None = None  # when its labelling was last flagged complete

    def selected_after_run(self) -> int:
        """Selected marks created after the posting already had a successful run: suggestions may have prompted
        them. A warning only; they are scored as selected."""
        if self.first_run_at is None:
            return 0
        return sum(
            m.origin == "selection" and m.created_at is not None and m.created_at > self.first_run_at
            for m in self.marks
        )


def labelled_set(conn: Connection) -> list[Labelled]:
    out = []
    for job_id, eval_set, set_origin, labelled_at, first_seen_at in conn.execute(
        select(
            posting_triage.c.job_id,
            posting_triage.c.eval_set,
            posting_triage.c.eval_set_origin,
            posting_triage.c.skills_complete_at,
            postings.c.first_seen_at,
        )
        .join(postings, postings.c.job_id == posting_triage.c.job_id)
        .where(posting_triage.c.skills_complete_at.is_not(None))
        .order_by(posting_triage.c.job_id)
    ).all():
        snapshot = latest_snapshot(conn, job_id)
        marks = [
            Mark(row.key, row.name, row.quote, row.importance, row.origin, row.created_at)
            for row in conn.execute(
                select(
                    skills.c.key,
                    skills.c.name,
                    posting_skill_marks.c.quote,
                    posting_skill_marks.c.importance,
                    posting_skill_marks.c.origin,
                    posting_skill_marks.c.created_at,
                )
                .join(skills, skills.c.id == posting_skill_marks.c.skill_id)
                .where(posting_skill_marks.c.job_id == job_id)
                .order_by(posting_skill_marks.c.id)
            )
        ]
        first_run_at = conn.execute(
            select(func.min(posting_enrichments.c.finished_at)).where(
                posting_enrichments.c.job_id == job_id, posting_enrichments.c.status == "succeeded"
            )
        ).scalar()
        out.append(
            Labelled(
                job_id,
                snapshot.title,
                snapshot.id,
                snapshot.description_text,
                marks,
                eval_set,
                set_origin,
                first_run_at,
                snapshot.posted_on_estimate or first_seen_at.astimezone(UTC).date(),
                labelled_at,
            )
        )
    return out


# --- Windows ---

AGE_FORMAT = "an age is a positive whole number followed by d, w, m or y, as in 12m"
_AGE = re.compile(r"([1-9][0-9]*)([dwmy])")
WINDOW_NOTE = "adopt or delete a method on the figures for all postings; windowed figures are for diagnosis"


@dataclass(frozen=True)
class Age:
    """A span counted back from now: days, weeks, calendar months or calendar years."""

    count: int
    unit: str  # d, w, m or y

    def __str__(self) -> str:
        return f"{self.count}{self.unit}"

    def before(self, now: datetime) -> datetime:
        """The moment this age before `now`; a month back from a day the month lacks lands on its last day."""
        if self.unit in ("d", "w"):
            return now - timedelta(days=self.count * (7 if self.unit == "w" else 1))
        year, month = divmod(now.year * 12 + now.month - 1 - self.count * (12 if self.unit == "y" else 1), 12)
        month += 1
        return now.replace(year=year, month=month, day=min(now.day, calendar.monthrange(year, month)[1]))


def parse_age(text: str) -> Age:
    """`12m` -> Age(12, 'm'); raises ValueError for anything else."""
    found = _AGE.fullmatch(text)
    if found is None:
        raise ValueError(AGE_FORMAT)
    return Age(int(found[1]), found[2])


@dataclass(frozen=True)
class Window:
    """The labelled postings posted on or after `posted_since` and last flagged complete at or after
    `labelled_since`; a test applies only when its age is given."""

    posted_within: Age | None
    labelled_within: Age | None
    now: datetime

    @property
    def posted_since(self) -> date | None:
        return None if self.posted_within is None else self.posted_within.before(self.now).astimezone(UTC).date()

    @property
    def labelled_since(self) -> datetime | None:
        return None if self.labelled_within is None else self.labelled_within.before(self.now)

    def contains(self, posting: Labelled) -> bool:
        posted, labelled = self.posted_since, self.labelled_since
        return (posted is None or posting.posted_on >= posted) and (
            labelled is None or posting.labelled_at >= labelled
        )

    def describe(self) -> str:
        parts = []
        if self.posted_within is not None:
            parts.append(f"posted within {self.posted_within} (since {self.posted_since.isoformat()})")
        if self.labelled_within is not None:
            parts.append(
                f"labelled within {self.labelled_within} "
                f"(since {self.labelled_since.astimezone(UTC):%Y-%m-%d %H:%M} UTC)"
            )
        return ", ".join(parts)


def reusable_run(conn: Connection, snapshot_id: int, model: str, pipeline: str) -> int | None:
    """The newest successful run for this snapshot, model and pipeline."""
    return conn.execute(
        select(posting_enrichments.c.id)
        .where(
            posting_enrichments.c.snapshot_id == snapshot_id,
            posting_enrichments.c.model == model,
            posting_enrichments.c.pipeline == pipeline,
            posting_enrichments.c.status == "succeeded",
        )
        .order_by(posting_enrichments.c.id.desc())
        .limit(1)
    ).scalar()


# --- Matching and attribution ---


@dataclass(frozen=True)
class Suggestion:
    key: str
    importance: str
    span: tuple[int, int] | None
    rejected: bool = False
    reason: str | None = None  # of the rejection: 'not-a-skill', 'not-for-me', or None (none given)
    name: str = ""
    quote: str = ""


def _overlaps(a: tuple[int, int] | None, b: tuple[int, int] | None) -> bool:
    return a is not None and b is not None and a[0] < b[1] and b[0] < a[1]


def placements(text: str, quote: str) -> list[tuple[int, int]]:
    """Raw (start, end) of every whole-word occurrence of the quote, or of every occurrence when none is whole-word
    (a partial-word selection). The rule is `validate.occurrences`, shared with the validator."""
    needle, _ = validate.normalise(quote)
    if not needle:
        return []
    haystack, positions = validate.normalise(text)
    return [(positions[at], positions[at + len(needle) - 1] + 1) for at in validate.occurrences(haystack, needle)]


def match(suggestions: list[Suggestion], marks: list[Mark], mark_places: list) -> list[tuple[int, int]]:
    """(suggestion index, mark index) pairs; each side at most once. Selected marks are paired first, so a
    suggestion that could pair with a selected or an accepted mark counts toward recall; within each, equal keys
    first, then text overlapping any of the mark's placements. Rejected suggestions never match."""
    pairs: list[tuple[int, int]] = []
    free_s = [i for i, s in enumerate(suggestions) if not s.rejected]
    for origin in ("selection", "suggestion"):
        free_m = [i for i, m in enumerate(marks) if m.origin == origin]
        for by_key in (True, False):
            for si in list(free_s):
                for mi in free_m:
                    hit = (
                        suggestions[si].key == marks[mi].key
                        if by_key
                        else any(_overlaps(suggestions[si].span, place) for place in mark_places[mi])
                    )
                    if hit:
                        pairs.append((si, mi))
                        free_s.remove(si)
                        free_m.remove(mi)
                        break
    return pairs


def _buckets() -> dict:
    return {"all": 0, "required": 0, "preferred": 0}


REASON_BUCKETS = {"not-a-skill": "not_a_skill", "not-for-me": "not_for_me", None: "no_reason"}


def _reasons() -> dict:
    return dict.fromkeys(REASON_BUCKETS.values(), 0)


@dataclass
class Counts:
    """Numerators and denominators; ratios are computed when reported. Mark counts cover selected marks only."""

    postings: int = 0
    failures: int = 0
    run_seconds: list[float] = field(default_factory=list)
    right: dict = field(default_factory=_buckets)  # suggestions matching a mark
    wrong: dict = field(default_factory=_buckets)  # rejected suggestions
    unjudged: dict = field(default_factory=_buckets)
    marks: dict = field(default_factory=_buckets)
    matched_marks: dict = field(default_factory=_buckets)
    importance_pairs: int = 0
    importance_agree: int = 0
    located: int = 0
    reached: int = 0
    misses: dict = field(default_factory=lambda: {"segmentation": 0, "extraction": 0, "not_located": 0})
    wrong_by_reason: dict = field(default_factory=_reasons)
    selected_after_run: int = 0

    def __add__(self, other: Counts) -> Counts:
        out = Counts()
        for f in fields(Counts):
            mine, theirs = getattr(self, f.name), getattr(other, f.name)
            setattr(out, f.name, {k: mine[k] + theirs[k] for k in mine} if isinstance(mine, dict) else mine + theirs)
        return out


def total(counts) -> Counts:
    return reduce(lambda a, b: a + b, counts, Counts())


@dataclass
class Detail:
    """One posting's scored run, by name: what the JSON report lists, and which selected marks were matched."""

    matched: set[int] = field(default_factory=set)  # indices of the posting's selected marks a suggestion matched
    missed: list[dict] = field(default_factory=list)
    wrong: list[dict] = field(default_factory=list)
    unjudged: list[dict] = field(default_factory=list)


def score(counts: Counts, posting: Labelled, suggestions: list[Suggestion], segments: list) -> Detail:
    """Add one posting's successful run to the counts, and return what was matched, missed and wrong."""
    places = [placements(posting.text, m.quote) for m in posting.marks]
    pairs = match(suggestions, posting.marks, places)
    matched_s = {si for si, _ in pairs}
    matched_m = {mi for _, mi in pairs}
    selected = [i for i, m in enumerate(posting.marks) if m.origin == "selection"]
    detail = Detail(matched={i for i in selected if i in matched_m})
    counts.postings += 1

    for i, s in enumerate(suggestions):
        verdict = counts.right if i in matched_s else counts.wrong if s.rejected else counts.unjudged
        for bucket in ("all", s.importance):
            verdict[bucket] += 1
        if i in matched_s:
            continue
        if s.rejected:
            counts.wrong_by_reason[REASON_BUCKETS[s.reason]] += 1
            detail.wrong.append({"name": s.name, "quote": s.quote, "reason": s.reason})
        else:
            detail.unjudged.append({"name": s.name, "importance": s.importance, "quote": s.quote})
    for i in selected:
        m = posting.marks[i]
        for bucket in ("all",) + ((m.importance,) if m.importance else ()):
            counts.marks[bucket] += 1
            counts.matched_marks[bucket] += i in matched_m
    for si, mi in pairs:
        if posting.marks[mi].origin == "selection" and posting.marks[mi].importance:
            counts.importance_pairs += 1
            counts.importance_agree += suggestions[si].importance == posting.marks[mi].importance

    labelled = [(start, end) for start, end, label in segments if label in IMPORTANCES]
    for i in selected:
        reached = any(_overlaps(place, seg) for place in places[i] for seg in labelled)
        if places[i]:
            counts.located += 1
            counts.reached += reached
        if i in matched_m:
            continue
        step = "not_located" if not places[i] else "extraction" if reached else "segmentation"
        counts.misses[step] += 1
        m = posting.marks[i]
        detail.missed.append({"name": m.name, "importance": m.importance, "quote": m.quote, "step": step})
    return detail


def _run_items(conn: Connection, run_id: int, rejected: dict[str, str | None]) -> tuple[list[Suggestion], list]:
    """Verified suggestions (with their rejection reasons) and the stored segments of a run."""
    suggestions = [
        Suggestion(
            row.key,
            row.importance,
            (row.start_offset, row.end_offset),
            row.key in rejected,
            rejected.get(row.key),
            row.name,
            row.quote,
        )
        for row in conn.execute(
            select(enrichment_skills)
            .where(enrichment_skills.c.enrichment_id == run_id, enrichment_skills.c.verified.is_(True))
            .order_by(enrichment_skills.c.position)
        )
    ]
    output = conn.execute(
        select(posting_enrichments.c.output_json).where(posting_enrichments.c.id == run_id)
    ).scalar_one()
    return suggestions, json.loads(output).get("segments", [])


# --- Running an evaluation ---


@dataclass
class PostingResult:
    posting: Labelled
    status: str  # of the run: 'succeeded' or 'failed'
    counts: Counts
    detail: Detail

    def to_dict(self) -> dict:
        return {
            "job_id": self.posting.job_id,
            "title": self.posting.title,
            "set": self.posting.set,
            "set_origin": self.posting.set_origin,
            "status": self.status,
            "selected_after_run": self.counts.selected_after_run,
            "missed": self.detail.missed,
            "wrong": self.detail.wrong,
            "unjudged": self.detail.unjudged,
        }


@dataclass
class Report:
    model: str
    pipeline: str
    new_runs: int
    reused_runs: int
    postings: list[PostingResult]
    skills: str = ""
    window: Window | None = None

    @property
    def counts(self) -> Counts:
        return total(p.counts for p in self.postings)

    def _show_drawn(self) -> bool:
        holdout = [p for p in self.postings if p.posting.set == HOLDOUT]
        return any(p.posting.set_origin != "drawn" for p in holdout)

    def sets(self) -> list[tuple[str, int, Counts]]:
        """(name, labelled postings, counts) for dev, holdout, the drawn holdout postings alone when some holdout
        postings weren't drawn, and together."""
        return _set_rows(_groups(self.postings, self._show_drawn()))

    def in_window(self, result: PostingResult) -> bool:
        return self.window is None or self.window.contains(result.posting)

    def windowed_sets(self) -> list[tuple[str, int, Counts]]:
        """The rows of sets(), in the same order, over the postings inside the window."""
        return _set_rows(_groups([p for p in self.postings if self.in_window(p)], self._show_drawn()))

    def window_lines(self) -> list[str]:
        """The window and the note, for a text header; none without a window."""
        if self.window is None:
            return []
        inside = sum(map(self.in_window, self.postings))
        return [
            f"window:   {self.window.describe()}",
            f"          {inside} of {len(self.postings)} labelled postings inside, "
            f"{len(self.postings) - inside} left out",
            f"note:     {WINDOW_NOTE}",
        ]

    def to_dict(self) -> dict:
        out = {
            "model": self.model,
            "pipeline": self.pipeline,
            "skills": self.skills,
            "new_runs": self.new_runs,
            "reused_runs": self.reused_runs,
            **_summary(self.counts),
            "sets": _sets_dict(self.sets()),
        }
        if self.window is None:
            out["per_posting"] = [p.to_dict() for p in self.postings]
            return out
        w, inside = self.window, sum(map(self.in_window, self.postings))
        out["window"] = {
            "posted_within": None if w.posted_within is None else str(w.posted_within),
            "posted_since": None if w.posted_since is None else w.posted_since.isoformat(),
            "labelled_within": None if w.labelled_within is None else str(w.labelled_within),
            "labelled_since": None if w.labelled_since is None else w.labelled_since.astimezone(UTC).isoformat(),
            "inside": inside,
            "left_out": len(self.postings) - inside,
            "note": WINDOW_NOTE,
        }
        windowed = self.windowed_sets()
        out["windowed"] = {**_summary(windowed[-1][2]), "sets": _sets_dict(windowed)}
        out["per_posting"] = [{**p.to_dict(), "in_window": self.in_window(p)} for p in self.postings]
        return out

    def format_text(self) -> str:
        lines = [
            f"model:    {self.model}",
            f"pipeline: {self.pipeline}",
            f"runs:     {self.new_runs} new, {self.reused_runs} reused",
        ]
        if self.window is None:
            for name, size, counts in self.sets():
                lines += ["", f"{name}: {size} labelled postings, {counts.postings} scored"] + _block(_summary(counts))
            return "\n".join(lines)
        lines += self.window_lines()
        for (name, size, counts), (_, inside, windowed) in zip(self.sets(), self.windowed_sets(), strict=True):
            lines += [""] + _table(
                f"{name}: {size} labelled postings, {inside} in window",
                ["all", "in window"],
                [_summary(counts), _summary(windowed)],
            )
        return "\n".join(lines)


def _groups(results: list[PostingResult], show_drawn: bool) -> list[tuple[str, list[PostingResult]]]:
    """Dev, holdout, the drawn holdout postings alone when `show_drawn`, and together."""
    dev = [p for p in results if p.posting.set == DEV]
    holdout = [p for p in results if p.posting.set == HOLDOUT]
    drawn = [p for p in holdout if p.posting.set_origin == "drawn"]
    return [(DEV, dev), (HOLDOUT, holdout)] + ([(HOLDOUT_DRAWN, drawn)] if show_drawn else []) + [("together", results)]


def _set_rows(groups: list[tuple[str, list[PostingResult]]]) -> list[tuple[str, int, Counts]]:
    return [(name, len(members), total(p.counts for p in members)) for name, members in groups]


def _sets_dict(rows: list[tuple[str, int, Counts]]) -> dict:
    """Every row but together, by JSON name."""
    return {
        {HOLDOUT_DRAWN: "holdout_drawn"}.get(name, name): {"labelled": size, **_summary(counts)}
        for name, size, counts in rows[:-1]
    }


def _ratio(num: int, den: int) -> dict:
    return {"count": num, "of": den, "ratio": num / den if den else None}


def _fmt(r: dict) -> str:
    share = f"{r['ratio']:.0%}" if r["ratio"] is not None else "n/a"
    return f"{share:>4} ({r['count']}/{r['of']})"


def _summary(c: Counts) -> dict:
    return {
        "postings": c.postings,
        "failures": c.failures,
        "precision": {b: _ratio(c.right[b], c.right[b] + c.wrong[b]) for b in c.right},
        "unjudged": dict(c.unjudged),
        "wrong_by_reason": dict(c.wrong_by_reason),
        "recall": {b: _ratio(c.matched_marks[b], c.marks[b]) for b in c.marks},
        "importance_agreement": _ratio(c.importance_agree, c.importance_pairs),
        "segment_recall": _ratio(c.reached, c.located),
        "misses": dict(c.misses),
        "selected_after_run": c.selected_after_run,
        "mean_run_seconds": sum(c.run_seconds) / len(c.run_seconds) if c.run_seconds else None,
    }


def _mean(s: dict) -> str:
    return f"{s['mean_run_seconds']:.1f} s" if s["mean_run_seconds"] is not None else "n/a"


def _block(s: dict) -> list[str]:
    """One set's figures as text lines."""
    lines = []
    for bucket in ("all", "required", "preferred"):
        precision = f"{_fmt(s['precision'][bucket])}, {s['unjudged'][bucket]} unjudged"
        lines.append(f"{bucket:<9} precision {precision:<26} recall {_fmt(s['recall'][bucket])}")
    lines.append(f"importance agreement {_fmt(s['importance_agreement'])}")
    lines.append(f"segment recall       {_fmt(s['segment_recall'])}")
    misses, wrong = s["misses"], s["wrong_by_reason"]
    lines.append(
        f"missed skills: {misses['segmentation']} segmentation, {misses['extraction']} extraction, "
        f"{misses['not_located']} not located"
    )
    lines.append(
        f"wrong by reason: {wrong['not_a_skill']} not a skill, {wrong['not_for_me']} not for me, "
        f"{wrong['no_reason']} no reason"
    )
    lines.append(f"failed runs: {s['failures']}   mean run time: {_mean(s)}")
    if s["selected_after_run"]:
        n = s["selected_after_run"]
        lines.append(
            f"warning: {n} selected mark{' was' if n == 1 else 's were'} made after the posting had a successful run; "
            "suggestions may have prompted them (they still count toward recall)"
        )
    else:
        lines.append("selected after a run: 0 marks")
    return lines


@dataclass
class Plan:
    """What an evaluation of one skill extraction method will run and reuse, worked out before any model call."""

    model: str
    skills: str
    steps: Steps
    pipeline: str
    num_ctx: int
    labelled: list[Labelled]
    reuse: dict[str, int | None]

    @property
    def todo(self) -> list[Labelled]:
        return [p for p in self.labelled if self.reuse[p.job_id] is None]


def plan(
    engine: Engine,
    model: str | None = None,
    segmenter: str | None = None,
    skills: str | None = None,
    fresh: bool = False,
) -> Plan:
    """Raises UnknownSkills, NoLabelledPostings or NoModel; makes no model request."""
    if skills is not None:
        check_skills(skills)
    with engine.connect() as conn:
        labelled = labelled_set(conn)
        if not labelled:
            raise NoLabelledPostings()
        model = model or get_setting(conn, "llm.model")
        if not model:
            raise NoModel()
        skills = skills or CURRENT_SKILLS
        steps = steps_for(segmenter or get_setting(conn, "llm.segmenter"), skills)
        pipeline = pipeline_id(steps)
        reuse = {
            p.job_id: None if fresh else reusable_run(conn, p.snapshot_id, model, pipeline) for p in labelled
        }
        return Plan(model, skills, steps, pipeline, get_setting(conn, "llm.num_ctx"), labelled, reuse)


def execute(engine: Engine, client, plan: Plan, window: Window | None = None) -> Report:
    """Run the plan's missing runs, then score every labelled posting; a window only adds figures to the report.

    Raises Unreachable when runs are needed and Ollama can't be reached. New runs are saved in one transaction
    after all of them finished, so an interrupted evaluation writes nothing.
    """
    todo = plan.todo
    results = {}
    if todo:
        client.version()  # Unreachable before any model call
        llm = client.for_model(plan.model, plan.num_ctx)
        for posting in todo:
            results[posting.job_id] = run_pipeline(posting.text, llm, plan.steps)

    out = []
    with engine.begin() as conn:
        for posting in plan.labelled:
            run_id = plan.reuse[posting.job_id]
            if run_id is None:
                run_id = derived.save_run(
                    conn, posting.job_id, posting.snapshot_id, plan.model, plan.pipeline, results[posting.job_id],
                    "eval",
                )
            run = conn.execute(select(posting_enrichments).where(posting_enrichments.c.id == run_id)).one()
            counts = Counts(selected_after_run=posting.selected_after_run())
            counts.run_seconds.append((run.finished_at - run.started_at).total_seconds())
            detail = Detail()
            if run.status == "succeeded":
                suggestions, segments = _run_items(conn, run_id, rejected_keys(conn, posting.job_id))
                detail = score(counts, posting, suggestions, segments)
            else:
                counts.failures += 1
            out.append(PostingResult(posting, run.status, counts, detail))
    return Report(plan.model, plan.pipeline, len(todo), len(plan.labelled) - len(todo), out, plan.skills, window)


def evaluate(
    engine: Engine,
    client,
    model: str | None = None,
    segmenter: str | None = None,
    fresh: bool = False,
    skills: str | None = None,
) -> Report:
    """Run (or reuse) extraction on every labelled posting with one skill extraction method and score it.

    Raises UnknownSkills, NoLabelledPostings, NoModel, or Unreachable when runs are needed and Ollama can't be
    reached.
    """
    return execute(engine, client, plan(engine, model, segmenter, skills, fresh))


def report_json(report: Report) -> str:
    return json.dumps(report.to_dict(), indent=2)


# --- Comparing skill extraction methods ---


def differences(reports: list[Report]) -> list[dict]:
    """Selected marks that some of the methods match and others don't, per posting, naming the methods that do;
    with a window, each says whether its posting is inside it."""
    out = []
    by_job = [{p.posting.job_id: p for p in r.postings} for r in reports]
    windowed = reports[0].window is not None
    for result in reports[0].postings:
        posting = result.posting
        for i, mark in enumerate(posting.marks):
            if mark.origin != "selection":
                continue
            matched_by = [
                r.skills
                for r, results in zip(reports, by_job, strict=True)
                if i in results[posting.job_id].detail.matched
            ]
            if 0 < len(matched_by) < len(reports):
                out.append(
                    {
                        "job_id": posting.job_id,
                        "title": posting.title,
                        "set": posting.set,
                        "name": mark.name,
                        "importance": mark.importance,
                        "quote": mark.quote,
                        "matched_by": matched_by,
                        **({"in_window": reports[0].in_window(result)} if windowed else {}),
                    }
                )
    return out


def comparison_json(reports: list[Report]) -> str:
    return json.dumps({"methods": [r.to_dict() for r in reports], "differences": differences(reports)}, indent=2)


_ROWS = [
    ("postings scored", lambda s: str(s["postings"])),
    *[(f"precision {b}", lambda s, b=b: _fmt(s["precision"][b])) for b in ("all", "required", "preferred")],
    *[(f"unjudged {b}", lambda s, b=b: str(s["unjudged"][b])) for b in ("all", "required", "preferred")],
    *[(f"recall {b}", lambda s, b=b: _fmt(s["recall"][b])) for b in ("all", "required", "preferred")],
    ("importance agreement", lambda s: _fmt(s["importance_agreement"])),
    ("segment recall", lambda s: _fmt(s["segment_recall"])),
    *[
        (f"missed: {k.replace('_', ' ')}", lambda s, k=k: str(s["misses"][k]))
        for k in ("segmentation", "extraction", "not_located")
    ],
    *[(f"wrong: {k.replace('_', ' ')}", lambda s, k=k: str(s["wrong_by_reason"][k])) for k in REASON_BUCKETS.values()],
    ("selected after a run", lambda s: str(s["selected_after_run"])),
    ("failed runs", lambda s: str(s["failures"])),
    ("mean run time", _mean),
]


def _table(heading: str, columns: list[str], summaries: list[dict]) -> list[str]:
    """One set's figures, a column per summary."""
    width = max(16, *(len(c) for c in columns))
    lines = [f"{heading:<22}" + "".join(f"{c:>{width}}" for c in columns)]
    for label, cell in _ROWS:
        lines.append(f"{label:<22}" + "".join(f"{cell(s):>{width}}" for s in summaries))
    return lines


def comparison_text(reports: list[Report]) -> str:
    """Each method's figures side by side, per set (and, with a window, inside it), then the mark differences."""
    width = max(16, *(len(r.skills) for r in reports))
    methods = [r.skills for r in reports]
    lines = [f"model:    {reports[0].model}"]
    lines += [f"{r.skills:<{width}} {r.pipeline}  ({r.new_runs} new, {r.reused_runs} reused runs)" for r in reports]
    lines += reports[0].window_lines()
    per_method = [r.sets() for r in reports]
    windowed = [r.windowed_sets() for r in reports] if reports[0].window is not None else None
    for k, (name, size, _) in enumerate(per_method[0]):
        lines += [""] + _table(f"{name}: {size} labelled postings", methods, [_summary(s[k][2]) for s in per_method])
        if windowed is not None:
            inside = windowed[0][k][1]
            lines += [""] + _table(
                f"{name}, in window: {inside} labelled postings", methods, [_summary(s[k][2]) for s in windowed]
            )
    diffs = differences(reports)
    lines += ["", f"selected marks matched by some methods only: {len(diffs) or 'none'}"]
    current = None
    for d in diffs:
        if d["job_id"] != current:
            current = d["job_id"]
            outside = " (outside window)" if d.get("in_window") is False else ""
            lines.append(f"  {d['job_id']}  {d['title']} ({d['set']}){outside}")
        importance = f" ({d['importance']})" if d["importance"] else ""
        lines.append(f"    {d['name']}{importance} “{d['quote']}”: {', '.join(d['matched_by'])}")
    return "\n".join(lines)
