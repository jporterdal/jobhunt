"""Link measurement (`jobhunt eval --links`): how well candidate-finding methods and judging versions reproduce
the links the user chose by hand (their overrides), so a new linking method is adopted or discarded on evidence.

Measuring stores its judgments in link_measurements, which only this module reads: they never decide a link.
Expansions and vectors are the same as the app's for the same skill, step and context, so both share them.
Judgments are reused from link_measurements and from the app's link_judgments when the posting skill, judging
version, chat model, embedding model and ordered candidate list are the same.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.engine import Connection, Engine

from ..db import link_judgments, link_measurements, link_relations, skill_link_overrides
from ..userdata import get_setting
from . import expand, links
from .pipeline import StepFailed, Unreachable

SWEEP_SIZES = (3, 5, 8, 10, 15)
SWEEP_FLOORS = (0.60, 0.65, 0.70, 0.75, 0.80, 0.85)
RELATION_ORDER = ("same", "specific", "general", "related")

# The outcomes of a reference link, in report order.
OUTCOMES = (
    ("right", "right skill, right relation"),
    ("other_relation", "right skill, another relation"),
    ("tied", "another skill, tied with yours"),
    ("refused", "no link, right skill was a candidate"),
    ("wrong_skill", "linked to another skill"),
    ("not_found", "no link, right skill not a candidate"),
)


class NoReference(Exception):
    """No override is in the reference set."""


class NoModel(Exception):
    """No chat model or no embedding model to measure with; the message says which."""


class UnknownMethod(ValueError):
    """A candidate-finding method or judging version this code doesn't have; the message names the available ones."""


def check_methods(retrievals: list[str], judges: list[str]) -> None:
    for name in retrievals:
        if name not in links.RETRIEVALS:
            raise UnknownMethod(f"unknown candidate-finding method {name!r}; available: {', '.join(links.RETRIEVALS)}")
    for name in judges:
        if name not in links.JUDGES:
            raise UnknownMethod(f"unknown judging version {name!r}; available: {', '.join(links.JUDGES)}")


# --- The reference set ---


@dataclass(frozen=True)
class Reference:
    key: str
    name: str
    quote: str | None
    skill_id: int | None  # None: a confirmed refusal
    skill_name: str | None
    relation: str | None


@dataclass
class ReferenceSet:
    links: list[Reference]
    refusals: list[Reference]
    left_out: dict[str, int]  # reason -> number of overrides

    @property
    def all(self) -> list[Reference]:
        return self.links + self.refusals


def reference_set(conn: Connection) -> ReferenceSet:
    """The user's overrides on posting skills that are still posting skills, have no same-identity profile skill
    (one with the same key, or of which the key is an alias), and aren't stale. A link to a profile skill is a
    reference link, "no link" a confirmed refusal."""
    from ..queries import posting_skill_keys, profile_skills, same_identity

    posting = {k["key"]: k for k in posting_skill_keys(conn)}
    profile_list = profile_skills(conn)
    profile = {s.id: s for s in profile_list}
    profile_keys = set(same_identity(conn, profile_list))
    out = ReferenceSet([], [], {"not a posting skill": 0, "same identity": 0, "stale": 0})
    for row in conn.execute(select(skill_link_overrides).order_by(skill_link_overrides.c.posting_key)):
        if row.posting_key not in posting:
            out.left_out["not a posting skill"] += 1
            continue
        if row.posting_key in profile_keys:
            out.left_out["same identity"] += 1
            continue
        if row.skill_id is not None and row.skill_id not in profile:
            out.left_out["stale"] += 1
            continue
        k = posting[row.posting_key]
        skill = profile.get(row.skill_id)
        ref = Reference(k["key"], k["name"], k["quote"], row.skill_id, skill.name if skill else None, row.relation)
        (out.links if row.skill_id is not None else out.refusals).append(ref)
    return out


# --- Reuse of judgments ---


def _reuse_index(conn: Connection, model: str, embed_model: str, since: datetime | None) -> dict[tuple, dict[int, str]]:
    """(posting key, judge, ordered candidate ids) -> relations, from succeeded judgments by the chat and
    embedding model: the app's and earlier measurements'. `since` keeps only those made from then on (--fresh)."""
    index: dict[tuple, dict[int, str]] = {}
    app = select(link_judgments).where(
        link_judgments.c.status == "succeeded", link_judgments.c.model == model,
        link_judgments.c.embed_model == embed_model,
    )
    if since is not None:
        app = app.where(link_judgments.c.created_at >= since)
    judged = conn.execute(app.order_by(link_judgments.c.id)).all()
    relations: dict[int, dict[int, str]] = {}
    if judged:
        for row in conn.execute(select(link_relations).where(link_relations.c.judgment_id.in_([j.id for j in judged]))):
            relations.setdefault(row.judgment_id, {})[row.skill_id] = row.relation
    for j in judged:
        judge = links.judge_of(j.pipeline)
        ids = tuple(c["skill_id"] for c in json.loads(j.candidates_json))
        index[(j.posting_key, judge, ids)] = relations.get(j.id, {})
    own = select(link_measurements).where(
        link_measurements.c.status == "succeeded", link_measurements.c.model == model,
        link_measurements.c.embed_model == embed_model,
    )
    if since is not None:
        own = own.where(link_measurements.c.created_at >= since)
    for m in conn.execute(own.order_by(link_measurements.c.id)):
        ids = tuple(c["skill_id"] for c in json.loads(m.candidates_json))
        index[(m.posting_key, m.judge, ids)] = {int(k): v for k, v in json.loads(m.relations_json).items()}
    return index


# --- The plan ---


@dataclass(frozen=True)
class Combo:
    retrieval: str
    judge: str

    @property
    def label(self) -> str:
        return f"{self.retrieval} + {self.judge}"


@dataclass
class Plan:
    """What a measurement needs, worked out before any model request."""

    model: str
    embed_model: str
    combos: list[Combo]
    reference: ReferenceSet
    preview_keys: list[dict]  # posting skills judged by the app, for --all-skills (else empty)
    fresh: bool
    started: datetime
    expansions: list[expand.Wanted]
    embeddings: int  # phrases known now without a stored vector
    judgments: dict[str, int]  # combo label -> judging requests (an upper bound when `exact` is False)
    exact: dict[str, bool]

    @property
    def needs_requests(self) -> bool:
        return bool(self.expansions or self.embeddings or any(self.judgments.values()))

    def statement(self) -> str:
        lines = [
            f"link measurement with {self.model} (embeddings: {self.embed_model}): "
            f"{len(self.reference.links)} reference links, {len(self.reference.refusals)} confirmed refusals"
            + (f", {len(self.preview_keys)} posting skills to preview" if self.preview_keys else ""),
            f"  expansion requests: {len(self.expansions)}",
            f"  phrases to embed: {self.embeddings}"
            + (f", plus up to {expand.MAX_PHRASES} per new expansion" if self.expansions else ""),
        ]
        for combo in self.combos:
            n = self.judgments[combo.label]
            lines.append(f"  judging requests for {combo.label}: {'' if self.exact[combo.label] else 'up to '}{n}")
        return "\n".join(lines)


def _resolve_models(conn: Connection, client, model: str | None) -> tuple[str, str]:
    model = model or get_setting(conn, "llm.model")
    if not model:
        raise NoModel("no chat model chosen; pass --model or choose one in Settings")
    try:
        embed_model = links.embed_model(conn, client)
        if embed_model is None:
            raise NoModel("no embedding model chosen or installed; choose one in Settings")
    except Unreachable:
        # The request statement can still be made; requests will fail later.
        embed_model = get_setting(conn, "llm.embed_model") or conn.execute(
            select(link_judgments.c.embed_model).order_by(link_judgments.c.id.desc()).limit(1)
        ).scalar()
        if not embed_model:
            raise NoModel("no embedding model chosen; choose one in Settings") from None
    return model, embed_model


def _keys(reference: ReferenceSet, preview: list[dict]) -> list[dict]:
    """posting_skill_keys-style dicts for every posting skill measured or previewed, once each."""
    out = {r.key: {"key": r.key, "name": r.name, "quote": r.quote} for r in reference.all}
    for k in preview:
        out.setdefault(k["key"], k)
    return list(out.values())


def plan(engine: Engine, client, retrievals: list[str] | None = None, judges: list[str] | None = None,
         model: str | None = None, fresh: bool = False, all_skills: bool = False) -> Plan:
    """Raises UnknownMethod, NoReference or NoModel; makes no model request (it may ask the server which models
    are installed)."""
    from ..queries import expansion_contexts, profile_skills

    retrievals = retrievals or [links.CURRENT_RETRIEVAL]
    judges = judges or [links.CURRENT_JUDGE]
    check_methods(retrievals, judges)
    combos = [Combo(r, j) for r in retrievals for j in judges]
    current = Combo(links.CURRENT_RETRIEVAL, links.CURRENT_JUDGE)
    if current in combos:
        combos.remove(current)
        combos.insert(0, current)
    started = datetime.now(UTC)
    with engine.connect() as conn:
        reference = reference_set(conn)
        if not reference.all:
            raise NoReference()
        model, embed_model = _resolve_models(conn, client, model)
        preview = links._judged_keys(conn)[0] if all_skills else []
        keys = _keys(reference, preview)
        profile = profile_skills(conn)
        contexts = expansion_contexts(conn)
        wanted: dict[tuple, expand.Wanted] = {}
        for name in retrievals:
            if links.RETRIEVALS[name].expands:
                for w in expand.missing(conn, keys, profile, contexts, links.RETRIEVALS[name].expansion):
                    wanted.setdefault((w.side, w.key, w.context), w)
        texts: dict[str, str] = {}
        for name in retrievals:
            texts |= links.texts_to_embed(conn, embed_model, links.RETRIEVALS[name], keys, profile)
        reuse = _reuse_index(conn, model, embed_model, started if fresh else None)
        judgments, exact = {}, {}
        ranked_by = {}
        for name in retrievals:
            complete = not texts and not (links.RETRIEVALS[name].expands and wanted)
            ranked_by[name] = (
                links.ranked(conn, embed_model, links.RETRIEVALS[name], keys, profile) if complete else None
            )
        for combo in combos:
            ranked = ranked_by[combo.retrieval]
            if ranked is None:
                judgments[combo.label] = len(keys) + len(reference.links)
                exact[combo.label] = False
                continue
            requests = [
                (key, candidates) for key, candidates in _requests(combo, ranked, reference, preview)
                if candidates and (key, combo.judge, tuple(c.skill_id for c in candidates)) not in reuse
            ]
            needed = {(key, tuple(c.skill_id for c in cs)) for key, cs in requests}
            judgments[combo.label], exact[combo.label] = len(needed), True
    return Plan(model, embed_model, combos, reference, preview, fresh, started, list(wanted.values()), len(texts),
                judgments, exact)


def _shortlist(combo: Combo, ranked: list[links.Candidate]) -> list[links.Candidate]:
    size, floor = links.RETRIEVALS[combo.retrieval].limits()
    return links.cut(ranked, size, floor)


def _with_right_skill(shortlist: list[links.Candidate], ranked: list[links.Candidate], skill_id: int):
    """The shortlist with the right skill inserted at its similarity rank, or None when it's already in it."""
    if any(c.skill_id == skill_id for c in shortlist):
        return None
    right = next(c for c in ranked if c.skill_id == skill_id)
    return sorted([*shortlist, right], key=lambda c: (-c.similarity, c.name))


def _requests(combo: Combo, ranked: dict[str, list], reference: ReferenceSet, preview: list[dict]):
    """(posting key, candidates) for every judgment the combination needs."""
    for ref in reference.all:
        shortlist = _shortlist(combo, ranked[ref.key])
        yield ref.key, shortlist
        if ref.skill_id is not None:
            added = _with_right_skill(shortlist, ranked[ref.key], ref.skill_id)
            if added is not None:
                yield ref.key, added
    for k in preview:
        if k["key"] in ranked:
            yield k["key"], _shortlist(combo, ranked[k["key"]])


# --- Execution ---


def resulting_link(candidates: list[links.Candidate], relations: dict[int, str]) -> tuple[int, str] | None:
    """(skill id, relation) of the strongest relation, the most similar first among equals; None for no link."""
    best = None
    for position, c in enumerate(candidates):
        relation = relations.get(c.skill_id, "none")
        if relation not in RELATION_ORDER:
            continue
        rank = (RELATION_ORDER.index(relation), position)
        if best is None or rank < best[0]:
            best = (rank, (c.skill_id, relation))
    return best[1] if best else None


@dataclass
class Judged:
    candidates: list[links.Candidate]
    relations: dict[int, str]
    status: str  # 'succeeded', 'failed' or 'empty' (no candidates, no request)
    reused: bool = False

    @property
    def link(self) -> tuple[int, str] | None:
        return resulting_link(self.candidates, self.relations) if self.status == "succeeded" else None


@dataclass
class Outcome:
    """One reference posting skill under one combination."""

    ref: Reference
    rank: int | None  # of the right skill among all profile skills (1 = most similar); None for refusals
    similarity: float | None
    judged: Judged
    added: Judged | None = None  # judged again with the right skill added, when the shortlist lacked it

    @property
    def shortlisted(self) -> bool:
        return any(c.skill_id == self.ref.skill_id for c in self.judged.candidates)

    def outcome(self, with_added: bool = False) -> str:
        judged = self.added if with_added and self.added is not None else self.judged
        link = judged.link
        if link is not None and link[0] == self.ref.skill_id:
            return "right" if link[1] == self.ref.relation else "other_relation"
        if link is not None:
            # The judge gave your skill the winning relation too: it lost only on shortlist order.
            return "tied" if judged.relations.get(self.ref.skill_id) == link[1] else "wrong_skill"
        return "refused" if any(c.skill_id == self.ref.skill_id for c in judged.candidates) else "not_found"


@dataclass
class ComboResult:
    combo: Combo
    links: list[Outcome] = field(default_factory=list)
    refusals: list[Outcome] = field(default_factory=list)
    preview: dict[str, Judged] = field(default_factory=dict)
    failed: int = 0

    def counts(self, with_added: bool = False) -> dict[str, int]:
        out = {name: 0 for name, _ in OUTCOMES}
        for o in self.links:
            out[o.outcome(with_added)] += 1
        return out

    @property
    def kept(self) -> int:
        return sum(_good(o) for o in self.refusals)


def _good(o: Outcome) -> bool:
    """A reference link judged with the right skill and relation, or a confirmed refusal kept."""
    if o.ref.skill_id is None:
        return o.judged.status != "failed" and o.judged.link is None
    return o.outcome() == "right"


@dataclass
class RetrievalResult:
    name: str
    ranked: dict[str, list[links.Candidate]]
    size: int
    floor: float


@dataclass
class Report:
    plan: Plan
    retrievals: list[RetrievalResult]
    results: list[ComboResult]
    current_links: dict[str, tuple[int, str] | None]  # the app's links of previewed keys
    new_judgments: int = 0
    reused_judgments: int = 0
    names: dict[int, str] = field(default_factory=dict)  # profile skill id -> name


def execute(engine: Engine, client, plan: Plan, progress: Callable[[str], None] = lambda _: None) -> Report:
    """Make the plan's expansions, embeddings and judgments, each stored as it's made, then score. Raises
    Unreachable when requests are needed and the server can't be reached, and StepFailed when embedding fails."""
    from ..queries import effective_links, profile_skills
    from . import derived

    if plan.expansions:
        progress(f"expanding {len(plan.expansions)} skills")
        expand.expand_all(engine, client.for_model(plan.model, _num_ctx(engine)), plan.model, plan.expansions)
    keys = _keys(plan.reference, plan.preview_keys)
    with engine.connect() as conn:
        profile = profile_skills(conn)
        texts: dict[str, str] = {}
        for combo in plan.combos:
            texts |= links.texts_to_embed(conn, plan.embed_model, links.RETRIEVALS[combo.retrieval], keys, profile)
    if texts:
        progress(f"embedding {len(texts)} phrases")
        vectors = client.embed(plan.embed_model, [links.embed_text(plan.embed_model, t) for t in texts.values()])
        with engine.begin() as conn:
            derived.save_embeddings(conn, plan.embed_model, dict(zip(texts, vectors, strict=True)))

    with engine.connect() as conn:
        contexts = {judge: links.judge_contexts(conn, links.JUDGES[judge]) for judge in {c.judge for c in plan.combos}}
        reuse = _reuse_index(conn, plan.model, plan.embed_model, plan.started if plan.fresh else None)
        retrievals = []
        for name in dict.fromkeys(c.retrieval for c in plan.combos):
            retrieval = links.RETRIEVALS[name]
            size, floor = retrieval.limits()
            retrievals.append(
                RetrievalResult(name, links.ranked(conn, plan.embed_model, retrieval, keys, profile), size, floor)
            )
        current = effective_links(conn, [k["key"] for k in plan.preview_keys]) if plan.preview_keys else {}
    report = Report(plan, retrievals, [], {
        key: (link["skill_id"], link["relation"]) if link["skill_id"] is not None else None
        for key, link in current.items()
    }, names={s.id: s.name for s in profile})
    by_name = {r.name: r for r in retrievals}
    llm = None

    def judged(combo: Combo, key: str, name: str, quote: str | None, candidates: list[links.Candidate]) -> Judged:
        nonlocal llm
        if not candidates:
            return Judged(candidates, {}, "empty", reused=True)
        index = (key, combo.judge, tuple(c.skill_id for c in candidates))
        if index in reuse:
            report.reused_judgments += 1
            return Judged(candidates, reuse[index], "succeeded", reused=True)
        if llm is None:
            llm = client.for_model(plan.model, _num_ctx(engine))
        item = links.Planned(key, name, quote, candidates)
        relations, status, error, output = {}, "succeeded", None, {}
        try:
            relations = links.JUDGES[combo.judge].judge(item, contexts[combo.judge], llm)
            output = {"relations": relations}
        except StepFailed as exc:
            status, error = "failed", f"{exc.step or 'link'}: {exc.message}"
        with engine.begin() as conn:
            derived.save_measurement(
                conn, item, combo.judge, plan.model, plan.embed_model, status, error, relations, output
            )
        report.new_judgments += 1
        if status == "succeeded":
            reuse[index] = relations
        return Judged(candidates, relations, status)

    for combo in plan.combos:
        progress(f"judging with {combo.label}")
        ranked = by_name[combo.retrieval].ranked
        result = ComboResult(combo)
        for ref in plan.reference.all:
            shortlist = _shortlist(combo, ranked[ref.key])
            first = judged(combo, ref.key, ref.name, ref.quote, shortlist)
            result.failed += first.status == "failed"
            if ref.skill_id is None:
                result.refusals.append(Outcome(ref, None, None, first))
                continue
            position = next(i for i, c in enumerate(ranked[ref.key]) if c.skill_id == ref.skill_id)
            added_list = _with_right_skill(shortlist, ranked[ref.key], ref.skill_id)
            added = judged(combo, ref.key, ref.name, ref.quote, added_list) if added_list is not None else None
            result.links.append(Outcome(ref, position + 1, ranked[ref.key][position].similarity, first, added))
        for k in plan.preview_keys:
            if k["key"] in ranked:
                result.preview[k["key"]] = judged(
                    combo, k["key"], k["name"], k["quote"], _shortlist(combo, ranked[k["key"]])
                )
        report.results.append(result)
    return report


def _num_ctx(engine: Engine) -> int:
    with engine.connect() as conn:
        return get_setting(conn, "llm.num_ctx")


# --- Scoring and reports ---


def sweep(retrieval: RetrievalResult, reference: ReferenceSet) -> list[dict]:
    """For each listed size and floor: reference links whose skill is shortlisted, and the mean number of
    candidates per reference posting skill. From stored vectors only."""
    out = []
    for size in SWEEP_SIZES:
        for floor in SWEEP_FLOORS:
            found = sum(
                any(c.skill_id == r.skill_id for c in links.cut(retrieval.ranked[r.key], size, floor))
                for r in reference.links
            )
            counts = [len(links.cut(retrieval.ranked[r.key], size, floor)) for r in reference.all]
            out.append(
                {
                    "size": size,
                    "floor": floor,
                    "shortlisted": found,
                    "mean_candidates": round(sum(counts) / len(counts), 2),
                }
            )
    return out


SIGNIFICANCE = 0.05


@dataclass(frozen=True)
class Comparison:
    """Reference posting skills one combination gets right (a right link, or a kept refusal) and the base gets
    wrong (`fixed`), and the other way round (`broke`)."""

    fixed: int
    broke: int

    @property
    def p(self) -> float:
        """One-sided exact sign test: the chance of a split at least this uneven if each differing posting skill
        were a coin toss. Judging the same skill twice can flip, so small differences are expected."""
        n = self.fixed + self.broke
        if n == 0:
            return 1.0
        return sum(math.comb(n, k) for k in range(min(self.fixed, self.broke) + 1)) / 2 ** n

    @property
    def verdict(self) -> str:
        if self.fixed == self.broke == 0:
            return "same"
        if self.p <= SIGNIFICANCE and self.fixed != self.broke:
            return "better" if self.fixed > self.broke else "worse"
        return "within noise"

    def describe(self) -> str:
        if self.verdict == "same":
            return "same"
        return f"{self.verdict} (fixed {self.fixed}, broke {self.broke}, p={self.p:.2f})"


def compare(base: ComboResult, other: ComboResult) -> Comparison:
    """`other` against `base`, posting skill by posting skill."""
    before = {o.ref.key: _good(o) for o in _outcomes(base)}
    after = [(before[o.ref.key], _good(o)) for o in _outcomes(other)]
    return Comparison(sum(not a and b for a, b in after), sum(a and not b for a, b in after))


def verdict(base: ComboResult, other: ComboResult) -> str:
    """'better', 'worse', 'same' or 'within noise' for `other` against `base`."""
    return compare(base, other).verdict


def _link_label(link, names: dict[int, str]) -> str:
    return "no link" if link is None else f"{names.get(link[0], link[0])} ({link[1]})"


def differing(report: Report) -> list[dict]:
    """Reference posting skills whose resulting link differs between combinations."""
    out = []
    for ref in report.plan.reference.all:
        per_combo = {}
        for result in report.results:
            outcome = (result.links + result.refusals)
            found = next(o for o in outcome if o.ref.key == ref.key)
            per_combo[result.combo.label] = found.judged.link
        if len(set(per_combo.values())) > 1:
            user = (ref.skill_id, ref.relation) if ref.skill_id is not None else None
            out.append({"key": ref.key, "name": ref.name, "user": user, "links": per_combo})
    return out


def _outcomes(result: ComboResult) -> list[Outcome]:
    return result.links + result.refusals


def format_text(report: Report) -> str:
    plan, names = report.plan, report.names
    ref = plan.reference
    left = ", ".join(f"{n} {reason}" for reason, n in ref.left_out.items() if n) or "none"
    lines = [
        f"Link measurement with {plan.model} (embeddings: {plan.embed_model})",
        f"Reference set: {len(ref.links)} links, {len(ref.refusals)} confirmed refusals (left out: {left})",
        f"Judgments: {report.new_judgments} new, {report.reused_judgments} reused",
        "",
    ]
    for r in report.retrievals:
        shortlisted = [o for o in report.results if o.combo.retrieval == r.name][0].links
        hit = sum(o.shortlisted for o in shortlisted)
        no_candidate = sum(not _shortlist(Combo(r.name, ""), r.ranked[x.key]) for x in ref.refusals)
        lines.append(f"Candidate finding: {r.name} (size {r.size}, floor {r.floor:.2f})")
        lines.append(f"  reference links shortlisted: {hit} of {len(ref.links)}")
        lines.append(f"  confirmed refusals with no candidate: {no_candidate} of {len(ref.refusals)}")
        for o in shortlisted:
            if not o.shortlisted:
                lines.append(
                    f"  missed: {o.ref.name} -> {o.ref.skill_name} (rank {o.rank}, similarity {o.similarity:.2f})"
                )
        lines.append("  sweep (shortlisted links / mean candidates):")
        table = sweep(r, ref)
        lines.append("    size " + "".join(f"{f:>12.2f}" for f in SWEEP_FLOORS))
        for size in SWEEP_SIZES:
            cells = [c for c in table if c["size"] == size]
            lines.append(
                f"    {size:>4} " + "".join(f"{c['shortlisted']:>6}/{c['mean_candidates']:<5.1f}" for c in cells)
            )
        lines.append("")
    base = report.results[0]
    for result in report.results:
        counts, added = result.counts(), result.counts(with_added=True)
        lines.append(
            f"Judging: {result.combo.label}"
            + ("" if result is base else f"  verdict: {compare(base, result).describe()}")
        )
        for name, label in OUTCOMES:
            lines.append(f"  {label:<40} {counts[name]:>3}   (right skill added: {added[name]})")
        lines.append(f"  confirmed refusals kept                  {result.kept:>3} of {len(ref.refusals)}")
        if result.failed:
            lines.append(f"  failed judgments: {result.failed}")
        if result.preview:
            linked = sum(j.link is not None for j in result.preview.values())
            differ = sum(j.link != report.current_links.get(k) for k, j in result.preview.items())
            lines.append(
                f"  preview: {linked} of {len(result.preview)} posting skills linked, "
                f"{differ} differ from the app's links"
            )
        lines.append("")
    diffs = differing(report)
    if diffs:
        lines.append("Posting skills whose link differs between combinations:")
        for d in diffs:
            lines.append(f"  {d['name']}: yours {_link_label(d['user'], names)}")
            for label, link in d["links"].items():
                lines.append(f"    {label}: {_link_label(link, names)}")
    return "\n".join(lines).rstrip() + "\n"


def _candidate_dict(c: links.Candidate) -> dict:
    return {
        "skill_id": c.skill_id,
        "name": c.name,
        "similarity": c.similarity,
        "pair": list(c.pair) if c.pair else None,
    }


def _judged_dict(j: Judged | None, names: dict[int, str]) -> dict | None:
    if j is None:
        return None
    return {
        "candidates": [_candidate_dict(c) for c in j.candidates],
        "relations": {names.get(k, str(k)): v for k, v in j.relations.items()},
        "status": j.status,
        "reused": j.reused,
        "link": None
        if j.link is None
        else {"skill_id": j.link[0], "name": names.get(j.link[0]), "relation": j.link[1]},
    }


def _comparison_dict(c: Comparison) -> dict:
    return {"fixed": c.fixed, "broke": c.broke, "p": round(c.p, 4)}


def to_dict(report: Report) -> dict:
    plan, names = report.plan, report.names
    base = report.results[0]
    return {
        "model": plan.model,
        "embed_model": plan.embed_model,
        "reference": {
            "links": len(plan.reference.links),
            "refusals": len(plan.reference.refusals),
            "left_out": plan.reference.left_out,
        },
        "judgments": {"new": report.new_judgments, "reused": report.reused_judgments},
        "retrievals": [
            {
                "name": r.name,
                "size": r.size,
                "floor": r.floor,
                "sweep": sweep(r, plan.reference),
                "shortlisted": sum(
                    o.shortlisted for o in [x for x in report.results if x.combo.retrieval == r.name][0].links
                ),
            }
            for r in report.retrievals
        ],
        "combinations": [
            {
                "retrieval": result.combo.retrieval,
                "judge": result.combo.judge,
                "verdict": None if result is base else verdict(base, result),
                "comparison": None if result is base else _comparison_dict(compare(base, result)),
                "counts": result.counts(),
                "counts_right_skill_added": result.counts(with_added=True),
                "refusals_kept": result.kept,
                "failed": result.failed,
                "preview": None
                if not result.preview
                else {
                    "posting_skills": len(result.preview),
                    "linked": sum(j.link is not None for j in result.preview.values()),
                    "differ_from_app": sum(j.link != report.current_links.get(k) for k, j in result.preview.items()),
                },
            }
            for result in report.results
        ],
        "per_posting_skill": [
            {
                "key": ref.key,
                "name": ref.name,
                "user": None
                if ref.skill_id is None
                else {"skill_id": ref.skill_id, "name": ref.skill_name, "relation": ref.relation},
                "combinations": {
                    result.combo.label: {
                        **_judged_dict(o.judged, names),
                        "outcome": o.outcome()
                        if ref.skill_id is not None
                        else ("kept" if o.judged.link is None else "broken"),
                        "rank": o.rank,
                        "right_skill_added": _judged_dict(o.added, names),
                    }
                    for result in report.results
                    for o in _outcomes(result)
                    if o.ref.key == ref.key
                },
            }
            for ref in plan.reference.all
        ],
        "differing": differing(report),
    }


def report_json(report: Report) -> str:
    return json.dumps(to_dict(report), indent=2, ensure_ascii=False)
