"""Tailoring a CV for a posting (`cv-rank@1`, design D2, D3, D6): which highlights, records and details to print,
and the posting skills the user has that nothing chosen shows. Computed from stored data each time; no writes,
no model requests, no Flask. Values come from recommend.py's weights, so a posting skill counts for as much here
as its credit does on Insights.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.engine import Connection

from . import queries, recommend
from .cvdoc.layout import HEADER_KINDS, PRINTED_SOURCE_KINDS, SECTION_ORDER
from .queries import IMPORTANCE_RANK, record_sort_key
from .userdata import RECORD_KINDS, level_rank, name_key, utcnow

# The ranking's constants, all in one place (design D2). Guesses until there is data to tune them against; a
# change that alters what is chosen for the same data bumps METHOD.
METHOD = "cv-rank@1"
HIGHLIGHT_BUDGET = 9  # about what fits beside the other sections on two pages
IRRELEVANT_COST = 0.1  # per covered claim that no posting skill has a link option to
KIND_RULES = {  # "all", or how many records of the kind to take by default, most relevant first
    "role": "all", "course": "all", "degree": "all", "award": "all",
    "publication": 3, "project": 0, "event": 0, "task": 0, "other": 0,
}
DEFAULT_DETAILS = ("name", "headline", "contact", "goal")  # summaries only when ticked
MAX_BUDGET = 30  # larger budgets and counts in a URL fall back to the default
MAX_COUNT = 50
MIN_ORGANISATION_CHARS = 4  # a private record's organisation is looked for in highlights from this length

RANKED_KINDS = tuple(kind for kind, rule in KIND_RULES.items() if rule != "all")
TICKABLE = ("h", "r", "d")  # highlights, records, details
EPSILON = 1e-9


def _number(raw: str | None, default: int, highest: int) -> int:
    raw = (raw or "").strip()
    if not raw.isdigit() or int(raw) > highest:
        return default
    return int(raw)


def _ids(args, name: str) -> frozenset[int]:
    return frozenset(int(v) for v in args.getlist(name) if v.strip().isdigit())


@dataclass(frozen=True)
class Choice:
    """A proposal's parameters: the highlight budget, the count per ranked kind, and, once `tuned`, the ids the
    user ticked and unticked (`ticked["h"]`, `unticked["r"]`, ...)."""

    budget: int = HIGHLIGHT_BUDGET
    counts: Mapping[str, int] = field(default_factory=lambda: {k: KIND_RULES[k] for k in RANKED_KINDS})
    tuned: bool = False
    ticked: Mapping[str, frozenset[int]] = field(default_factory=lambda: {k: frozenset() for k in TICKABLE})
    unticked: Mapping[str, frozenset[int]] = field(default_factory=lambda: {k: frozenset() for k in TICKABLE})

    @classmethod
    def from_args(cls, args) -> Choice:
        """The only parser of a proposal's URL or form (a MultiDict): `budget`, `count_<kind>`, `tuned=1`, and
        with it `h`, `r`, `d` (ticked ids) and `x_h`, `x_r`, `x_d` (unticked ids). The form also sends `a_h`,
        `a_r`, `a_d`, the ids the ranking chose by itself: one of those left unchecked is unticked, and one still
        checked is left to the ranking. Without `tuned`, ticks are ignored; bad numbers fall back to defaults."""
        budget = _number(args.get("budget"), HIGHLIGHT_BUDGET, MAX_BUDGET)
        counts = {kind: _number(args.get(f"count_{kind}"), KIND_RULES[kind], MAX_COUNT) for kind in RANKED_KINDS}
        tuned = args.get("tuned") == "1"
        ticked, unticked = {}, {}
        for kind in TICKABLE:
            if not tuned:
                ticked[kind] = unticked[kind] = frozenset()
                continue
            checked, auto, was_unticked = _ids(args, kind), _ids(args, f"a_{kind}"), _ids(args, f"x_{kind}")
            ticked[kind] = checked - auto
            unticked[kind] = (auto | was_unticked) - checked
        return cls(budget, counts, tuned, ticked, unticked)

    def to_args(self) -> list[tuple[str, str]]:
        """The canonical URL parameters for this choice."""
        out = [("budget", str(self.budget))] + [(f"count_{k}", str(self.counts[k])) for k in RANKED_KINDS]
        if self.tuned:
            out.append(("tuned", "1"))
            for kind in TICKABLE:
                out += [(kind, str(i)) for i in sorted(self.ticked[kind])]
                out += [(f"x_{kind}", str(i)) for i in sorted(self.unticked[kind])]
        return out

    def to_json(self) -> dict:
        return {
            "budget": self.budget, "counts": dict(self.counts), "tuned": self.tuned,
            **{kind: sorted(self.ticked[kind]) for kind in TICKABLE},
            **{f"x_{kind}": sorted(self.unticked[kind]) for kind in TICKABLE},
        }


@dataclass(frozen=True)
class Proposal:
    """A proposed CV. `content` is cvdoc's content (see cvdoc.model); the rest is for the proposal page:
    highlights (each with gain, covered claims, flag and state), records by kind (relevance and state), details,
    gaps, and the posting's match score (None without posting skills)."""

    job_id: int
    choice: Choice
    score: float | None
    has_skills: bool
    highlights: list[dict]
    records: list[dict]
    details: list[dict]
    gaps: list[dict]
    content: dict
    method: str = METHOD


# --- Non-disclosure (D6) ---


def _bare_address(url: str) -> str:
    address = url.split("://", 1)[-1].casefold()
    return address.removeprefix("www.").rstrip("/")


def private_needles(records: list[dict]) -> list[tuple[str, str]]:
    """(casefolded text, record label) for every private record's title, organisation (MIN_ORGANISATION_CHARS or
    longer) and source address (no scheme, no `www.`)."""
    out = []
    for r in records:
        texts = [r["title"]] if r["title"] else []
        if r["organisation"] and len(r["organisation"]) >= MIN_ORGANISATION_CHARS:
            texts.append(r["organisation"])
        texts += [_bare_address(s["url"]) for s in r["sources"] if s["url"]]
        out += [(t.casefold(), r["label"]) for t in texts if t.strip()]
    return out


def private_mention(text: str, needles: list[tuple[str, str]]) -> str | None:
    """The label of the first private record the text mentions, ignoring case; None when it mentions none."""
    folded = text.casefold()
    return next((label for needle, label in needles if needle in folded), None)


# --- Values (D2) ---


def skill_values(
    asked: list[dict], options: Mapping[str, list], levels: Mapping[int, str]
) -> dict[str, dict[int, float]]:
    """posting key -> {profile skill id: importance weight × relation weight × level weight} over its options."""
    out: dict[str, dict[int, float]] = {}
    for s in asked:
        weight = recommend.IMPORTANCE_WEIGHT.get(s["importance"], 1)
        values: dict[int, float] = {}
        for o in options.get(s["key"], []):
            value = (
                weight
                * recommend.RELATION_WEIGHT[o["relation"]]
                * recommend.LEVEL_WEIGHT.get(levels.get(o["skill_id"]), 0.0)
            )
            values[o["skill_id"]] = max(values.get(o["skill_id"], 0.0), value)
        out[s["key"]] = values
    return out


def shows(skill_ids: set[int], values: Mapping[str, dict[int, float]]) -> dict[str, float]:
    """posting key -> the best value among its options to these profile skills (a highlight's claims or a record's
    grounds)."""
    return {
        key: max((v for k, v in by_skill.items() if k in skill_ids), default=0.0) for key, by_skill in values.items()
    }


def gain(skill_ids: set[int], values: Mapping[str, dict[int, float]], shown: Mapping[str, float],
         linked: set[int]) -> float:
    """How much a highlight raises what is already shown, less IRRELEVANT_COST per claim no posting skill links to."""
    raised = sum(max(0.0, v - shown.get(key, 0.0)) for key, v in shows(skill_ids, values).items())
    return raised - IRRELEVANT_COST * len(skill_ids - linked)


def choose_highlights(highlights: list[dict], values: Mapping[str, dict[int, float]], linked: set[int], budget: int,
                      skip: set[int]) -> tuple[list[tuple[dict, float]], dict[str, float]]:
    """Greedy weighted cover: up to `budget` highlights not in `skip`, the highest gain first while above 0; ties
    to fewer claims, then the lower id. Returns [(highlight, gain when chosen)] in order, and what they show."""
    shown: dict[str, float] = defaultdict(float)
    chosen: list[tuple[dict, float]] = []
    remaining = [h for h in highlights if h["id"] not in skip]
    while len(chosen) < budget and remaining:
        scored = [(gain(h["skill_ids"], values, shown, linked), h) for h in remaining]
        best_gain, best = max(scored, key=lambda pair: (round(pair[0], 9), -len(pair[1]["skill_ids"]), -pair[1]["id"]))
        if best_gain <= EPSILON:
            break
        chosen.append((best, best_gain))
        remaining.remove(best)
        for key, v in shows(best["skill_ids"], values).items():
            shown[key] = max(shown[key], v)
    return chosen, shown


def relevance(skill_ids: set[int], values: Mapping[str, dict[int, float]]) -> float:
    """A record's relevance: Σ over posting skills of the best value among its grounds."""
    return sum(shows(skill_ids, values).values())


# --- Content (D4, D5) ---


def _record_payload(r: dict, printed: set[int], by_id: Mapping[int, dict], children: Mapping[int, list[dict]]) -> dict:
    parent = by_id.get(r["part_of_id"])
    return {
        "id": r["id"], "kind": r["kind"], "title": r["title"], "organisation": r["organisation"],
        "location": r["location"], "start_date": r["start_date"], "end_date": r["end_date"],
        "ongoing": bool(r["ongoing"]),
        "lines": [line["text"] for line in r["lines"]],
        "sources": [s["url"] for s in r["sources"] if s["kind"] in PRINTED_SOURCE_KINDS and s["url"]],
        "context": {"title": parent["title"], "organisation": parent["organisation"]}
        if parent is not None and parent["id"] not in printed else None,
        "children": entries(children.get(r["id"], []), printed, by_id, children),
    }


def _course_key(r: dict) -> tuple[str, str]:
    return name_key(r["title"] or ""), name_key(r["organisation"] or "")


def entries(
    group: list[dict], printed: set[int], by_id: Mapping[int, dict], children: Mapping[int, list[dict]]
) -> list[dict]:
    """Payloads for sibling records in print order (record_sort_key); course records with the same title and
    organisation become one course group, where the newest of them stands."""
    out: list[dict] = []
    courses: dict[tuple[str, str], dict] = {}
    for r in sorted(group, key=record_sort_key):
        payload = _record_payload(r, printed, by_id, children)
        if r["kind"] != "course":
            out.append(payload)
            continue
        key = _course_key(r)
        if key not in courses:
            courses[key] = {
                "kind": "course", "title": r["title"], "organisation": r["organisation"], "location": r["location"],
                "terms": [], "record_ids": [], "lines": [], "sources": [], "context": payload["context"],
                "children": [],
            }
            out.append(courses[key])
        course = courses[key]
        course["terms"].append(
            {"start_date": r["start_date"], "end_date": r["end_date"], "ongoing": bool(r["ongoing"])}
        )
        course["record_ids"].append(r["id"])
        course["lines"] += [line for line in payload["lines"] if line not in course["lines"]]
        course["sources"] += [s for s in payload["sources"] if s not in course["sources"]]
        course["context"] = course["context"] or payload["context"]
        course["children"] += payload["children"]
    return out


# --- The proposal ---


def propose(conn: Connection, job_id: int, choice: Choice = Choice(), now: datetime | None = None) -> Proposal:
    """The proposed CV for a posting under a choice. Reads only."""
    asked = queries.posting_skills(conn, job_id)
    profile = queries.profile(conn)
    profile_skills = queries.profile_skills(conn)
    levels = {row.id: row.level for row in profile_skills}
    names = {row.id: row.name for row in profile_skills}
    links = queries.effective_links(conn, [s["key"] for s in asked]) if asked else {}
    options = {key: link["options"] for key, link in links.items()}
    values = skill_values(asked, options, levels)
    linked = {o["skill_id"] for opts in options.values() for o in opts}

    every_record = [r for _, group in profile["records"] for r in group]
    public = [r for r in every_record if r["effective_disclosure"] != "private"]
    by_id = {r["id"]: r for r in public}
    needles = private_needles([r for r in every_record if r["effective_disclosure"] == "private"])

    # Highlights
    highlights = [
        {**h, "skill_ids": {c["skill_id"] for c in h["claims"]}, "flag": private_mention(h["text"], needles)}
        for h in profile["highlights"]
    ]
    ticked_h, unticked_h = choice.ticked["h"], choice.unticked["h"]
    skip = {h["id"] for h in highlights if h["id"] in unticked_h or (h["flag"] and h["id"] not in ticked_h)}
    greedy, shown = choose_highlights(highlights, values, linked, choice.budget, skip)
    greedy_ids = [h["id"] for h, _ in greedy]
    chosen_h = greedy_ids + sorted(h["id"] for h in highlights if h["id"] in ticked_h and h["id"] not in greedy_ids)
    gains = {h["id"]: g for h, g in greedy}
    highlight_rows = [
        {
            "id": h["id"], "text": h["text"], "claims": [c["name"] for c in h["claims"]],
            "gain": gains.get(h["id"], gain(h["skill_ids"], values, shown, linked)),
            "chosen": h["id"] in chosen_h, "position": chosen_h.index(h["id"]) + 1 if h["id"] in chosen_h else None,
            "ticked": h["id"] in ticked_h, "unticked": h["id"] in unticked_h,
            "auto": h["id"] in greedy_ids and h["id"] not in ticked_h, "flag": h["flag"],
        }
        for h in highlights
    ]
    highlight_rows.sort(key=lambda h: (h["position"] or len(chosen_h) + 1, -round(h["gain"], 9), h["id"]))

    # Records
    ticked_r, unticked_r = choice.ticked["r"], choice.unticked["r"]
    rel = {r["id"]: relevance({g["skill_id"] for g in r["grounds"]}, values) for r in public}
    printed: set[int] = set()
    auto_r: set[int] = set()
    record_groups = []
    for kind in RECORD_KINDS:
        group = sorted((r for r in public if r["kind"] == kind), key=record_sort_key)
        if not group:
            continue
        rule = KIND_RULES[kind]
        if rule == "all":
            auto = [r["id"] for r in group if r["id"] not in unticked_r]
        else:
            ranked = sorted(group, key=lambda r: (-round(rel[r["id"]], 9), record_sort_key(r)))
            auto = [r["id"] for r in ranked if r["id"] not in unticked_r][:choice.counts[kind]]
        chosen = set(auto) | {r["id"] for r in group if r["id"] in ticked_r}
        printed |= chosen
        auto_r |= set(auto) - ticked_r
        record_groups.append({
            "kind": kind, "rule": rule, "count": None if rule == "all" else choice.counts[kind],
            "records": [
                {"id": r["id"], "label": r["label"], "relevance": rel[r["id"]], "chosen": r["id"] in chosen,
                 "ticked": r["id"] in ticked_r, "unticked": r["id"] in unticked_r,
                 "auto": r["id"] in auto and r["id"] not in ticked_r}
                for r in group
            ],
        })
    for g in record_groups:
        for row in g["records"]:
            parent = by_id[row["id"]]["part_of_id"]
            row["under"] = by_id[parent]["label"] if row["chosen"] and parent in printed else None

    # Details
    ticked_d, unticked_d = choice.ticked["d"], choice.unticked["d"]
    detail_rows = []
    for d in profile["details"]:
        auto = d["kind"] in DEFAULT_DETAILS and d["id"] not in unticked_d
        detail_rows.append({
            "id": d["id"], "kind": d["kind"], "label": d["label"], "text": d["text"],
            "chosen": auto or d["id"] in ticked_d, "auto": auto and d["id"] not in ticked_d,
            "ticked": d["id"] in ticked_d, "unticked": d["id"] in unticked_d,
        })

    # Gaps
    highlight_skills = {h["id"]: h["skill_ids"] for h in highlights}
    shown_skills = set().union(*(highlight_skills[i] for i in chosen_h),
                               *({g["skill_id"] for g in by_id[i]["grounds"]} for i in printed))
    gaps = []
    for s in asked:
        opts = options.get(s["key"], [])
        if recommend.credit(opts, levels) <= 0:
            continue
        had = {o["skill_id"] for o in opts if level_rank(levels.get(o["skill_id"])) > level_rank("missing")}
        if had & shown_skills:
            continue
        best = recommend.best_option(opts, levels)
        gaps.append({
            "key": s["key"], "name": s["name"], "importance": s["importance"],
            "skill_name": names[best["skill_id"]],
            "covered_by_unchosen": any(had & highlight_skills[h["id"]] for h in highlights if h["id"] not in chosen_h),
        })
    gaps.sort(key=lambda g: (-IMPORTANCE_RANK[g["importance"]], g["name"].casefold()))

    # Content, in print order
    by_highlight = {h["id"]: h for h in highlights}
    items = [
        {"section": "header" if d["kind"] in HEADER_KINDS else d["kind"], "source_kind": "detail", "source_id": d["id"],
         "payload": {"kind": d["kind"], "label": d["label"], "text": d["text"]}}
        for d in detail_rows if d["chosen"]
    ]
    items += [
        {
            "section": "highlights",
            "source_kind": "highlight",
            "source_id": i,
            "payload": {"text": by_highlight[i]["text"]},
        }
        for i in chosen_h
    ]
    children: dict[int, list[dict]] = defaultdict(list)
    roots = []
    for i in printed:
        parent = by_id[i]["part_of_id"]
        (children[parent] if parent in printed else roots).append(by_id[i])
    for kind in (k for k in SECTION_ORDER if k in RECORD_KINDS):
        for payload in entries([r for r in roots if r["kind"] == kind], printed, by_id, children):
            group = "record_ids" in payload
            items.append({"section": kind, "source_kind": "course_group" if group else "record",
                          "source_id": None if group else payload["id"], "payload": payload})
    left_out = sorted({r["kind"] for r in public if r["id"] not in printed}, key=RECORD_KINDS.index)
    day = (now or utcnow()).astimezone().date().isoformat()

    credits = {s["key"]: recommend.credit(options.get(s["key"], []), levels) for s in asked}
    return Proposal(
        job_id=job_id,
        choice=choice,
        score=recommend.score(asked, credits, options)["score"],
        has_skills=bool(asked),
        highlights=highlight_rows,
        records=record_groups,
        details=detail_rows,
        gaps=gaps,
        content={"produced": day, "left_out": left_out, "items": items},
    )
