## Why

A browser's "Save Page, Complete" writes a `<name>_files/` folder of scripts, stylesheets and images beside each saved page. A parser for saved pages names that folder as a companion only so it moves with the page; parsers may not read other files, so nothing ever uses it. Each folder is tens of megabytes, the folders repeat the same assets, and the import keeps every one of them in `inbox/processed/` or `inbox/rejected/`. Over a few months of collecting they make up nearly all of the inbox's size, and the "Processed files leave the inbox" requirement allows no deletion at all.

## What Changes

- **A parser can mark a companion as discardable.** A new optional parser method names which of a file's companions may be removed once the file has been filed away. Only a path the same parser also names as a companion counts, so a parser can't make the app delete anything else. The built-in `posting-file` parser has no companions and marks nothing.
- **Everything else is kept.** The file itself, its download metadata (`:Zone.Identifier`) and every companion no installed parser marks stay in `processed/` and `rejected/`, for accepted and rejected files alike, so an import can still be checked by hand.
- **The import still deletes nothing.** It moves discardable companions with their file, as today. Only the prune removes files.
- **The prune** removes discardable companions from `inbox/processed/` and `inbox/rejected/`, asking the parsers installed at the time. It never touches files directly in the inbox, follows no links out of those folders, and reports what it removed (count and bytes) and anything it couldn't remove.
- **The server prunes daily.** While `jobhunt serve` runs, it prunes at start-up when no prune of that inbox is recorded in the last 24 hours, and again each time 24 hours have passed. The first start after upgrading therefore removes the existing pile.
- **`jobhunt inbox prune`** runs a prune by hand, with `--dry-run` to list what would be removed without removing it.
- **Each prune is recorded** in a new operational table (time, inbox, number and bytes removed, problems). The Import page shows the latest one, and the server prints a line for each prune.

Not in this change:
- deduplicating the assets instead of deleting them (no parser reads them);
- a warning at import time about large companions;
- changing how pages are saved at their source.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `capture-import`: the parser contract gains discardable companions; "Processed files leave the inbox" keeps the import from deleting files but lets the prune remove discardable companions; new requirements for the prune, its daily run in the server, the `inbox prune` command and the prune record shown on the Import page.

## Parser impact

**Optional.** The parser contract gains an optional `discardable(path)` method, and parsers that don't define it keep working unchanged: the prune removes nothing for their files. A parser that names disposable companions (such as a saved page's asset folder) should adopt it. [parser-changes.md](parser-changes.md) is the brief for parser maintainers, and `docs/parsers.md` gains this change in its contract changelog.

## Impact

- `src/jobhunt/parsers/__init__.py`: the optional `discardable(path)` method in the protocol, and a helper that keeps only a parser's own companions.
- New `src/jobhunt/prune.py`: plan and run a prune, record it, and the `Pruner` thread `serve` starts. It is the only writer of the new table.
- `src/jobhunt/db.py` and a new Alembic revision `0011`: the `inbox_prunes` operational table, listed in `OPERATIONAL_TABLES`.
- `src/jobhunt/cli.py`: `jobhunt inbox prune [--dry-run]`, and the `Pruner` started and stopped beside the worker in `serve`.
- `src/jobhunt/web/postings.py` and `templates/import_report.html`: the latest prune on the Import page.
- `tests/fakes.py`: `FakeParser` can mark companion suffixes discardable; new `tests/test_prune.py`, plus CLI, migration and web cases.
- Parsers outside this repository: see "Parser impact".
- Docs: a new `docs/parsers.md` (guide for parser authors, with a contract changelog), CLAUDE.md ("Getting postings in", the four data kinds, Architecture, Commands), README ("nothing is deleted" no longer holds; a pointer to the parser guide), and FUTURE_CHANGE.md (section 4 removed).
- No new dependency. No model is used.
