"""The prune: remove the companions installed parsers mark discardable from the inbox's processed and rejected
folders, and record each prune (`inbox_prunes`, written only here). `Pruner` runs it daily inside `serve`."""

from __future__ import annotations

import json
import logging
import os
import shutil
import stat
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import insert, select
from sqlalchemy.engine import Connection, Engine

from . import parsers as plugins
from .db import inbox_prunes
from .importer import PROCESSED_DIR, REJECTED_DIR, companions
from .parsers import DOWNLOAD_METADATA, Parser
from .units import format_size

log = logging.getLogger(__name__)

FOLDERS = (PROCESSED_DIR, REJECTED_DIR)
INTERVAL = timedelta(hours=24)
MAX_WAIT = timedelta(hours=1)  # waits are by wall clock: re-read the record at least this often (sleep, hand prunes)
MAX_DETAIL = 50  # problems kept in a record's detail


@dataclass(frozen=True)
class Companion:
    path: Path  # the discardable companion
    owner: Path  # the file it belongs to
    size: int  # apparent size in bytes, links not followed


@dataclass
class Result:
    inbox: Path
    started_at: datetime
    finished_at: datetime | None = None
    dry_run: bool = False
    missing: bool = False  # the inbox folder doesn't exist
    stopped: bool = False  # stopped before every companion was removed
    removed: list[Companion] = field(default_factory=list)  # or, in a dry run, the ones that would be
    problems: list[tuple[Path, str]] = field(default_factory=list)

    @property
    def bytes(self) -> int:
        return sum(c.size for c in self.removed)

    def summary(self) -> str:
        """`12 companions, 530.2 MB removed, 0 problems`."""
        verb = "would be removed" if self.dry_run else "removed"
        return (f"{_count(len(self.removed), 'companion')}, {format_size(self.bytes)} {verb}, "
                f"{_count(len(self.problems), 'problem')}")


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def size_of(path: Path) -> int:
    """The apparent size of a file, a link (not followed) or a folder's contents (links inside not followed)."""
    try:
        st = path.lstat()
    except FileNotFoundError:
        return 0
    if not stat.S_ISDIR(st.st_mode):
        return st.st_size
    total = 0
    for folder, dirs, files in os.walk(path, followlinks=False):
        for name in (*dirs, *files):
            try:
                st = os.lstat(os.path.join(folder, name))
            except OSError:
                continue
            if not stat.S_ISDIR(st.st_mode):
                total += st.st_size
    return total


def plan(inbox: Path, parsers: Sequence[Parser]) -> list[Companion]:
    """The existing discardable companions of the files directly inside the processed and rejected folders, by any
    of `parsers`. Files that are other files' companions aren't asked about; files directly in the inbox never are."""
    planned: list[Companion] = []
    seen: set[Path] = set()
    for name in FOLDERS:
        folder = inbox / name
        if folder.is_symlink() or not folder.is_dir():
            continue
        files = sorted(p for p in folder.iterdir() if p.is_file() and not p.is_symlink())
        belonging = {c for f in files for c in companions(f, parsers)}
        for file in files:
            if file in belonging:
                continue
            for parser in parsers:
                for path in plugins.discardable(parser, file):
                    if path not in seen and os.path.lexists(path):
                        seen.add(path)
                        planned.append(Companion(path, file, size_of(path)))
    return planned


def _refusal(companion: Companion) -> str | None:
    """Why a planned path must not be removed (checked again just before removing), or None."""
    path, owner = companion.path, companion.owner
    if path.parent != owner.parent:
        return f"not directly inside {owner.parent.name}/ beside {owner.name}; kept"
    if path.name in (owner.name, owner.name + DOWNLOAD_METADATA):
        return "the file itself or its download metadata; kept"
    return None


def _remove(path: Path) -> list[str] | None:
    """Remove a link or file, or a folder with its contents; links are never followed. None when it was already
    gone, else the problems met (empty when removed completely)."""
    try:
        st = path.lstat()
    except FileNotFoundError:
        return None
    except OSError as error:
        return [str(error)]
    if not stat.S_ISDIR(st.st_mode):
        try:
            path.unlink()
        except FileNotFoundError:
            return None
        except OSError as error:
            return [str(error)]
        return []

    errors: list[str] = []

    def collect(function, failed, error) -> None:
        if not isinstance(error, FileNotFoundError):
            errors.append(f"{failed}: {error}")

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=collect)
    else:  # Python 3.11
        shutil.rmtree(path, onerror=lambda function, failed, info: collect(function, failed, info[1]))
    return errors


def shown(path: Path, inbox: Path) -> str:
    """`path` relative to the inbox when it is inside it."""
    try:
        return str(path.relative_to(inbox))
    except ValueError:
        return str(path)


def run(
    engine: Engine | None,
    inbox: Path,
    parsers: Sequence[Parser],
    now: datetime,
    stop: threading.Event | None = None,
    dry_run: bool = False,
    on_companion: Callable[[Companion, str | None], None] | None = None,
) -> Result:
    """Prune once and, unless `dry_run`, record it (a dry run needs no `engine`). `now` is the start time; `stop` is
    checked between companions. `on_companion(companion, problem)` is called after each one is handled."""
    began = time.monotonic()
    result = Result(inbox, now, dry_run=dry_run)
    if not inbox.is_dir():
        result.missing = True
        planned = []
    else:
        planned = plan(inbox, parsers)
    for companion in planned:
        if stop is not None and stop.is_set():
            result.stopped = True
            break
        problem = _refusal(companion)
        if problem is None and not dry_run:
            problems = _remove(companion.path)
            if problems is None:  # already gone: neither counted nor a problem
                continue
            problem = "; ".join(problems) or None
        if problem is None:
            result.removed.append(companion)
        else:
            result.problems.append((companion.path, problem))
        if on_companion is not None:
            on_companion(companion, problem)
    result.finished_at = now + timedelta(seconds=time.monotonic() - began)
    if not dry_run:
        detail = [[shown(p, inbox), reason] for p, reason in result.problems[:MAX_DETAIL]]
        with engine.begin() as conn:
            conn.execute(insert(inbox_prunes).values(
                inbox=_key(inbox), started_at=result.started_at, finished_at=result.finished_at,
                removed=len(result.removed), bytes=result.bytes, problems=len(result.problems),
                detail=json.dumps(detail),
            ))
    return result


def _key(inbox: Path) -> str:
    return str(inbox.resolve())


def latest(conn: Connection, inbox: Path):
    """The latest recorded prune of `inbox` (a row of `inbox_prunes`), or None."""
    return conn.execute(
        select(inbox_prunes)
        .where(inbox_prunes.c.inbox == _key(inbox))
        .order_by(inbox_prunes.c.finished_at.desc(), inbox_prunes.c.id.desc())
        .limit(1)
    ).first()


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Pruner(threading.Thread):
    """Prunes the server's inbox when no prune of it is recorded within `interval`, checking at least every
    `MAX_WAIT`. Started and stopped by `serve` beside the worker."""

    def __init__(
        self, engine: Engine, inbox: Path, parsers: Sequence[Parser], interval: timedelta = INTERVAL,
        clock: Callable[[], datetime] = _utcnow,
    ):
        super().__init__(name="jobhunt-pruner", daemon=True)
        self.engine = engine
        self.inbox = inbox
        self.parsers = tuple(parsers)
        self.interval = interval
        self.clock = clock
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def _last(self) -> datetime | None:
        with self.engine.connect() as conn:
            row = latest(conn, self.inbox)
        return row.finished_at if row is not None else None

    def run_once(self, now: datetime) -> Result | None:
        """Prune and print the result when one is due at `now`; otherwise do nothing."""
        last = self._last()
        if last is not None and now - last < self.interval:
            return None
        result = run(self.engine, self.inbox, self.parsers, now, stop=self._stop_event)
        print(f"jobhunt: pruned inbox: {result.summary()}", flush=True)
        return result

    def wait_after(self, now: datetime) -> timedelta:
        """How long to wait from `now` before checking again: until the next prune is due, at most `MAX_WAIT`."""
        last = self._last()
        if last is None:
            return timedelta(0)
        return max(timedelta(0), min(MAX_WAIT, last + self.interval - now))

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.run_once(self.clock())
                wait = self.wait_after(self.clock())
            except Exception:
                log.exception("inbox prune failed")
                wait = MAX_WAIT
            self._stop_event.wait(wait.total_seconds())
