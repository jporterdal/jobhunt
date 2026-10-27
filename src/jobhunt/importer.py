"""Import inbox files through the installed parsers: exactly one must accept a file, then it is stored and filed
away."""

from __future__ import annotations

import shutil
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.engine import Engine

from . import parsers as plugins
from .db import postings
from .parsers import CaptureFile, ParsedPosting, Parser, Rejected
from .store import InvalidPosting, find_capture, latest_snapshot, sha256_hex, store_capture

OUTCOMES = ("new", "updated", "unchanged", "duplicate", "rejected")
PROCESSED_DIR = "processed"
REJECTED_DIR = "rejected"
# The download metadata some systems keep beside a downloaded file; it belongs to no parser.
DOWNLOAD_METADATA = ":Zone.Identifier"


@dataclass
class FileResult:
    name: str
    outcome: str
    job_id: int | None = None
    source: str | None = None
    external_id: str | None = None
    title: str | None = None
    company: str | None = None
    url: str | None = None
    warnings: list[str] = field(default_factory=list)
    reason: str | None = None


def _existing(paths) -> list[Path]:
    """The paths that exist, each once, in order."""
    seen: list[Path] = []
    for p in paths:
        if p not in seen and p.exists():
            seen.append(p)
    return seen


def companions(path: Path, parsers: Sequence[Parser]) -> list[Path]:
    """The files that move with `path`: those the given parsers name, and its download metadata."""
    named = [c for p in parsers for c in plugins.companions(p, path)]
    return [c for c in _existing([*named, path.with_name(path.name + DOWNLOAD_METADATA)]) if c != path]


def discover(inbox: Path, parsers: Sequence[Parser]) -> list[Path]:
    """Files directly in the inbox, oldest first; subfolders and other files' companions are left out."""
    files = [p for p in inbox.iterdir() if p.is_file()]
    belonging = {c for f in files for c in companions(f, parsers)}
    return sorted((f for f in files if f not in belonging), key=lambda p: (p.stat().st_mtime, p.name))


def import_files(
    engine: Engine,
    paths: list[Path],
    inbox: Path | None = None,
    parsers: Sequence[Parser] | None = None,
    now: datetime | None = None,
) -> list[FileResult]:
    """Process each file in its own transaction. With `inbox`, move files out of it afterwards.

    `parsers` defaults to the installed ones (parsers.installed()); `now` is the import time (default: the clock).
    """
    if parsers is None:
        parsers = plugins.installed().parsers
    results = []
    for path in paths:
        result, accepted_by = _import_one(engine, path, parsers, now)
        if inbox is not None:
            folder = REJECTED_DIR if result.outcome == "rejected" else PROCESSED_DIR
            moving = companions(path, [accepted_by] if accepted_by is not None else parsers)
            move_with_companions(path, inbox / folder, moving)
        results.append(result)
    return results


def _parse(parser: Parser, file: CaptureFile) -> ParsedPosting | Rejected | None:
    try:
        return parser.parse(file)
    except Exception as error:  # a parser's failure is its rejection of this file only
        return Rejected(f"{type(error).__name__}: {error}")


def _rejection(parsers: Sequence[Parser], outcomes: list) -> str:
    accepted = [p for p, o in zip(parsers, outcomes, strict=True) if isinstance(o, ParsedPosting)]
    if len(accepted) > 1:
        return "accepted by more than one parser (" + ", ".join(plugins.label(p) for p in accepted) + ")"
    rejections = [(p, o) for p, o in zip(parsers, outcomes, strict=True) if isinstance(o, Rejected)]
    if rejections:
        return "; ".join(f"{plugins.label(p)}: {o.reason}" for p, o in rejections)
    if not parsers:
        return "no parsers are installed"
    return "not recognised by any installed parser (" + ", ".join(plugins.label(p) for p in parsers) + ")"


def _import_one(
    engine: Engine, path: Path, parsers: Sequence[Parser], now: datetime | None = None
) -> tuple[FileResult, Parser | None]:
    try:
        raw = path.read_bytes()
        modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        with engine.begin() as conn:
            duplicate = find_capture(conn, sha256_hex(raw))
            if duplicate is not None:
                posting = conn.execute(select(postings).where(postings.c.job_id == duplicate.job_id)).one()
                result = FileResult(
                    path.name, "duplicate", posting.job_id, posting.source, posting.external_id, url=posting.url
                )
                snapshot = latest_snapshot(conn, duplicate.job_id)
                if snapshot is not None:
                    result.title, result.company = snapshot.title, snapshot.company
                result.warnings.append("already imported (identical file)")
                return result, None

            file = CaptureFile(path, raw, modified_at)
            outcomes = [_parse(p, file) for p in parsers]
            accepted = [(p, o) for p, o in zip(parsers, outcomes, strict=True) if isinstance(o, ParsedPosting)]
            if len(accepted) != 1:
                return FileResult(path.name, "rejected", reason=_rejection(parsers, outcomes)), None
            [(parser, posting)] = accepted
            try:
                stored = store_capture(
                    conn, posting, raw, path.name, modified_at, now or datetime.now(UTC), plugins.label(parser)
                )
            except InvalidPosting as error:
                return FileResult(path.name, "rejected", reason=f"{plugins.label(parser)}: {error}"), None
    except Exception as error:  # one bad file must not stop the batch
        return FileResult(path.name, "rejected", reason=f"unexpected error: {type(error).__name__}: {error}"), None

    failed = [
        f"{plugins.label(p)} failed: {o.reason}"
        for p, o in zip(parsers, outcomes, strict=True)
        if isinstance(o, Rejected) and p is not parser
    ]
    result = FileResult(
        path.name, stored.outcome, stored.job_id, posting.source, posting.external_id, posting.title, posting.company,
        posting.url, [*posting.warnings, *failed],
    )
    return result, parser


def move_with_companions(path: Path, dest_dir: Path, companions: list[Path]) -> Path:
    """Move a file and its companions into dest_dir. On a name clash, `x.json` becomes `x (2).json`, and each
    companion named after the file (`x.json:Zone.Identifier`, `x_files`) gets the same number."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    stem = path.stem

    def renamed(name: str, number: int) -> str:
        if number == 1:
            return name
        if name.startswith(stem):
            return f"{stem} ({number}){name[len(stem):]}"
        p = Path(name)
        return f"{p.stem} ({number}){p.suffix}"

    number = 1
    while any((dest_dir / renamed(p.name, number)).exists() for p in (path, *companions)):
        number += 1
    for companion in companions:
        shutil.move(companion, dest_dir / renamed(companion.name, number))
    target = dest_dir / renamed(path.name, number)
    shutil.move(path, target)
    return target


def format_report(results: list[FileResult], warnings: Sequence[str] = ()) -> str:
    """Any parser-loading warnings, one line per file, then a count per outcome."""
    lines = [f"warning: {w}" for w in warnings]
    for r in results:
        if r.outcome == "rejected":
            lines.append(f"{r.outcome:<9} {r.name}: {r.reason}")
            continue
        line = f"{r.outcome:<9} {r.source} {r.external_id} {r.title} — {r.company}  {r.url}  [{r.name}]"
        lines.append(line + "".join(f" | warning: {w}" for w in r.warnings))
    counts = {o: sum(r.outcome == o for r in results) for o in OUTCOMES}
    lines.append("Totals: " + ", ".join(f"{n} {o}" for o, n in counts.items() if n))
    return "\n".join(lines)
