"""Links from posting skills to profile skills: candidate-finding methods and the embedding shortlist, the
link-judge versions, the plan of what to judge, and the judging loop a links job runs. derived.py stores what
this module produces.

A posting skill with an override, or with a profile skill of the same key, is never judged. For the rest,
the profile skills most similar by embedding go to the chat model, which judges each one's relation. A skill
is compared through its phrases: its name, plus its expansion's phrasings when the candidate-finding method
expands (enrich/expand.py); a profile skill's similarity is that of its most similar pair of phrases.

The app uses one linking method, named here (CURRENT_RETRIEVAL, CURRENT_JUDGE); the other registered entries
exist only to be measured (enrich/link_eval.py). A key is judged again only when its shortlist, the embedding
model or the linking method differs from its latest judgment's, so a pass after a small change makes few
requests, and a new method version re-judges everything.
"""

from __future__ import annotations

import json
import math
import operator
import struct
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.engine import Connection, Engine

from ..db import link_judgments, skill_embeddings, skill_link_overrides
from ..userdata import LINK_RELATIONS, get_setting, name_key
from . import expand
from .pipeline import LLM, Cancelled, StepFailed, conform

NAME = "link-judge"
ALL_SCOPE = " scope=all"  # appended to a links job's pipeline: re-judge every key without an override

DEFAULT_EMBED_MODEL = "nomic-embed-text"
# Task prefixes models recommend for symmetric similarity; the text after it is the skill's name.
EMBED_PREFIXES = {"nomic-embed-text": "clustering: "}

# The shortlist of the "names" method (bare names).
SHORTLIST_K = 5
# nomic-embed-text puts any two skill names at 0.65 or more; at 0.75 the first real pass judged 150 of 223
# posting skills instead of all of them, and the weakest model links lost their candidates.
SHORTLIST_FLOOR = 0.75


@dataclass(frozen=True)
class Retrieval:
    """A candidate-finding method: the expansion step whose phrasings are compared beside the names (None: names
    only), and the shortlist size and floor (None: SHORTLIST_K and SHORTLIST_FLOOR, read when used)."""

    name: str
    expansion: str | None = None
    size: int | None = None
    floor: float | None = None

    @property
    def expands(self) -> bool:
        return self.expansion is not None

    def limits(self) -> tuple[int, float]:
        return (
            SHORTLIST_K if self.size is None else self.size,
            SHORTLIST_FLOOR if self.floor is None else self.floor,
        )


NAMES = "names"
RETRIEVALS = {
    r.name: r
    for r in (
        Retrieval(NAMES),
        # Measured 2026-10-06: within noise of names. It finds concept-to-tool links names can't, but its
        # shortlists fill to 5 and break refusals. Kept for later measurement; size and floor not tuned.
        Retrieval(expand.STEP, expansion=expand.STEP, size=5, floor=0.75),
    )
}


def embed_choices(installed) -> list[str]:
    """Names of installed models (enrich.ollama.ModelInfo) that can produce embeddings."""
    return [m.name for m in installed if m.embeds]


def resolve_embed_model(chosen: str | None, choices: list[str]) -> str | None:
    """The chosen embedding model if it is installed; with none chosen, an installed nomic-embed-text."""
    if chosen:
        return chosen if chosen in choices else None
    return next((name for name in choices if name.split(":")[0] == DEFAULT_EMBED_MODEL), None)


def embed_model(conn: Connection, client) -> str | None:
    """The embedding model link judging uses now, or None while none is chosen or installed (judging waits).
    Raises Unreachable when the server can't be asked."""
    return resolve_embed_model(get_setting(conn, "llm.embed_model"), embed_choices(client.models()))


# --- Vectors ---


def pack(vector: list[float]) -> bytes:
    """Little-endian float32, the same bytes on every platform and database."""
    return struct.pack(f"<{len(vector)}f", *vector)


def unpack(data: bytes) -> list[float]:
    return list(struct.unpack(f"<{len(data) // 4}f", data))


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def unit(vector: list[float]) -> list[float]:
    """The vector scaled to length 1, so a cosine is one dot product."""
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector] if norm else vector


def dot(a: list[float], b: list[float]) -> float:
    return sum(map(operator.mul, a, b))


def embed_text(model: str, name: str) -> str:
    return EMBED_PREFIXES.get(model.split(":")[0], "") + name


def stored_vectors(conn: Connection, model: str) -> dict[str, list[float]]:
    return {
        row.text_key: unpack(row.vector)
        for row in conn.execute(select(skill_embeddings).where(skill_embeddings.c.model == model))
    }


@dataclass(frozen=True)
class Candidate:
    skill_id: int
    name: str
    similarity: float
    pair: tuple[str, str] | None = None  # (posting phrase, profile phrase) giving the similarity, when expanded


def rank(phrases: list[tuple[str, list[float]]], profile: list[tuple], pairs: bool = False) -> list[Candidate]:
    """Every profile skill ((row, [(phrase, unit vector)]) pairs) by similarity to a posting skill's phrases
    ((phrase, unit vector) pairs), most similar first: the similarity of the most similar pair of phrases.
    `pairs` records that pair on each candidate."""
    scored = []
    for row, theirs in profile:
        best, pair = -2.0, None
        for mine, a in phrases:
            for their, b in theirs:
                similarity = dot(a, b)
                if similarity > best:
                    best, pair = similarity, (mine, their)
        scored.append(Candidate(row.id, row.name, round(best, 4), pair if pairs else None))
    return sorted(scored, key=lambda c: (-c.similarity, c.name))


def cut(ranked: list[Candidate], size: int, floor: float) -> list[Candidate]:
    """The shortlist: at most `size` of the ranked candidates, at or above `floor`."""
    return [c for c in ranked if c.similarity >= floor][:size]


def shortlist(vector: list[float], profile: list[tuple], size: int | None = None, floor: float | None = None):
    """The most similar profile skills ((row, vector) pairs) to one vector, by bare names (SHORTLIST_K and
    SHORTLIST_FLOOR unless given)."""
    ranked = rank([("", unit(vector))], [(row, [("", unit(v))]) for row, v in profile])
    return cut(ranked, SHORTLIST_K if size is None else size, SHORTLIST_FLOOR if floor is None else floor)


# --- Phrases ---


def context_quotes(conn: Connection) -> dict[int, str]:
    """skill id -> its expansion context quote (queries.expansion_contexts), shown in judging requests too."""
    from ..queries import expansion_contexts

    return {skill_id: quote for skill_id, (_, quote) in expansion_contexts(conn).items()}


CONTEXT_CHARS = 200


def around(line: str, quote: str, limit: int = CONTEXT_CHARS) -> str:
    """The line, cut to `limit` characters around the quote's first occurrence (from the start when it isn't
    found), with "…" where text was cut."""
    line = " ".join(line.split())
    if len(line) <= limit:
        return line
    at = line.lower().find(quote.lower())
    start = 0 if at < 0 else max(0, min(at - (limit - len(quote)) // 2, len(line) - limit))
    cut = line[start:start + limit]
    return ("…" if start > 0 else "") + cut + ("…" if start + limit < len(line) else "")


def context_lines(conn: Connection) -> dict[int, str]:
    """skill id -> the CV line its context quote was found in (queries.context_lines), cut around the quote."""
    from ..queries import context_lines as lines

    return {skill_id: around(line, quote) for skill_id, (quote, line) in lines(conn).items()}


def judge_contexts(conn: Connection, judge) -> dict[int, str]:
    """skill id -> the CV context the judge shows beside each profile skill: its quote, or the quote's line."""
    return context_lines(conn) if judge.context == "line" else context_quotes(conn)


def phrases(conn: Connection, retrieval: Retrieval, posting: list[dict], profile: list,
            quotes: dict[int, str] | None = None) -> tuple[dict[str, list[str]], dict[int, list[str]]]:
    """(posting key -> phrases, profile skill id -> phrases): the name first, then the phrasings of the skill's
    usable expansion when the method expands (none when it has none). `quotes` defaults to context_quotes."""
    posting_out = {k["key"]: [k["name"]] for k in posting}
    profile_out = {s.id: [s.name] for s in profile}
    if retrieval.expands:
        quotes = context_quotes(conn) if quotes is None else quotes
        for key, more in expand.posting_expansions(conn, retrieval.expansion).items():
            if key in posting_out:
                posting_out[key] += more
        by_key = {s.key: s.id for s in profile}
        contexts = {s.key: quotes.get(s.id) for s in profile}
        for key, more in expand.profile_expansions(conn, contexts, retrieval.expansion).items():
            profile_out[by_key[key]] += more
    return posting_out, profile_out


def phrase_vectors(texts: list[str], vectors: dict[str, list[float]]) -> list[tuple[str, list[float]]] | None:
    """(phrase, unit vector) for each phrase with a stored vector; None when the first (the name) has none."""
    if name_key(texts[0]) not in vectors:
        return None
    return [(t, unit(vectors[name_key(t)])) for t in texts if name_key(t) in vectors]


def ranked(conn: Connection, embed_model: str, retrieval: Retrieval, posting: list[dict], profile: list,
           quotes: dict[int, str] | None = None) -> dict[str, list[Candidate]]:
    """posting key -> every profile skill ranked by similarity (see `rank`). Keys, and profile skills, whose
    name has no stored vector yet are left out."""
    vectors = stored_vectors(conn, embed_model)
    posting_phrases, profile_phrases = phrases(conn, retrieval, posting, profile, quotes)
    theirs = [(s, pv) for s in profile if (pv := phrase_vectors(profile_phrases[s.id], vectors)) is not None]
    out = {}
    for k in posting:
        mine = phrase_vectors(posting_phrases[k["key"]], vectors)
        if mine is not None:
            out[k["key"]] = rank(mine, theirs, pairs=retrieval.expands)
    return out


# --- What to judge ---


@dataclass(frozen=True)
class Planned:
    key: str
    name: str
    quote: str | None
    candidates: list[Candidate]


def _judged_keys(conn: Connection) -> tuple[list[dict], list, set[str]]:
    """(posting skill keys that may need judging, profile skills, the keys they cover: their own and their
    aliases')."""
    from ..queries import posting_skill_keys, profile_skills, same_identity

    profile = profile_skills(conn)
    if not profile:
        return [], [], set()
    profile_keys = set(same_identity(conn, profile))
    overridden = set(conn.execute(select(skill_link_overrides.c.posting_key)).scalars())
    keys = [k for k in posting_skill_keys(conn) if k["key"] not in profile_keys and k["key"] not in overridden]
    return keys, profile, profile_keys


def texts_to_embed(conn: Connection, model: str, retrieval: Retrieval | None = None,
                   posting: list[dict] | None = None, profile: list | None = None) -> dict[str, str]:
    """text key -> phrase for every phrase without a stored vector, of the posting skills that may be judged
    (or `posting`) and the profile skills (or `profile`), under the method (default: the current one)."""
    retrieval = retrieval or RETRIEVALS[CURRENT_RETRIEVAL]
    if posting is None or profile is None:
        keys, all_profile, _ = _judged_keys(conn)
        posting = keys if posting is None else posting
        profile = all_profile if profile is None else profile
    have = set(conn.execute(select(skill_embeddings.c.text_key).where(skill_embeddings.c.model == model)).scalars())
    posting_phrases, profile_phrases = phrases(conn, retrieval, posting, profile)
    wanted: dict[str, str] = {}
    for texts in [*posting_phrases.values(), *profile_phrases.values()]:
        for text in texts:
            wanted.setdefault(name_key(text), text)
    return {key: text for key, text in wanted.items() if key not in have}


def latest_judgments(conn: Connection, keys=None) -> dict[str, object]:
    """The newest succeeded judgment of each posting key."""
    newest = select(func.max(link_judgments.c.id)).where(link_judgments.c.status == "succeeded")
    if keys is not None:
        newest = newest.where(link_judgments.c.posting_key.in_(list(keys)))
    newest = newest.group_by(link_judgments.c.posting_key)
    return {
        row.posting_key: row
        for row in conn.execute(select(link_judgments).where(link_judgments.c.id.in_(newest)))
    }


def plan(conn: Connection, embed_model: str, everything: bool = False) -> list[Planned]:
    """The posting skills to judge with the current method, each with its current shortlist: those with no
    override and no same-key profile skill that have never been judged, or whose candidate set, embedding model
    or linking method differs from their latest judgment's (`everything`: all of them). A key whose name has
    no stored vector yet is left for later."""
    keys, profile, _ = _judged_keys(conn)
    if not keys:
        return []
    retrieval = RETRIEVALS[CURRENT_RETRIEVAL]
    size, floor = retrieval.limits()
    by_key = ranked(conn, embed_model, retrieval, keys, profile)
    latest = latest_judgments(conn, [k["key"] for k in keys])
    out = []
    for k in keys:
        if k["key"] not in by_key:
            continue
        candidates = cut(by_key[k["key"]], size, floor)
        previous = latest.get(k["key"])
        if not everything and previous is not None and previous.embed_model == embed_model and (
            previous.pipeline == PIPELINE
        ) and {c["skill_id"] for c in json.loads(previous.candidates_json)} == {c.skill_id for c in candidates}:
            continue
        out.append(Planned(k["key"], k["name"], k["quote"], candidates))
    return out


def outdated(conn: Connection) -> bool:
    """True when some posting skill's latest judgment was made by another linking method than the current one."""
    keys, _, _ = _judged_keys(conn)
    return any(j.pipeline != PIPELINE for j in latest_judgments(conn, [k["key"] for k in keys]).values())


# --- link-judge ---

JUDGE_RELATIONS = LINK_RELATIONS + ("none",)
JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "candidate": {"type": "integer"},
                    "relation": {"type": "string", "enum": list(JUDGE_RELATIONS)},
                },
                "required": ["candidate", "relation"],
            },
        }
    },
    "required": ["relations"],
}

# @5: @2 (a stricter "same", weaker relation when in doubt, examples of "none") with its two examples replaced: both
# were among the reference links it is measured against, so that measurement wasn't fair. Current since 2026-10-06:
# within noise of @2 (4 links lost, p=0.06), whose figures those examples flattered. @2, @3 (a looser "none") and
# @4 (one request per candidate) were measured and deleted; their figures are in improve-skill-linking's design.
JUDGE_SYSTEM = """You compare one skill a job posting asks for with skills on a person's CV, to decide whether the
person has the posting's skill.
For each numbered CV skill, choose how it relates to the posting's skill:
- "same": the two names mean exactly the same skill, so a recruiter screening for the posting's skill would count
  the CV skill as that skill (for example "LLMs" and "Large language models", "JS" and "JavaScript"). A skill used
  in the same work, a part of it, a tool for it or an approach to it is not "same".
- "specific": the CV skill is one particular form, tool or instance of the posting's skill, so having it shows the
  posting's skill (for example "GitHub Actions" for "CI/CD", "PostgreSQL" for "Relational databases").
- "general": the CV skill is a broader skill that includes the posting's skill, but having it doesn't show the
  posting's skill (for example "LLM fine-tuning" for "LoRA", "Machine learning" for "Gradient boosting").
- "related": a different skill in the same area that gives a real head start on the posting's skill (for example
  "Docker" for "Kubernetes", "Vue.js" for "React").
- "none": anything else, including skills that only share a word or a broad field (for example "Computer science"
  for "Data science", "Spreadsheets" for "Data engineering", "Assessment design" for "Model evaluation").
Judge each CV skill on its own: most are "none". When two relations seem possible, choose the weaker one
(same, then specific, then general, then related, then none, from strongest to weakest).
Answer with JSON: {"relations": [{"candidate": <number>, "relation": "..."}]}."""


class LinkJudge:
    """One request per posting skill, with its shortlisted profile skills numbered. `context` is what is shown
    beside each profile skill: "quote" (its evidence quote) or "line" (the CV line the quote was found in)."""

    name = NAME

    def __init__(self, version: int, system: str, context: str = "quote"):
        self.version = version
        self.system = system
        self.context = context
        self.id = f"{NAME}@{version}"

    def request(self, item: Planned, quotes: dict[int, str]) -> str:
        lines = [f"Posting skill: {item.name}"]
        if item.quote:
            lines.append(f'In the posting: "{item.quote}"')
        lines.append("")
        lines.append("CV skills:")
        for n, c in enumerate(item.candidates, start=1):
            quote = quotes.get(c.skill_id)
            lines.append(f'{n}: {c.name}' + (f' (on the CV: "{quote}")' if quote else ""))
        return "\n".join(lines)

    def judge(self, item: Planned, quotes: dict[int, str], llm: LLM) -> dict[int, str]:
        """skill_id -> relation for every candidate; candidates the model leaves out are 'none'."""
        response = conform("link", llm.chat_json(self.system, self.request(item, quotes), JUDGE_SCHEMA), JUDGE_SCHEMA)
        out = {c.skill_id: "none" for c in item.candidates}
        for answer in response["relations"]:
            if 1 <= answer["candidate"] <= len(item.candidates):
                out[item.candidates[answer["candidate"] - 1].skill_id] = answer["relation"]
        return out


# @6: @5, with each profile skill shown beside the CV line its evidence quote was found in instead of the quote
# alone (most quotes are only the skill's name), and told how to read that line. Measured 2026-10-06: within noise
# of @5; kept for later measurement.
JUDGE_SYSTEM_V6 = JUDGE_SYSTEM.replace(
    "Judge each CV skill on its own:",
    "Each CV skill comes with the CV line it was found in. Use the line to see what the person did with that skill, "
    "but judge the CV skill named, not other skills on the same line.\nJudge each CV skill on its own:",
)

JUDGES = {j.id: j for j in (LinkJudge(5, JUDGE_SYSTEM), LinkJudge(6, JUDGE_SYSTEM_V6, context="line"))}


# --- The app's linking method ---

CURRENT_RETRIEVAL = NAMES
CURRENT_JUDGE = "link-judge@5"


def pipeline_for(retrieval: str, judge: str) -> str:
    """A linking method's pipeline id, as judgments record it: the expansion step, when it expands, and the
    judge."""
    r = RETRIEVALS[retrieval]
    parts = [f"expand={r.expansion}"] if r.expands else []
    return " ".join([*parts, f"links={judge}"])


def judge_of(pipeline: str) -> str | None:
    """The judging version a pipeline id names ('links=link-judge@2' -> 'link-judge@2')."""
    return next((part.removeprefix("links=") for part in pipeline.split() if part.startswith("links=")), None)


PIPELINE = pipeline_for(CURRENT_RETRIEVAL, CURRENT_JUDGE)
JUDGE = JUDGES[CURRENT_JUDGE]


# --- The judging loop of a links job ---


@dataclass
class Pass:
    planned: int = 0
    judged: int = 0
    failed: int = 0
    requests: int = 0
    expanded: int = 0
    expand_failed: int = 0


def judge_links(
    engine: Engine, client, model: str, num_ctx: int, embed: str, everything: bool = False,
    should_stop: Callable[[], bool] = lambda: False,
) -> Pass:
    """Expand what the current method needs (when it expands), embed what has no vector yet, plan, then judge
    key by key. Each expansion and judgment is stored in its own transaction, so a cancelled or interrupted pass
    keeps what it finished. Model calls happen outside transactions. Raises Cancelled (between requests),
    Unreachable, and StepFailed when embedding fails (nothing embedded is stored)."""
    from ..queries import expansion_contexts
    from . import derived

    result = Pass()
    if RETRIEVALS[CURRENT_RETRIEVAL].expands:
        with engine.connect() as conn:
            keys, profile, _ = _judged_keys(conn)
            step = RETRIEVALS[CURRENT_RETRIEVAL].expansion
            wanted = expand.missing(conn, keys, profile, expansion_contexts(conn), step) if profile else []
        if wanted:
            expanded = expand.expand_all(engine, client.for_model(model, num_ctx), model, wanted, should_stop)
            result.expanded, result.expand_failed = expanded.succeeded, expanded.failed
    with engine.connect() as conn:
        missing = texts_to_embed(conn, embed)
    if missing:
        vectors = client.embed(embed, [embed_text(embed, name) for name in missing.values()])
        with engine.begin() as conn:
            derived.save_embeddings(conn, embed, dict(zip(missing, vectors, strict=True)))
    with engine.connect() as conn:
        planned = plan(conn, embed, everything)
        quotes = judge_contexts(conn, JUDGE)
    result.planned = len(planned)
    llm = client.for_model(model, num_ctx) if any(p.candidates for p in planned) else None
    for item in planned:
        if should_stop():
            raise Cancelled()
        relations, status, error, output = {}, "succeeded", None, {}
        if item.candidates:
            try:
                relations = JUDGE.judge(item, quotes, llm)
                output = {"relations": relations}
            except StepFailed as exc:
                status, error = "failed", f"{exc.step or 'link'}: {exc.message}"
                result.failed += 1
            result.requests += 1
        with engine.begin() as conn:
            derived.save_judgment(conn, item, model, embed, PIPELINE, status, error, relations, output)
        result.judged += status == "succeeded"
    return result
