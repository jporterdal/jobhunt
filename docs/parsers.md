# Writing a parser

jobhunt reads every posting through a **parser**: a small Python object that looks at one file a person collected
and says whether it holds a posting. The built-in parser reads posting files (one JSON object per posting; see the
[README](../README.md#getting-postings-in)). Any other format, such as pages saved from a job board's website, is
read by a parser you install beside the app. This guide is for someone writing their first one.

The rules a parser must follow are in the
[`capture-import` spec](../openspec/specs/capture-import/spec.md) ("Parsers are installed plug-ins", "Exactly one
parser must accept a file", "Identity comes from the accepting parser", "Parsers can mark companions as discardable"
and "Processed files leave the inbox"). This guide shows how to meet them. Where the two disagree, the spec wins.
The types are in [`src/jobhunt/parsers/__init__.py`](../src/jobhunt/parsers/__init__.py).

## The contract

A parser is any object with:

- `name: str`, unique among installed parsers (two parsers with the same name are both left out, with a warning);
- `version: str`, recorded with every capture as `name@version`;
- `parse(file: CaptureFile) -> ParsedPosting | Rejected | None`;
- optionally, `companions(path: Path) -> list[Path]`;
- optionally, `discardable(path: Path) -> list[Path]`.

**`parse`** gets a `CaptureFile`: the file's `path`, its bytes (`raw`) and its modification time (`modified_at`,
UTC). It returns:

- `None` when the file isn't one of yours. Every installed parser is tried on every file, so most files you see
  belong to someone else. Recognise yours **by their contents**, not by their name or extension: several parsers
  may read HTML.
- `Rejected(reason)` when the file is yours but can't be used (an empty description, a page saved before it
  finished loading). The reason is shown to the person importing.
- a `ParsedPosting` otherwise. `source` (lowercase letters, digits, dots and hyphens: for a website, its host
  without `www.`) and `external_id` are the posting's identity, so re-capturing the same posting under another
  filename updates it. `url`, `title`, `company` and `description_html` are required; the HTML is sanitized again
  when stored. `details` holds extra fields that are compared between captures, and `volatile_details` extra fields
  that are stored but not compared (an applicant count changes daily and isn't a change to the posting). `warnings`
  are shown in the import report.

Raising an error counts as your rejection of that file, so a bug in a parser never stops an import. Read only
`file.raw`: a parser **must not read other files**, companions included.

**`companions(path)`** names the files that belong to `path` and must move with it into `inbox/processed/` or
`inbox/rejected/`, such as the `<name>_files/` folder a browser writes beside a page saved with "Save Page,
Complete". Name them from `path` alone (`path.with_name(path.stem + "_files")`); return paths whether or not they
exist, since only existing ones are moved. A file's download metadata (`<name>:Zone.Identifier`) always moves with
it, so don't name it. A file you name as a companion is never offered to any parser as a file of its own.

**`discardable(path)`** names which of those companions may be deleted once `path` has been filed away: files kept
only so they move with it. The daily prune deletes them from `inbox/processed/` and `inbox/rejected/`.

- Only paths your `companions(path)` also returns count; anything else is ignored.
- The file itself and its download metadata are never deleted, even if returned.
- Not defining the method, returning `[]` or raising all mean "keep everything".
- The prune asks every installed parser about every filed-away file, including files you rejected and files
  another parser accepted, so build the answer the same way `companions` builds it. Consider returning `[]` from
  both methods for files you could never accept.
- Return a companion only if nothing will ever need it again: a pruned companion can't be restored.

**`version`** marks your parsed output. Bump it when the same file would parse differently. Keep each source's
`details` names and value forms stable, or every re-capture is stored as an update.

### An example

An invented format: a text export whose first line is `EXJOB 1`, followed by `key: value` lines and a blank line
before the description.

```
EXJOB 1
id: 9000000201
title: Data Engineer
company: Example Labs
url: https://jobs.example.com/view/9000000201

We are looking for someone to build data pipelines in Python.
```

```python
from html import escape
from pathlib import Path

from jobhunt.parsers import CaptureFile, ParsedPosting, Rejected

MAGIC = b"EXJOB 1\n"


class ExampleExportParser:
    name = "example-export"
    version = "1"

    def parse(self, file: CaptureFile) -> ParsedPosting | Rejected | None:
        if not file.raw.startswith(MAGIC):
            return None  # not ours
        head, _, body = file.raw[len(MAGIC):].decode("utf-8").partition("\n\n")
        fields = dict(line.split(": ", 1) for line in head.splitlines())
        if not body.strip():
            return Rejected("the export has no description")
        return ParsedPosting(
            source="jobs.example.com",
            external_id=fields["id"],
            url=fields["url"],
            title=fields["title"],
            company=fields["company"],
            description_html=f"<p>{escape(body.strip())}</p>",
        )

    def companions(self, path: Path) -> list[Path]:
        return [path.with_name(path.stem + "_files")]  # saved assets, if the export came with any

    def discardable(self, path: Path) -> list[Path]:
        return [path.with_name(path.stem + "_files")]  # no one reads them once the file is filed away


PARSER = ExampleExportParser()
```

A `KeyError` from a missing field is a rejection naming the error; a real parser would check each field and reject
with a clearer reason.

## A parser in its own repository

A parser can live in its own repository, private if it reads a site you'd rather not name. Make it an ordinary
package that registers the parser under the `jobhunt.parsers` entry-point group:

```toml
# pyproject.toml of the parser's package
[project]
name = "example-export-parser"
version = "0.1.0"
dependencies = ["jobhunt"]

[project.entry-points."jobhunt.parsers"]
example-export = "example_export_parser:PARSER"
```

The entry point may name an object (as here) or a class that takes no arguments. Install it, editable, into the
same venv as jobhunt:

```bash
source /path/to/jobhunt/venv/bin/activate
pip install -e /path/to/example-export-parser
```

Then list what the app will load:

```bash
python -c "from jobhunt.parsers import installed; i = installed(); print([p.name for p in i.parsers], i.errors)"
```

A parser that fails to load is reported as a warning by `jobhunt import` and the rest still load.

**When to run `pip install -e .` again:** only when an entry point changes (added, renamed or pointed elsewhere),
in the parser's package or in jobhunt's. Entry points come from installed metadata; code changes, including new
methods such as `discardable`, are picked up by an editable install without reinstalling.

## Testing a parser

Test `parse` directly: build a `CaptureFile` from invented bytes, and check each result.

```python
from datetime import UTC, datetime
from pathlib import Path

from jobhunt.parsers import CaptureFile, ParsedPosting, Rejected
from example_export_parser import PARSER


def capture(raw: bytes, name: str = "a.txt") -> CaptureFile:
    return CaptureFile(Path("inbox") / name, raw, datetime(2026, 3, 2, tzinfo=UTC))


def test_recognises_its_own_files_only():
    assert PARSER.parse(capture(b"<html></html>")) is None


def test_reads_a_posting():
    raw = b"EXJOB 1\nid: 9000000201\ntitle: Data Engineer\ncompany: Example Labs\n" \
          b"url: https://jobs.example.com/view/9000000201\n\nBuild pipelines.\n"
    posting = PARSER.parse(capture(raw))
    assert isinstance(posting, ParsedPosting) and posting.external_id == "9000000201"


def test_discardable_companions_are_its_own():
    path = Path("inbox/A.txt")
    marked = PARSER.discardable(path)
    assert marked == [Path("inbox/A_files")]
    assert set(marked) <= set(PARSER.companions(path))
    assert path not in marked and Path("inbox/A.txt:Zone.Identifier") not in marked
```

Then try it against jobhunt on a scratch inbox and database, never your own:

```bash
mkdir -p /tmp/scratch/inbox && cp invented-example.txt /tmp/scratch/inbox/
jobhunt import --inbox /tmp/scratch/inbox --db sqlite:////tmp/scratch/jobhunt.db
jobhunt inbox prune --dry-run --inbox /tmp/scratch/inbox   # lists what the prune would delete; deletes nothing
```

Use invented postings in tests and fixtures (see [fictional-data.md](fictional-data.md)): files saved from a real
site hold real people's names and real posting IDs.

## Contract changelog

Each change to what jobhunt asks of parsers, newest first. *Optional* changes keep existing parsers working;
*required* ones need parser work before upgrading jobhunt.

- **Optional: `discardable(path)`** (change `prune-discardable-companions`). A parser can mark which of its
  companions the daily prune may delete from `inbox/processed/` and `inbox/rejected/`. Parsers without it keep
  every companion. Brief for maintainers:
  [parser-impact.md](../openspec/changes/prune-discardable-companions/parser-impact.md).
