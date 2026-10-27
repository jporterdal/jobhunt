"""Skill expansion: alternative phrasings of a skill's name, so link candidates are found by meaning rather than
by spelling ("Claude Code" -> "AI coding agent"). derived.py stores what this module produces.

A posting skill is expanded once per step version, with one quote from a posting that asks for it. A profile
skill is expanded once per step version and expansion context (queries.expansion_contexts). A failed expansion
is not used: the skill is compared by its name alone, and the next links job asks again.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.engine import Connection, Engine

from ..db import skill_expansions
from ..userdata import collapse, name_key
from .pipeline import LLM, Cancelled, StepFailed, conform

NAME = "skill-expand"
VERSION = 1
STEP = f"{NAME}@{VERSION}"

MAX_PHRASES = 6
MAX_WORDS = 8

SCHEMA = {
    "type": "object",
    "properties": {"phrases": {"type": "array", "items": {"type": "string"}}},
    "required": ["phrases"],
}

SYSTEM = """You write other ways of naming one skill, so the same skill can be recognised when a CV or a job
posting names it differently.
Give up to six phrasings, each at most eight words:
- synonyms and other common names for the same skill
- the expanded form of an abbreviation, or the usual abbreviation of a long name
- the usual name of the tool, practice or discipline the skill is
- one short description that says what kind of skill it is (for example "AI coding agent" for "Claude Code",
  "container orchestration" for "Kubernetes", "relational database querying" for "SQL").
Read the context to decide what an ambiguous name means, and describe that meaning.
Every phrasing must name the skill itself. Don't list broader skills it is part of, narrower skills, related tools
or skills often used with it.
Answer with JSON: {"phrases": ["...", "..."]}."""


def clean(name: str, phrases: list[str]) -> list[str]:
    """Trimmed phrasings without ones of the same identity as the name or an earlier phrasing, without ones over
    MAX_WORDS words, at most MAX_PHRASES."""
    seen = {name_key(name)}
    out = []
    for phrase in phrases:
        phrase = collapse(phrase)
        key = name_key(phrase)
        if not key or key in seen or len(phrase.split()) > MAX_WORDS:
            continue
        seen.add(key)
        out.append(phrase)
        if len(out) == MAX_PHRASES:
            break
    return out


class SkillExpander:
    """One request per skill, with its context quote when it has one."""

    name = NAME
    version = VERSION

    def expand(self, side: str, name: str, context: str | None, llm: LLM) -> tuple[list[str], dict]:
        """(cleaned phrasings, the raw response). Raises StepFailed when the response doesn't fit the schema."""
        lines = [f"Skill: {name}"]
        if context:
            lines.append(("In the posting" if side == "posting" else "On the CV") + f': "{context}"')
        response = conform("expand", llm.chat_json(SYSTEM, "\n".join(lines), SCHEMA), SCHEMA)
        return clean(name, response["phrases"]), response


EXPANDER = SkillExpander()


# --- Stored expansions ---


def posting_expansions(conn: Connection, step: str = STEP) -> dict[str, list[str]]:
    """posting skill key -> the phrasings of its newest succeeded expansion at the step, whatever its context."""
    out: dict[str, list[str]] = {}
    for row in conn.execute(
        select(skill_expansions.c.skill_key, skill_expansions.c.phrases_json)
        .where(skill_expansions.c.side == "posting", skill_expansions.c.step == step,
               skill_expansions.c.status == "succeeded")
        .order_by(skill_expansions.c.id)
    ):
        out[row.skill_key] = json.loads(row.phrases_json)
    return out


def profile_expansions(conn: Connection, contexts: dict[str, str | None], step: str = STEP) -> dict[str, list[str]]:
    """profile skill key -> the phrasings of its newest succeeded expansion at the step made for its current
    context (`contexts`: key -> quote or None). Keys without one are left out."""
    out: dict[str, list[str]] = {}
    for row in conn.execute(
        select(skill_expansions.c.skill_key, skill_expansions.c.context, skill_expansions.c.phrases_json)
        .where(skill_expansions.c.side == "profile", skill_expansions.c.step == step,
               skill_expansions.c.status == "succeeded")
        .order_by(skill_expansions.c.id)
    ):
        if row.skill_key in contexts and contexts[row.skill_key] == row.context:
            out[row.skill_key] = json.loads(row.phrases_json)
    return out


@dataclass(frozen=True)
class Wanted:
    side: str  # 'posting' or 'profile'
    key: str
    name: str
    context: str | None


def missing(conn: Connection, posting: list[dict], profile: list, contexts: dict[int, tuple[int, str]],
            step: str = STEP) -> list[Wanted]:
    """The expansions to request: posting skills (posting_skill_keys dicts) and profile skills (rows) with no
    succeeded expansion at the step (for a profile skill: for its current context)."""
    have_posting = posting_expansions(conn, step)
    profile_contexts = {s.key: contexts[s.id][1] if s.id in contexts else None for s in profile}
    have_profile = profile_expansions(conn, profile_contexts, step)
    out = [Wanted("profile", s.key, s.name, profile_contexts[s.key]) for s in profile if s.key not in have_profile]
    out += [Wanted("posting", k["key"], k["name"], k["quote"]) for k in posting if k["key"] not in have_posting]
    return out


@dataclass
class Expanded:
    succeeded: int = 0
    failed: int = 0


def expand_all(engine: Engine, llm: LLM, model: str, wanted: list[Wanted],
               should_stop: Callable[[], bool] = lambda: False) -> Expanded:
    """Request each expansion, each stored in its own transaction so an interrupted pass keeps what it finished.
    Model calls happen outside transactions. Raises Cancelled (between requests) and Unreachable."""
    from . import derived

    result = Expanded()
    for item in wanted:
        if should_stop():
            raise Cancelled()
        phrases, status, error, output = [], "succeeded", None, {}
        try:
            phrases, output = EXPANDER.expand(item.side, item.name, item.context, llm)
        except StepFailed as exc:
            status, error = "failed", f"{exc.step or 'expand'}: {exc.message}"
        with engine.begin() as conn:
            derived.save_expansion(conn, item, STEP, model, status, error, phrases, output)
        if status == "succeeded":
            result.succeeded += 1
        else:
            result.failed += 1
    return result
