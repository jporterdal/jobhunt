"""Pipeline contracts, the step registry and run_pipeline. No database, no HTTP.

A segment is a pair of character offsets into the snapshot's description_text, so no step can rewrite
the text: quotes stay checkable and marks stay highlightable.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

LABELS = ("required", "preferred", "other")
IMPORTANCES = ("required", "preferred")
SKILL_KINDS = ("technical", "soft", "qualification")
SALARY_BASES = ("base", "ote", "unclear")
SALARY_PERIODS = ("year", "month", "biweekly", "week", "day", "hour", "unclear")


class StepFailed(Exception):
    """A step's error that is stored as a failed run. `step` is None when raised below the step (the client)."""

    def __init__(self, step: str | None, message: str):
        super().__init__(message)
        self.step = step
        self.message = message


class Cancelled(Exception):
    """should_stop() returned true between steps; nothing from the run is stored."""


class Unreachable(Exception):
    """The Ollama server could not be reached; queued work waits instead of failing."""


@dataclass(frozen=True)
class Segment:
    start: int
    end: int
    label: str  # one of LABELS


@dataclass(frozen=True)
class SkillItem:
    name: str
    importance: str  # from the segment group, never from the model
    kind: str
    quote: str
    source: tuple[int, int] | None = None  # span of the line the model cited; the quote is looked for there first


@dataclass(frozen=True)
class SalaryItem:
    min: float | None
    max: float | None
    currency: str
    period: str
    location: str | None
    basis: str
    quote: str


@dataclass(frozen=True)
class Checked:
    """An item after validation; offsets into the raw text are set only when verified."""

    item: SkillItem | SalaryItem
    verified: bool
    start: int | None = None
    end: int | None = None


class LLM(Protocol):
    num_ctx: int

    def chat_json(self, system: str, user: str, schema: dict) -> dict: ...


class Segmenter(Protocol):
    name: str
    version: int

    def segment(self, text: str, llm: LLM) -> list[Segment]: ...


class SkillExtractor(Protocol):
    name: str
    version: int

    def extract(self, text: str, segments: list[Segment], llm: LLM) -> list[SkillItem]: ...


class SalaryExtractor(Protocol):
    name: str
    version: int

    def extract(self, text: str, llm: LLM) -> list[SalaryItem]: ...


# --- Registry ---


def segmenters() -> dict[str, Segmenter]:
    from . import segment

    return {s.name: s for s in segment.SEGMENTERS}


def skill_extractors() -> dict[str, SkillExtractor]:
    """Keyed by name@version: several versions of one extractor can be registered side by side."""
    from . import skills

    return {f"{s.name}@{s.version}": s for s in skills.EXTRACTORS}


def salary_extractors() -> dict[str, SalaryExtractor]:
    from . import salary

    return {s.name: s for s in salary.EXTRACTORS}


# The app's skill extractor, named by the code (no setting). A registered candidate is for `jobhunt eval` only.
CURRENT_SKILLS = "atomic@2"
DEFAULT_SALARY = "paylines"


@dataclass(frozen=True)
class Steps:
    segmenter: Segmenter
    skills: SkillExtractor
    salary: SalaryExtractor


def steps_for(segmenter: str, skills: str = CURRENT_SKILLS) -> Steps:
    """The current steps with the chosen segmenter and a skill extractor (name@version; the app's by default)."""
    return Steps(segmenters()[segmenter], skill_extractors()[skills], salary_extractors()[DEFAULT_SALARY])


def pipeline_id(steps: Steps) -> str:
    """Canonical text naming every step and its version; equal text means comparable runs."""
    from . import validate

    return (
        f"seg={steps.segmenter.name}@{steps.segmenter.version} "
        f"skills={steps.skills.name}@{steps.skills.version} "
        f"salary={steps.salary.name}@{steps.salary.version} "
        f"validate={validate.NAME}@{validate.VERSION}"
    )


def steps_from_id(pipeline: str) -> Steps:
    """The steps a pipeline id names. Raises ValueError when this code no longer has one of them."""
    steps = None
    try:
        parts = dict(part.split("=", 1) for part in pipeline.split())
        steps = Steps(
            segmenters()[parts["seg"].split("@")[0]],
            skill_extractors()[parts["skills"]],
            salary_extractors()[parts["salary"].split("@")[0]],
        )
    except (KeyError, ValueError):
        pass
    if steps is None or pipeline_id(steps) != pipeline:
        raise ValueError(f"pipeline {pipeline!r} is not available in this version")
    return steps


# --- Model output checks ---


def conform(step: str, value: Any, schema: dict, path: str = "$") -> Any:
    """Check a parsed response against the subset of JSON Schema the steps use; StepFailed if it doesn't fit."""
    types = schema.get("type")
    if types is not None:
        allowed = types if isinstance(types, list) else [types]
        if not any(_is_type(value, t) for t in allowed):
            raise StepFailed(step, f"response does not match the schema: {path} is not {' or '.join(allowed)}")
    if "enum" in schema and value not in schema["enum"]:
        raise StepFailed(step, f"response does not match the schema: {path} is not one of {schema['enum']}")
    if isinstance(value, dict):
        for key in schema.get("required", ()):
            if key not in value:
                raise StepFailed(step, f"response does not match the schema: {path}.{key} is missing")
        for key, sub in schema.get("properties", {}).items():
            if key in value:
                conform(step, value[key], sub, f"{path}.{key}")
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            conform(step, item, schema["items"], f"{path}[{i}]")
    return value


def _is_type(value: Any, name: str) -> bool:
    if name == "object":
        return isinstance(value, dict)
    if name == "array":
        return isinstance(value, list)
    if name == "string":
        return isinstance(value, str)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "null":
        return value is None
    if name == "boolean":
        return isinstance(value, bool)
    return False


# --- Running ---


@dataclass
class RunResult:
    status: str  # 'succeeded' or 'failed'
    error: str | None
    started_at: datetime
    finished_at: datetime
    segments: list[Segment] = field(default_factory=list)
    skills: list[Checked] = field(default_factory=list)
    salaries: list[Checked] = field(default_factory=list)
    trace: dict = field(default_factory=dict)  # stored as output_json

    @property
    def seconds(self) -> float:
        return (self.finished_at - self.started_at).total_seconds()


@dataclass
class DocumentResult:
    """One document run. `suggestions` holds the verified suggestions by kind ('record', 'claim', 'part_of',
    'highlight'; None when the run failed); `trace` holds each step's calls and the unverified items."""

    status: str  # 'succeeded' or 'failed'
    error: str | None
    started_at: datetime
    finished_at: datetime
    suggestions: dict | None = None
    trace: dict = field(default_factory=dict)


class _Recorder:
    """Passes calls through to the model and keeps each response and its time for the step trace."""

    def __init__(self, llm: LLM):
        self._llm = llm
        self.num_ctx = llm.num_ctx
        self.calls: list[dict] = []

    def chat_json(self, system: str, user: str, schema: dict) -> dict:
        started = time.monotonic()
        response = self._llm.chat_json(system, user, schema)
        self.calls.append({"seconds": round(time.monotonic() - started, 3), "response": response})
        return response


def run_pipeline(
    text: str, llm: LLM, steps: Steps, should_stop: Callable[[], bool] = lambda: False
) -> RunResult:
    """Segment, extract skills and salary, then validate and merge duplicate skills. Raises Cancelled and
    Unreachable; a StepFailed becomes a failed result with no items."""
    from . import validate

    started_at = datetime.now(UTC)
    trace: dict = {"steps": []}
    segments: list[Segment] = []
    skill_items: list[SkillItem] = []
    salary_items: list[SalaryItem] = []
    current = "segment"

    def step(name: str, impl, fn):
        nonlocal current
        if should_stop():
            raise Cancelled()
        current = name
        recorder = _Recorder(llm)
        entry = {"step": name, "name": impl.name, "version": impl.version, "calls": recorder.calls}
        trace["steps"].append(entry)
        began = time.monotonic()
        try:
            return fn(recorder)
        finally:
            entry["seconds"] = round(time.monotonic() - began, 3)

    try:
        segments = step("segment", steps.segmenter, lambda m: steps.segmenter.segment(text, m))
        trace["segments"] = [[s.start, s.end, s.label] for s in segments]
        skill_items = step("skills", steps.skills, lambda m: steps.skills.extract(text, segments, m))
        salary_items = step("salary", steps.salary, lambda m: steps.salary.extract(text, m))
    except StepFailed as exc:
        error = f"{exc.step or current}: {exc.message}"
        trace["error"] = error
        return RunResult("failed", error, started_at, datetime.now(UTC), segments, trace=trace)

    if should_stop():
        raise Cancelled()
    checked = validate.check_skills(text, skill_items)
    skills = validate.merge_skills(checked)
    salaries = validate.check_salaries(text, salary_items)
    trace["items"] = {
        "skills": [asdict(c.item) | {"verified": c.verified} for c in checked],  # duplicates the merge dropped too
        "salaries": [asdict(c.item) | {"verified": c.verified} for c in salaries],
    }
    return RunResult(
        "succeeded", None, started_at, datetime.now(UTC), segments, skills, salaries, trace
    )
