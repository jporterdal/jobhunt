"""Skill extractors: turn the required and preferred segments into atomic skills."""

from __future__ import annotations

from .pipeline import IMPORTANCES, LLM, SKILL_KINDS, Segment, SkillItem, StepFailed, conform

SKILLS_SCHEMA = {
    "type": "object",
    "properties": {
        "skills": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "line": {"type": "integer"},
                    "name": {"type": "string"},
                    "kind": {"type": "string", "enum": list(SKILL_KINDS)},
                    "quote": {"type": "string"},
                },
                "required": ["line", "name", "kind", "quote"],
            },
        }
    },
    "required": ["skills"],
}

# atomic@2: the prompt from before tighten-skill-definition.
SKILLS_SYSTEM_V2 = """You extract skills from lines of a job posting.
List every skill the numbered lines ask for, or that the work they describe uses, one skill per entry.
A skill is one of:
- a technology, tool, platform, language or method
- a soft skill that names a capability (for example communication, stakeholder management, technical leadership)
- a call for an advanced degree
Do not list:
- personality traits (for example adaptability, independence, comfort with ambiguity)
- industries or subject domains (for example fintech, insurance, genomics)
- fields of study
- words that name no skill on their own (for example "trends", "systems")
Split lists: "Python, Spark and MLflow" is three skills.
Name an advanced degree by its level only: "PhD", "Master's degree", or "Advanced degree" when no level is stated.
When several levels qualify, use the lowest. Leave the field of study in the quote.
- "name": the skill's usual short name, 1 to 4 words (for example "Python", "Machine learning", "Stakeholder management").
- "kind": "technical" for technologies, tools, platforms, languages and methods; "soft" for capabilities in working
  with people; "qualification" for degrees.
- "line": the number of the line the skill comes from.
- "quote": the shortest exact text from that line that names the skill, copied character for character.
Answer with JSON: {"skills": [{"line": <number>, "name": "...", "kind": "...", "quote": "..."}]}."""

EMPTY_REMINDER_V2 = (
    "\n\nThese lines come from the {group} section of a job posting, so they ask for at least one skill, "
    "or describe work that uses at least one. List every skill they name."
)


class AtomicExtractor:
    """One call per non-empty group; importance comes from the group, never from the model.

    Each version is its own instance with its own prompt, so a candidate can be registered beside the app's version.
    """

    name = "atomic"

    def __init__(self, version: int, system: str, reminder: str):
        self.version = version
        self.system = system
        self.reminder = reminder

    def extract(self, text: str, segments: list[Segment], llm: LLM) -> list[SkillItem]:
        items: list[SkillItem] = []
        for group in IMPORTANCES:
            spans = [(s.start, s.end) for s in segments if s.label == group]
            if not spans:
                continue
            user = "\n".join(f"{n}: {text[s:e]}" for n, (s, e) in enumerate(spans, start=1))
            found = self._ask(llm, user, spans, group)
            if not found:
                found = self._ask(llm, user + self.reminder.format(group=group), spans, group)
            if not found:
                raise StepFailed("skills", f"no skills were extracted from the {group} lines")
            items.extend(found)
        return items

    def _ask(self, llm: LLM, user: str, spans: list[tuple[int, int]], group: str) -> list[SkillItem]:
        response = conform("skills", llm.chat_json(self.system, user, SKILLS_SCHEMA), SKILLS_SCHEMA)
        out = []
        for entry in response["skills"]:
            name = " ".join(entry["name"].split())
            if not name:
                continue
            line = entry["line"]
            source = spans[line - 1] if 1 <= line <= len(spans) else None
            out.append(SkillItem(name, group, entry["kind"], entry["quote"].strip(), source))
        return out


# atomic@2 is the app's method (pipeline.CURRENT_SKILLS). At most one candidate version sits beside it while
# `jobhunt eval --skills` measures it; a candidate that isn't adopted is deleted.
ATOMIC_V2 = AtomicExtractor(2, SKILLS_SYSTEM_V2, EMPTY_REMINDER_V2)

EXTRACTORS = (ATOMIC_V2,)
