"""Find personal values and personal-looking patterns in a repository: tracked files, staged changes, untracked
files and git history. Personal values come from the user's own database (read-only) and a private term file.
"""

from __future__ import annotations

import bisect
import re
import subprocess
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine, make_url

MIN_TERM_LENGTH = 4
# A value starts a word after a non-word character, or right after a `\n`, `\r` or `\t` escape in source code.
WORD_START = r"(?:(?<!\w)|(?<=\\[nrt]))"
ALLOW_MARKER = "privacy: allow"
PRIVATE_TERM = "private term"
DEFAULT_TERMS_FILE = Path("data/privacy-terms.txt")
DEFAULT_ALLOW_FILE = Path("data/privacy-allow.txt")
COMMIT_IDENTITY = "<commit author or committer>"  # the path an allow entry names to accept a public identity

# category -> (table, columns) read from the database
TERM_COLUMNS: dict[str, tuple[str, tuple[str, ...]]] = {
    "profile detail": ("profile_details", ("text",)),
    "record title": ("records", ("title",)),
    "record organisation": ("records", ("organisation",)),
    "record line": ("record_lines", ("text",)),
    "record source": ("record_sources", ("url",)),
    "highlight": ("highlights", ("text",)),
    "document": ("documents", ("original_filename", "label")),
    "posting id": ("postings", ("external_id",)),
    "posting title": ("posting_snapshots", ("title",)),
    "posting company": ("posting_snapshots", ("company",)),
    "company": ("companies", ("name", "website_url", "careers_url")),
    "contact": ("contacts", ("name", "profile_url")),
    "contact email": ("contact_emails", ("email",)),
    "application note": ("applications", ("next_action", "compensation_notes")),
    "application event note": ("application_events", ("note",)),
    "posting note": ("posting_triage", ("notes",)),
    "tag": ("tags", ("name",)),
}

FORBIDDEN_SUFFIXES = (".db", ".sqlite", ".sqlite3", ".odt", ".docx", ".doc", ".pdf")
PAGE_SUFFIXES = (".htm", ".html")
PAGE_ALLOWED_PREFIXES = ("tests/fixtures/synthetic/", "src/jobhunt/web/templates/")
FORBIDDEN_PREFIXES = ("data/", "inbox/", "tests/fixtures/private/")

SYNTHETIC_ID_PREFIX = "9000000"
SYNTHETIC_EMAIL_DOMAINS = ("example.com", "example.org", "example.net")
SYNTHETIC_EMAIL_SUFFIXES = (".example", ".invalid")
NOREPLY_DOMAIN = "users.noreply.github.com"

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@((?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,})(?![\w.-]*\w)")
JOB_ID = re.compile(r"(?<![\w.])\d{9,10}(?![\w])")
PHONE = re.compile(r"(?<![\w.])(?:\+?1[\s.-]?)?\(?(\d{3})\)?[\s.-](\d{3})[\s.-](\d{4})(?![\w])")
HOME_PATH = re.compile(r"(?:/home|/Users)/([A-Za-z0-9._-]+)/|[A-Za-z]:\\Users\\([A-Za-z0-9._-]+)\\")


class PrivacyError(Exception):
    """A usage or database problem (exit code 2)."""


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    column: int
    category: str
    value: str
    commit: str | None = None

    def masked(self) -> str:
        return f"{self.value[:1]}… ({len(self.value)} chars)"

    def format(self, show: bool = False) -> str:
        where = self.path + (f" @{self.commit[:10]}" if self.commit else "")
        if self.line:
            where += f":{self.line}:{self.column}"
        return f"{where}: {self.category}: {self.value if show else self.masked()}"


@dataclass
class Report:
    findings: list[Finding]
    suppressed: int = 0
    notices: tuple[str, ...] = ()

    def by_category(self) -> Counter:
        return Counter(f.category for f in self.findings)

    def format(self, show: bool = False) -> str:
        lines = list(self.notices)
        lines += [f.format(show) for f in self.findings]
        if self.findings:
            lines.append("Findings by category:")
            lines += [f"  {category}: {count}" for category, count in sorted(self.by_category().items())]
        else:
            lines.append("No findings.")
        if self.suppressed:
            lines.append(f"Suppressed by allow entries or markers: {self.suppressed}")
        return "\n".join(lines)

    @property
    def exit_code(self) -> int:
        return 1 if self.findings else 0


# --- Terms ---


def normalise(value: str) -> str:
    return " ".join(value.casefold().split())


class Terms:
    """Personal values by normalised text, with the category each was collected under, matched as whole words."""

    def __init__(self, by_value: dict[str, str]):
        self.by_value = {v: c for v, c in by_value.items() if len(v) >= MIN_TERM_LENGTH}
        self._regex = self._compile(self.by_value)

    @staticmethod
    def _compile(values: dict[str, str]) -> re.Pattern | None:
        if not values:
            return None
        parts = []
        for value in sorted(values, key=len, reverse=True):
            body = r"\s+".join(re.escape(word) for word in value.split())
            head = WORD_START if value[0].isalnum() else ""
            tail = r"(?!\w)" if value[-1].isalnum() else ""
            parts.append(f"{head}{body}{tail}")
        return re.compile("|".join(parts), re.IGNORECASE)

    def __bool__(self) -> bool:
        return self._regex is not None

    def find(self, text: str) -> Iterator[tuple[int, int, str, str]]:
        """(start, end, category, matched text) for each personal value in `text`."""
        if self._regex is None:
            return
        for m in self._regex.finditer(text):
            yield m.start(), m.end(), self.by_value.get(normalise(m.group()), PRIVATE_TERM), m.group()


def read_lines(path: Path) -> list[str]:
    """Non-empty, non-comment lines of a term or allow file."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    return [
        line
        for line in (raw.rstrip("\r\n") for raw in text.splitlines())
        if line.strip() and not line.lstrip().startswith("#")
    ]


def read_terms_from(lines: Iterable[str]) -> dict[str, str]:
    return {normalise(line): PRIVATE_TERM for line in lines}


def read_terms(path: Path) -> dict[str, str]:
    return read_terms_from(read_lines(path))


class Allowed:
    """Values the allow file suppresses, everywhere or under a path prefix (`prefix<TAB>value`)."""

    def __init__(self, entries: Iterable[tuple[str, str]] = ()):
        self.entries = [(prefix, normalise(value)) for prefix, value in entries]

    @classmethod
    def from_file(cls, path: Path) -> Allowed:
        entries = []
        for line in read_lines(path):
            prefix, tab, value = line.partition("\t")
            entries.append((prefix.strip(), value) if tab else ("", line))
        return cls(entries)

    def covers(self, path: str, value: str) -> bool:
        wanted = normalise(value)
        return any(wanted == v and path.startswith(prefix) for prefix, v in self.entries)

    def values(self) -> list[tuple[str, str]]:
        return list(self.entries)


def database_terms(engine: Engine) -> dict[str, str]:
    """Distinct values of the personal columns, by normalised text. Reads only; refuses a database not at head."""
    from alembic.migration import MigrationContext
    from alembic.script import ScriptDirectory

    from .db import metadata
    from .migrate import config

    with engine.connect() as conn:
        found = MigrationContext.configure(conn).get_current_revision()
        head = ScriptDirectory.from_config(config()).get_current_head()
        if found != head:
            raise PrivacyError(
                f"the database is at schema version {found or 'none'}, not {head}; run `jobhunt import` or "
                "`jobhunt serve` once to upgrade it (this check never changes the database)"
            )
        by_value: dict[str, str] = {}
        for category, (table_name, columns) in TERM_COLUMNS.items():
            table = metadata.tables[table_name]
            for name in columns:
                column = table.c[name]
                for (value,) in conn.execute(select(func.distinct(column)).where(column.is_not(None))):
                    key = normalise(str(value))
                    if len(key) >= MIN_TERM_LENGTH:
                        by_value.setdefault(key, category)
        return by_value


def open_database(url: str) -> Engine | None:
    """A read-only engine, or None when a SQLite file doesn't exist (the check then runs patterns only)."""
    parsed = make_url(url)
    if parsed.get_backend_name() != "sqlite":
        return create_engine(url)
    if not parsed.database or parsed.database == ":memory:" or not Path(parsed.database).is_file():
        return None
    path = Path(parsed.database).resolve()
    return create_engine(f"sqlite:///file:{path}?mode=ro&uri=true")


# --- Scanning text ---


def _is_synthetic_email(domain: str) -> bool:
    domain = domain.lower()
    return domain in SYNTHETIC_EMAIL_DOMAINS or domain.endswith(SYNTHETIC_EMAIL_SUFFIXES) or domain == NOREPLY_DOMAIN


def pattern_matches(text: str) -> Iterator[tuple[int, int, str, str]]:
    """(start, end, category, matched text) for each personal-looking pattern outside the reserved ranges."""
    for m in JOB_ID.finditer(text):
        if not m.group().startswith(SYNTHETIC_ID_PREFIX):
            yield m.start(), m.end(), "job id", m.group()
    for m in EMAIL.finditer(text):
        if not _is_synthetic_email(m.group(1)):
            yield m.start(), m.end(), "email", m.group()
    for m in PHONE.finditer(text):
        _area, exchange, line = m.groups()
        if not (exchange == "555" and line.startswith("01")):
            yield m.start(), m.end(), "phone", m.group()
    for m in HOME_PATH.finditer(text):
        yield m.start(), m.end(), "home path", m.group()


class Scanner:
    def __init__(self, terms: Terms, allowed: Allowed):
        self.terms = terms
        self.allowed = allowed
        self.suppressed = 0

    def scan_text(self, path: str, text: str, commit: str | None = None) -> list[Finding]:
        newlines = [i for i, ch in enumerate(text) if ch == "\n"]
        lines = text.split("\n")
        found: list[Finding] = []

        def place(start: int) -> tuple[int, int]:
            row = bisect.bisect_left(newlines, start)
            return row + 1, start - (newlines[row - 1] + 1 if row else 0) + 1

        for start, _end, category, value in self.terms.find(text):
            if self.allowed.covers(path, value):
                self.suppressed += 1
                continue
            line, column = place(start)
            found.append(Finding(path, line, column, category, value, commit))
        for start, _end, category, value in pattern_matches(text):
            line, column = place(start)
            if ALLOW_MARKER in lines[line - 1] or self.allowed.covers(path, value):
                self.suppressed += 1
                continue
            found.append(Finding(path, line, column, category, value, commit))
        return found

    def scan_name(self, path: str, commit: str | None = None) -> list[Finding]:
        """Private terms in a file's own path."""
        found = []
        for _start, _end, category, value in self.terms.find(path):
            if self.allowed.covers(path, value):
                self.suppressed += 1
            else:
                found.append(Finding(path, 0, 0, category, value, commit))
        return found


def forbidden_kind(path: str) -> bool:
    lower = path.lower()
    if lower.endswith(FORBIDDEN_SUFFIXES) or lower.endswith(":zone.identifier"):
        return True
    if lower.endswith(PAGE_SUFFIXES) and not path.startswith(PAGE_ALLOWED_PREFIXES):
        return True
    return path.startswith(FORBIDDEN_PREFIXES)


def decode(data: bytes) -> str | None:
    """The text of a file, or None for a binary one."""
    if b"\0" in data:
        return None
    return data.decode("utf-8", errors="replace")


# --- Git ---


def git(repo: Path, *args: str, check: bool = True) -> bytes:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    if check and done.returncode != 0:
        raise PrivacyError(f"git {' '.join(args[:2])} failed: {done.stderr.decode(errors='replace').strip()}")
    return done.stdout


def _paths(output: bytes) -> list[str]:
    return [p.decode("utf-8", errors="surrogateescape") for p in output.split(b"\0") if p]


def tracked_paths(repo: Path) -> list[str]:
    return _paths(git(repo, "ls-files", "-z"))


def staged_paths(repo: Path) -> list[str]:
    return _paths(git(repo, "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR"))


def untracked_folders(repo: Path) -> list[Finding]:
    """Untracked, unignored files of forbidden kinds, grouped by their top-level folder."""
    groups: dict[str, str] = {}
    for path in _paths(git(repo, "ls-files", "--others", "--exclude-standard", "-z")):
        if forbidden_kind(path):
            top = path.split("/", 1)[0] + "/" if "/" in path else path
            groups.setdefault(top, path)
    return [Finding(top, 0, 0, "unignored personal file", top) for top in sorted(groups)]


class BlobReader:
    """Blob contents by id from one `git cat-file --batch` process."""

    def __init__(self, repo: Path):
        self.proc = subprocess.Popen(
            ["git", "-C", str(repo), "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE
        )

    def read(self, blob: str) -> bytes:
        self.proc.stdin.write(blob.encode() + b"\n")
        self.proc.stdin.flush()
        header = self.proc.stdout.readline().split()
        if len(header) != 3:
            raise PrivacyError(f"git could not read blob {blob}")
        data = self.proc.stdout.read(int(header[2]))
        self.proc.stdout.read(1)  # the newline after the content
        return data

    def close(self) -> None:
        self.proc.stdin.close()
        self.proc.wait()


def scan_history(repo: Path, scanner: Scanner, private: Terms) -> list[Finding]:
    found: list[Finding] = []
    seen_blobs: set[str] = set()
    seen_paths: set[str] = set()
    reader = BlobReader(repo)
    try:
        commits = git(repo, "rev-list", "--all").decode().split()
        for commit in commits:
            meta = git(repo, "log", "-1", "--format=%an%x00%ae%x00%cn%x00%ce%x00%B", commit).decode(errors="replace")
            *identity, message = meta.split("\0", 4)
            for field in identity:
                for _s, _e, _c, value in private.find(field):
                    if scanner.allowed.covers(COMMIT_IDENTITY, value):
                        scanner.suppressed += 1
                    else:
                        found.append(Finding(COMMIT_IDENTITY, 0, 0, "commit identity", value, commit))
            found += scanner.scan_text("<commit message>", message, commit)
            for entry in git(repo, "ls-tree", "-r", "-z", commit).split(b"\0"):
                if not entry:
                    continue
                meta_part, _tab, raw_path = entry.partition(b"\t")
                _mode, kind, blob = meta_part.decode().split()
                path = raw_path.decode("utf-8", errors="surrogateescape")
                if kind != "blob":
                    continue
                if path not in seen_paths:
                    seen_paths.add(path)
                    found += scanner.scan_name(path, commit)
                    if forbidden_kind(path):
                        found.append(Finding(path, 0, 0, "forbidden file", path, commit))
                if blob in seen_blobs:
                    continue
                seen_blobs.add(blob)
                text = decode(reader.read(blob))
                if text is not None:
                    found += scanner.scan_text(path, text, commit)
    finally:
        reader.close()
    return found


# --- The check ---


def check(
    repo: Path,
    terms: dict[str, str] | None = None,
    allowed: Allowed | None = None,
    staged: bool = False,
    history: bool = False,
    private_terms: dict[str, str] | None = None,
    protect: Iterable[Path] = (),
    notices: Iterable[str] = (),
) -> Report:
    """Scan `repo`. `terms` are the personal values (database and private terms together); `private_terms` are
    checked against author and committer fields; `protect` are files that must never be tracked or staged."""
    merged = dict(terms or {})
    merged.update(private_terms or {})
    scanner = Scanner(Terms(merged), allowed or Allowed())
    findings: list[Finding] = []

    names = staged_paths(repo) if staged else tracked_paths(repo)
    for path in names:
        findings += scanner.scan_name(path)
        if forbidden_kind(path):
            findings.append(Finding(path, 0, 0, "forbidden file", path))
        if staged:
            data = git(repo, "show", f":{path}", check=False)
        else:
            try:
                data = (repo / path).read_bytes()
            except (FileNotFoundError, IsADirectoryError):
                continue
        text = decode(data)
        if text is not None:
            findings += scanner.scan_text(path, text)

    root = repo.resolve()
    listed = set(names) | set(tracked_paths(repo)) | set(staged_paths(repo))
    for protected in protect:
        try:
            relative = str(protected.resolve().relative_to(root))
        except ValueError:
            continue
        if relative in listed:
            findings.append(Finding(relative, 0, 0, "tracked private file", relative))

    if not staged:
        findings += untracked_folders(repo)
    if history:
        findings += scan_history(repo, scanner, Terms(private_terms or {}))
    return Report(findings, scanner.suppressed, tuple(notices))
