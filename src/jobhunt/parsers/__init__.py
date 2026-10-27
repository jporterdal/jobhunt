"""The parser plug-in point: what a parser is given and returns, and loading the installed parsers.

Installed packages register parsers under the `jobhunt.parsers` entry-point group, as an object or a class
taking no arguments. The app's own parsers are registered the same way (see pyproject.toml). Entry points come
from installed metadata, so a changed registration takes effect only after `pip install -e .` again.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from importlib.metadata import EntryPoint, entry_points
from pathlib import Path
from typing import Protocol, runtime_checkable

GROUP = "jobhunt.parsers"

# A detail's value: text, a number, true or false, a list of text, or null (absent).
Value = str | int | float | bool | list[str] | None


@dataclass(frozen=True)
class CaptureFile:
    """What a parser is given. `path` is for its name and for companions; parsers must not read other files."""

    path: Path
    raw: bytes
    modified_at: datetime  # the file's mtime, UTC


@dataclass(frozen=True)
class ParsedPosting:
    source: str  # lowercase letters, digits, dots and hyphens; a website's host without "www."
    external_id: str
    url: str
    title: str
    company: str
    description_html: str  # sanitized again by the store
    description_text: str | None = None  # derived from the sanitized HTML when None
    location: str | None = None
    workplace_type: str | None = None
    employment_type: str | None = None
    posted_on: date | None = None
    posted_precision: str | None = None
    captured_at: datetime | None = None  # else the file's modification time
    details: Mapping[str, Value] = field(default_factory=dict)  # compared between captures
    volatile_details: Mapping[str, Value] = field(default_factory=dict)  # stored, not compared
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class Rejected:
    """The file comes from the parser's origin but can't be used."""

    reason: str


@runtime_checkable
class Parser(Protocol):
    name: str  # e.g. "posting-file"
    version: str  # recorded as "name@version"

    def parse(self, file: CaptureFile) -> ParsedPosting | Rejected | None:
        """A posting, a rejection, or None when the file isn't recognised."""
        ...

    # Optional: `companions(path) -> list[Path]`, the files that belong to `path` and move with it.


def label(parser: Parser) -> str:
    return f"{parser.name}@{parser.version}"


def companions(parser: Parser, path: Path) -> list[Path]:
    """The companions a parser names for `path` (none when it has no `companions`)."""
    method = getattr(parser, "companions", None)
    return list(method(path)) if method is not None else []


@dataclass(frozen=True)
class Installed:
    parsers: tuple[Parser, ...]  # sorted by name
    errors: tuple[str, ...] = ()  # entry points that failed to load, or clashing names


def load(points: Iterable[EntryPoint]) -> Installed:
    """Load each entry point; a failure is reported, and the rest still load. A name used twice loads neither."""
    loaded: list[Parser] = []
    errors: list[str] = []
    for point in points:
        try:
            obj = point.load()
            parser = obj() if isinstance(obj, type) else obj
            if not (isinstance(getattr(parser, "name", None), str) and isinstance(getattr(parser, "version", None), str)
                    and callable(getattr(parser, "parse", None))):
                raise TypeError("not a parser (needs name, version and parse)")
        except Exception as error:  # a broken plug-in must not stop the import
            errors.append(f"parser {point.name!r} ({point.value}) failed to load: {type(error).__name__}: {error}")
            continue
        loaded.append(parser)

    names = [p.name for p in loaded]
    clashes = sorted({n for n in names if names.count(n) > 1})
    for name in clashes:
        errors.append(f"several installed parsers are named {name!r}; none of them is used")
    parsers = sorted((p for p in loaded if p.name not in clashes), key=lambda p: p.name)
    return Installed(tuple(parsers), tuple(errors))


def installed() -> Installed:
    """The parsers registered by installed packages."""
    return load(entry_points(group=GROUP))
