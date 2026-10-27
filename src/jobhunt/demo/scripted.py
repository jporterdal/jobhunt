"""Scripted stand-ins for the Ollama client: deterministic embeddings, and the demo's chat answers.

`ScriptedClient` has the client interface the job queue uses (for_model, chat_json, embed, models, version) and
answers from persona.py, so the demo's runs go through the real pipeline steps, validation and storage without a
model server or any network access.
"""

from __future__ import annotations

import re
import zlib

from ..enrich.ollama import ModelInfo
from ..userdata import name_key
from . import persona

TRIGRAM_DIMENSIONS = 512

CHAT_MODEL = "demo-scripted"
EMBED_MODEL = "demo-trigram"


def trigram_vector(text: str) -> list[float]:
    """Character-trigram counts hashed into a fixed number of dimensions: names sharing letters are similar.
    A task prefix ("clustering: ") is left out, as a real model would weigh it little."""
    if text.startswith("clustering: "):
        text = text[len("clustering: "):]
    padded = f"  {text.casefold()} "
    vector = [0.0] * TRIGRAM_DIMENSIONS
    for i in range(len(padded) - 2):
        vector[zlib.crc32(padded[i:i + 3].encode()) % TRIGRAM_DIMENSIONS] += 1.0
    return vector


_NUMBERED = re.compile(r"^(\d+): (.*)$")
_TERMS = re.compile(
    "|".join(rf"(?<!\w){re.escape(term)}(?!\w)" for term in sorted(persona.SKILL_TERMS, key=len, reverse=True)),
    re.IGNORECASE,
)
_TERM_BY_KEY = {term.casefold(): value for term, value in persona.SKILL_TERMS.items()}
_PAY = re.compile(r"\$(\d[\d,]*)–\$(\d[\d,]*) ([A-Z]{3}) per year")
_POSTING_SKILL = re.compile(r"^Posting skill: (.*)$", re.MULTILINE)
_CANDIDATE = re.compile(r"^(\d+): (.*?)(?: \(on the CV: .*\))?$", re.MULTILINE)


def numbered(user: str) -> list[tuple[int, str]]:
    return [(int(m.group(1)), m.group(2)) for m in map(_NUMBERED.match, user.splitlines()) if m]


def label_lines(user: str) -> dict:
    """llm-lines: lines under a heading take its label (persona.SECTIONS); headings themselves are other."""
    out, section = [], "other"
    for number, text in numbered(user):
        if text in persona.SECTIONS:
            section = persona.SECTIONS[text]
        elif section != "other":
            out.append({"line": number, "label": section})
    return {"lines": out}


def find_skills(user: str) -> dict:
    """atomic: every skill term each line names, quoted as written."""
    out = []
    for number, text in numbered(user):
        for match in _TERMS.finditer(text):
            name, kind = _TERM_BY_KEY[match.group().casefold()]
            out.append({"line": number, "name": name, "kind": kind, "quote": match.group()})
    return {"skills": out}


def read_pay(user: str) -> dict:
    """paylines: the demo's one pay line format, "$95,000–$112,000 CAD per year"."""
    out = []
    for match in _PAY.finditer(user):
        low, high, currency = match.groups()
        out.append({"min": float(low.replace(",", "")), "max": float(high.replace(",", "")), "currency": currency,
                    "period": "year", "location": None, "basis": "base", "quote": match.group()})
    return {"ranges": out}


def judge(user: str) -> dict:
    """link-judge: each numbered CV skill's relation from persona.RELATIONS; pairs not listed are none."""
    posting = name_key(_POSTING_SKILL.search(user).group(1))
    candidates = _CANDIDATE.findall(user.split("CV skills:", 1)[1])
    return {"relations": [
        {"candidate": int(number), "relation": persona.RELATIONS.get((posting, name_key(name)), "none")}
        for number, name in candidates
    ]}


ANSWERS = {"lines": label_lines, "skills": find_skills, "ranges": read_pay, "relations": judge}


class ScriptedClient:
    """The Ollama client's interface, answered from the persona. Any other request is a bug in the demo."""

    def __init__(self):
        self.num_ctx = 8192
        self.model: str | None = None

    def for_model(self, model: str, num_ctx: int) -> ScriptedClient:
        self.model, self.num_ctx = model, num_ctx
        return self

    def chat_json(self, system: str, user: str, schema: dict) -> dict:
        key = schema["required"][0]
        if key not in ANSWERS:
            raise ValueError(f"the demo has no scripted answer for {key!r} requests")
        return ANSWERS[key](user)

    def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        return [trigram_vector(t) for t in texts]

    def models(self) -> list[ModelInfo]:
        return [
            ModelInfo(CHAT_MODEL, "scripted", 0, ("completion",)),
            ModelInfo(EMBED_MODEL, "scripted", 0, ("embedding",)),
        ]

    def version(self) -> str:
        return "demo"
