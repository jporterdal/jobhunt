## Context

- A parser names a file's companions through an optional `companions(path)` (`parsers/__init__.py`). The importer moves them with the file into `inbox/processed/` or `inbox/rejected/` (`importer.move_with_companions`). On a name clash the file and every companion named after it get the same number (`x (2).html`, `x (2)_files`). Companions are moved before the file.
- Rejected files have no capture row, so for files in the two folders nothing records which parser named their companions. The importer's `companions(path, parsers)` therefore asks every installed parser.
- `serve` starts one `jobs.Worker` thread, which is skipped in the debug reloader's parent process. A posting or document job holds that thread for minutes.
- Data kinds have one writer each (CLAUDE.md, "Four data kinds, one writer each"). `app_settings` is user-authored and is written only by `userdata.py`. `llm_jobs` is operational and is written only by `enrich/jobs.py`.
- The Import page exists only as the result of `POST /import` (`import_report.html`). There is no GET import page.

## Goals / Non-Goals

**Goals:**
- Deletion has one path. That path removes only what a parser has explicitly marked, and only inside `processed/` and `rejected/`.
- The daily prune never blocks requests, model jobs or the server's start-up.
- Existing parsers keep working unchanged. A parser without the new method causes nothing to be deleted.

**Non-Goals:**
- Reclaiming space from anything other than discardable companions (old captures, documents, backups).
- Recovering pruned companions. They are deleted, not moved to a trash folder.
- A configurable interval. 24 hours is a constant.

## Decisions

### D1. The contract: an optional `discardable(path)` method, limited to the parser's own companions

A parser may define `discardable(path) -> list[Path]`, beside `companions(path)`. A new helper `parsers.discardable(parser, path)` returns its answer intersected with `companions(parser, path)`. It leaves out `path` itself and `path`'s download metadata. If either method raises, it returns `[]`. The `Parser` protocol's comment documents both optional methods.

- *Why the intersection:* a parser can only give up files it has already claimed as belonging to a file it recognises. A buggy `discardable` can't reach a sibling page or an unrelated folder.
- *Alternative: `companions()` returns tagged objects (path plus a flag).* Rejected because it changes an existing contract that an installed package already implements.
- *Alternative: a class attribute of discardable suffixes.* Simpler, but it assumes companions are named by suffix. The method form works for any naming scheme and mirrors `companions`.

### D2. What the prune looks at

For each of `processed/` and `rejected/` (each may be missing), the prune lists the regular files directly inside it. Like `importer.discover`, it skips any file that is another listed file's companion. Then it asks every installed parser for `discardable(file)`. The union of the answers, minus non-existent paths, is the plan.

- Skipping companions keeps a companion such as `page.meta` from being treated as a file of its own, whose "companions" a parser might match by stem.
- Every installed parser is asked, not just the one that accepted the file. Rejected files have no accepting parser, and the spec's "any installed parser" rule then reads the same for both folders. A parser that is no longer installed marks nothing, so its companions are kept.
- Files directly in the inbox are never listed. They haven't been imported yet.

### D3. Removing safely

Each planned path is checked again just before it is removed: its parent must be the folder being pruned, and it must not be the file itself or `:Zone.Identifier`. The path is then examined with `lstat`:

- symbolic link → `unlink` (never followed)
- directory → `shutil.rmtree`, which refuses a symlinked root and doesn't follow links inside
- anything else → `unlink`

Its size is summed with `lstat` over `os.walk(..., followlinks=False)` before removal. The size counts toward the totals only if the removal succeeds completely. `FileNotFoundError` means the path is already gone (a concurrent prune or a hand clean-up): it is neither counted nor treated as a problem. Any other `OSError`, including errors collected by `rmtree`'s error callback (`onexc` from Python 3.12, `onerror` on 3.11, which CI still tests), becomes a problem `(path, reason)`, and the prune moves on.

The same function produces the plan for `--dry-run`. A dry run measures sizes and stops before removing anything.

### D4. Where prunes are recorded: a new operational table `inbox_prunes`

The table has these columns: `id`, `inbox` (the resolved absolute path, as text), `started_at`, `finished_at`, `removed` (integer), `bytes` (BigInteger), `problems` (integer), `detail` (text: the problems as JSON, the first 50 of them). Rows are appended, never updated. The table is written only by the new `prune.py` and listed in `OPERATIONAL_TABLES`. Alembic revision `0011` adds it, with a `downgrade()` that drops it.

- *Alternative: `app_settings`.* Rejected because that table is user-authored and written only by `userdata.py`, and a prune time isn't the user's data.
- *Alternative: a marker file in the inbox.* It would key the schedule to the folder naturally. But files directly in the inbox are import candidates, so `discover` would need an exception, and the record wouldn't be kept with the rest of the database.
- *Alternative: a `prune` kind in `llm_jobs`.* Rejected because the worker runs jobs one at a time, so a prune would wait behind long model jobs, and the queue's columns (model, pipeline) don't fit.
- *Keyed by inbox:* "the latest prune" means the latest row for the server's resolved inbox path. Serving the demo database against the real inbox, or one database against two inboxes, then keeps a schedule per inbox. If the folder is renamed, the next start prunes once more than strictly needed, which is harmless.

### D5. Scheduling: a `Pruner` thread beside the worker

`prune.Pruner(engine, inbox, parsers, interval=24h, clock=utcnow)` is a daemon thread. `_serve` starts and stops it next to the `Worker`, under the same guard against the debug reloader's parent. The loop:

1. Read the latest `finished_at` for this inbox.
2. If there is none, or it is at least `interval` ago, prune, record it and print the result.
3. Wait on the stop event until the next prune is due, but never more than `MAX_WAIT` (1 hour), then go back to step 1.

The prune also checks the stop event between companions.

- *Why its own thread:* inside the `Worker` loop, a prune would wait behind model jobs, and a model job would wait behind a large first prune.
- *Why cap the wait:* the wait is by wall clock and WSL machines sleep. Re-reading the database every hour catches up after a suspend. It also picks up a prune made in the meantime by `jobhunt inbox prune`, which pushes the next one back.
- An unexpected error in the loop is logged (`log.exception`), not recorded. The thread retries after `MAX_WAIT` instead of spinning.
- The server prints one line per prune to stdout, matching `serve`'s start-up lines: `jobhunt: pruned inbox: 12 companions, 530.2 MB removed, 0 problems`. The module logger isn't configured to show INFO under Flask, so `print(..., flush=True)` is used.

### D6. `jobhunt inbox prune`

`inbox` becomes a command group, mirroring `profile`, with `prune` as its only subcommand. It takes `_storage_args` (`--inbox`, `--db`) and `--dry-run`. It uses the installed parsers and prints any of their load errors as warnings first, as the import does. It prints one line per companion (`removed  processed/a_files  44.1 MB`, or `would remove …`), then the problems and the totals.

A dry run doesn't open the database. A real run calls `init_db` and records the prune. Exit codes follow the spec: 0, 1 when there are problems, 2 when the inbox is missing.

### D7. Showing the latest prune

`queries.latest_prune(conn, inbox)` returns the latest row or `None`. `POST /import` passes it to `import_report.html`, which shows it under the results (also on the "inbox not found" page). The page shows when the prune finished, what it removed (formatted with the existing `size` filter, `web.format_size`; the command line uses the same formatting, moved somewhere both can import), and the number of problems, or "Not pruned yet". GET handlers stay read-only. The page never prunes.

### D8. Parsers outside this repository: a brief, not edits

Parsers can live in other repositories, private ones included, so this change edits none of them. [parser-impact.md](parser-impact.md) is a self-contained brief for their maintainers: the contract delta, steps, tests and a compatibility table. A parser that adopts the method returns the same paths its `companions` builds, for example a saved page's `<stem>_files` folder. Its `version` stays the same, because a parser's version marks changes in parsed output and parsing doesn't change. An editable install picks the method up without reinstalling. Until a parser has the method, the prune removes nothing for its files. `docs/parsers.md` records the change in its contract changelog.

### D9. Tests

- `tests/fakes.FakeParser` gains `discardable_suffixes` (a subset of `companion_suffixes`).
- `prune.py` takes `now` and a clock, so the schedule is tested without waiting. The `Pruner` loop is tested through a `run_once(now)` step and a stop event.
- The symlink scenario uses a temporary target folder, and is skipped where symlinks can't be made.
- The permission scenario makes a folder read-only, and is skipped when running as root.
- Migration and web cases run on Postgres too.

## Risks / Trade-offs

- [The first start after upgrading deletes the existing pile, possibly gigabytes] → This is intended (decided with the user). `jobhunt inbox prune --dry-run` shows it first, and CLAUDE.md and the README say so. Back up `inbox/` beforehand if wanted.
- [A parser marks something it shouldn't] → Only the parser's own companions can be marked (D1), only inside `processed/` and `rejected/`, and links aren't followed (D3).
- [A rejected page moved back into the inbox no longer has its asset folder] → No parser reads companions' contents, so re-importing the page works the same.
- [A concurrent import moves a file in while the prune runs] → Companions are moved before their file, so the prune never sees a file before its companions. A clash rename gives the companion the file's new stem, which is what the parser matches.
- [Two prunes at once (the server and the command)] → A path that is already gone is neither counted nor a problem, and two records for the same day are harmless.
- [Sizes are apparent sizes] → Assets duplicated through hard links would be counted twice. Saved pages don't use hard links, so the total is close to the space freed.

## Migration Plan

1. Revision `0011` adds `inbox_prunes`. `init_db` applies it on the next `import`, `serve` or `inbox prune`.
2. Hand [parser-impact.md](parser-impact.md) to the maintainer of each out-of-tree parser that names disposable companions (D8). Until a parser adopts `discardable`, prunes run but remove nothing for its files.
3. Optionally preview with `jobhunt inbox prune --dry-run`.
4. Rollback: `alembic downgrade 0010_baseline` drops the table (copy the database first, as for any downgrade). Removed companions can't be restored.
