## 1. The parser contract (`src/jobhunt/parsers/__init__.py`)

- [ ] 1.1 Document the optional `discardable(path) -> list[Path]` beside `companions` in the `Parser` protocol's comment, and add `parsers.discardable(parser, path)`. It returns the parser's answer intersected with `companions(parser, path)`, without `path` or its `:Zone.Identifier` file, and returns `[]` when the parser has no method or either call raises (D1). Give `tests/fakes.FakeParser` a `discardable_suffixes` argument. Verify with tests for these scenarios:
  - "A parser marks its asset folder"
  - "A path that isn't the parser's companion"
  - "Download metadata is never discardable"
  - a raising `discardable`
  - a parser without the method
- [ ] 1.2 Verify "Import still moves discardable companions": a new `tests/test_importer.py` case shows that `page_files/` (discardable) is moved to `processed/` with `page.html`, and that every existing importer test passes unchanged.

## 2. Schema (`src/jobhunt/db.py`, Alembic `0011`)

- [ ] 2.1 Add the `inbox_prunes` table from D4 (`bytes` as BigInteger) and list it in `OPERATIONAL_TABLES`. Generate revision `0011` against a scratch database at head (CLAUDE.md, "Schema migrations"), review it, and write its `downgrade()`. Verify that `tests/test_migrate.py` passes on SQLite and Postgres, and that `alembic downgrade 0010_baseline` then `upgrade head` round-trips on a scratch database.

## 3. The prune (new `src/jobhunt/prune.py`)

- [ ] 3.1 Add `plan(inbox, parsers)`. It covers `processed/` and `rejected/`, each of which may be missing. It lists the regular files directly inside each, skips the ones that are other files' companions, takes the union of `parsers.discardable` over the installed parsers, keeps only paths that exist, and measures each with `lstat` and `os.walk(followlinks=False)` (D2, D3). Verify with `tests/test_prune.py` cases for:
  - "The inbox itself is untouched"
  - "Parser no longer installed"
  - "Renamed after a name clash"
  - a companion file such as `page.meta` that isn't treated as a file of its own
- [ ] 3.2 Add `run(engine, inbox, parsers, now, stop=None, dry_run=False)`. It re-checks each planned path's parent and name, unlinks links and plain files, `rmtree`s folders (collecting errors with `onexc` from Python 3.12, `onerror` on 3.11), treats `FileNotFoundError` as already gone, and checks `stop` between companions. Unless it is a dry run, it records one `inbox_prunes` row with the resolved inbox path. It returns the removed entries, the totals and the problems. Verify with tests for:
  - "Asset folders are removed, pages kept"
  - "A link to elsewhere" (skipped where symlinks can't be made)
  - "A companion that can't be removed" (skipped as root)
  - "Missing inbox" (recorded with 0 removed)
  - a dry run that removes and records nothing
  - row counts of every captured, user-authored and derived table, unchanged on both backends
- [ ] 3.3 Add `latest(conn, inbox)` and `Pruner(engine, inbox, parsers, interval=24h, clock=...)`, a daemon thread whose loop is a testable `run_once(now)` (prune when no record is newer than `interval`, otherwise do nothing). Its waits are capped at `MAX_WAIT` (1 hour). It prints one line per prune and, after an unexpected error, logs it and waits `MAX_WAIT` (D5). Verify with tests driven by an injected clock for "First start after upgrading", "Restarted within a day" and "Running for days", and a test that `stop()` ends the thread promptly.

## 4. Command line (`src/jobhunt/cli.py`)

- [ ] 4.1 Add the `inbox` command group with `prune [--dry-run]`, taking `_storage_args` (D6). It prints parser load errors as warnings, one line per companion, then the problems and totals. Exit codes are 0, 1 (problems) and 2 (no inbox), and a dry run doesn't open the database. Verify with `tests/test_cli.py` cases for "Dry run", "Pruning by hand resets the schedule" (a run records a prune, and a `Pruner.run_once` an hour later does nothing) and each exit code.
- [ ] 4.2 Start a `Pruner` in `_serve` beside the `Worker`, under the same reloader guard, using the installed parsers and `args.inbox`, and stop and join it in `finally`. Verify with a test that patches `app.run` and checks the pruner thread is started and stopped (follow how the worker start is tested today, if it is), and by running `jobhunt serve` on a scratch inbox and database and seeing the prune line printed once.

## 5. Web (`src/jobhunt/web/postings.py`, `templates/import_report.html`)

- [ ] 5.1 Pass `prune.latest(conn, inbox)` to `import_report.html` from `POST /import` (both the results and the "inbox not found" render). Show when the prune finished, the number of companions and size removed (with the `size` filter) and the problem count, or "Not pruned yet". Share the size formatting with the CLI (D7). Verify with `tests/test_web.py` cases for "The Import page shows the latest prune" and "Never pruned", and that `tests/test_demo.py` still passes.

## 6. Parsers outside this repository

- [ ] 6.1 Write `docs/parsers.md`, the guide for parser authors, for someone starting from scratch. It covers:
  - the contract (pointing at the `capture-import` spec rather than repeating it), with an invented example format;
  - a parser kept in its own repository and installed editable into the same venv (generic, naming no site);
  - testing a parser against jobhunt;
  - when `pip install -e` is needed again (entry points only);
  - a contract changelog whose first entry is this change ("optional: `discardable(path)`", linking [parser-impact.md](parser-impact.md)).

  Point the README's plug-in paragraph and `docs/architecture.md`'s parser paragraph at it. Verify that every method and rule the brief states appears in the guide or the spec, and that `jobhunt privacy-check --staged` passes.
- [ ] 6.2 Tell the user the brief is ready to hand to whoever maintains each out-of-tree parser, and give them the path to [parser-impact.md](parser-impact.md). Don't edit any parser repository from this change. Verify by re-reading the brief against the final `parsers/__init__.py` and the spec, and updating it if the implementation moved. Once the user reports the parser updated, `jobhunt inbox prune --dry-run` on their inbox should list asset folders only. Only the totals are reported here, and a real prune is the user's call.

## 7. Docs and checks

- [ ] 7.1 Update CLAUDE.md:
  - "Getting postings in": discardable companions and the prune, and "nothing is deleted" now applies to the import only
  - the four data kinds: `inbox_prunes` operational, written only by `prune.py`
  - Architecture: `prune.py`
  - Commands: `jobhunt inbox prune`
  - `serve`'s second thread

  Update the README's import paragraph (the first `serve` prunes the existing pile; preview with `--dry-run`). Remove section 4 from `FUTURE_CHANGE.md`, and its index line. Verify by reading the edited sections, and with `grep -n "nothing is deleted"` showing no stale claim.
- [ ] 7.2 Run the full suite on SQLite and Postgres (`JOBHUNT_TEST_PG_URL=… pytest`), `ruff check`, `openspec validate prune-discardable-companions --strict` and `jobhunt privacy-check --staged`, and verify that all pass.
