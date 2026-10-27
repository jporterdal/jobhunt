## 1. Preparation

- [x] 1.1 Back up `data/` (database and documents) to a dated folder outside the repository, and verify that the copy's database opens read-only and has the same posting count as the original
- [x] 1.2 Reword in place, as an editorial change with no delta: rename the three requirement headers that name the site to "One posting record per source and external ID" (`posting-storage`), "Postings always link to their original page" (`web-interface`) and "Applications without an imported posting" (`application-tracking`), and reword the Purposes of `capture-import`, `posting-storage`, `web-interface` and `application-tracking` in source-neutral terms. Verify that `openspec validate separate-capture-parser --strict` shows no "Archive would refuse" notice and `openspec validate --specs` passes
- [x] 1.3 Add the one archive that is only about the parser (named in the private notes, `FUTURE_CHANGE.md` section 4) to the archives `prepare-public-release` moves, naming it only in private notes, not in that change's artifacts. Verify that its design's D10 points to the private list

## 2. Parsers and sanitizing

- [x] 2.1 Add `src/jobhunt/sanitize.py` (`clean_html`, `html_to_text`) moved from `extract.py`, with the `http`/`https`/`mailto` link rule (design D6). Verify with `tests/test_sanitize.py`: unsafe markup, a list with emoji, nested paragraphs, a relative link dropped, and idempotence over every fixture description
- [x] 2.2 Add `src/jobhunt/parsers/__init__.py`: `CaptureFile`, `ParsedPosting`, `Rejected`, the `Parser` protocol and `installed()` (design D3), plus `tests/fakes.FakeParser`. Verify with `tests/test_parsers.py`: loading from a faked entry-point list, sorting by name, refusing duplicate names, and a failing entry point reported without stopping the others
- [x] 2.3 Add the built-in parser `src/jobhunt/parsers/posting_file.py` and register it in `pyproject.toml` under `jobhunt.parsers`, then run `pip install -e ".[dev,postgres]"`. Verify that `parsers.installed()` lists `posting-file`, and that `tests/test_posting_file.py` covers each scenario of "Built-in posting file format", plus `captured_at`, the precision default and an unknown top-level field
- [x] 2.4 Write about six invented posting files in `tests/fixtures/postings/` (design D14: two sources, a list description, emoji, unsafe markup, missing optional fields, a changed re-capture), and verify that each one parses with the built-in parser

## 3. Schema and the conversion revision

- [x] 3.1 Change `db.py`: an integer `postings.job_id` with `source`, `external_id` and their unique constraint; integer `job_id` foreign keys in the 11 referencing tables; snapshot `details_json`, `volatile_json` and `parser` replacing the site columns and `parser_version`; capture `raw_gz` and `parser` replacing `html_gz` and `page_type` (design D1, D2, D7, D8). Verify that `db.metadata` creates cleanly on an empty SQLite database
- [x] 3.2 Write revision `0010_baseline` after `0009_tailored_cv` (design D9), with its `downgrade()` refusing shared external IDs. Verify that `tests/test_migrate.py`'s metadata comparison passes on SQLite and Postgres, and that an upgrade, downgrade and upgrade again on an empty database succeeds
- [x] 3.3 Add a data test that builds a `0009` database with at least one row in each of the 11 referencing tables (and a hand-made application and a links job with null `job_id`), upgrades it, and checks every row's new key, each posting's source and external ID, the moved details and the recomputed fingerprints. Check also that the revision's frozen fingerprint equals `store.fingerprint` for the same values. Verify that it passes on SQLite and Postgres

## 4. Store and importer

- [x] 4.1 Rewrite `store.py` for `ParsedPosting`: look postings up by source and external ID, assign keys through the database, sanitize and derive text (D6), canonicalize details, use the new fingerprint (D7), record the parser on captures and snapshots, and use `captured_at`. Verify with `tests/test_store.py` against each `posting-storage` scenario (new, look-alike, same external ID from two sources, unchanged with only volatile details changed, changed detail, out-of-order capture times, retained bytes)
- [x] 4.2 Rewrite `importer.py`: `discover` with companions and download-metadata files (D5), trying every parser (D4), moving with companions and renaming collisions, and a report with source, external ID and URL. `importer.py` and `store.py` must no longer import `extract` or `dates`. Verify with `tests/test_importer.py` and `tests/test_reimport.py`, rewritten over `FakeParser` and posting files, covering each `capture-import` scenario (two parsers for HTML, a failing parser, not recognised, recognised but unusable, two accepting, companions, collisions, mixed batch, a single file in place, a duplicate)

## 5. The rest of the app

- [x] 5.1 Change `job_id` from `str` to `int` throughout `queries.py`, `userdata.py`, `recommend.py`, `tailor.py`, `enrich/` and `web/`, with `<int:job_id>` routes. Verify that `pytest` passes on SQLite, and that a non-numeric or unknown posting URL gives 404
- [x] 5.2 In `queries.py`: details and volatile details in the posting detail read model, `DIFF_FIELDS` as the core fields plus detail keys, and an exact external-ID match in the list search (D12). Verify with `tests/test_queries.py`: searching by external ID, a diff that shows a changed detail, and the detail read model's source, external ID and details
- [x] 5.3 Update the templates and CSS (D11): the `original_link` macro and class in all 14 templates, "Original posting ↗" labels, "imported" scraped-data labels, Source, External ID and the details on the detail page, and the hand-made application hint. Verify with `tests/test_web.py` (the label on the list, detail, board, company, Insights, CV and import-report pages) and with a grep showing that `src/jobhunt/web/` doesn't contain the site's name
- [x] 5.4 Load parsers once in `create_app` and in `cli.py` and pass them to the importer, and rewrite the import help text in source-neutral terms. Verify with `tests/test_web.py`'s "Importing two pages" scenario (one posting file, one unrecognised file) and with `jobhunt import --help`
- [x] 5.5 Make `conftest.add_posting` import an invented posting file and return the integer key, and replace literal posting IDs across the tests. Verify that the full suite passes on SQLite and with `JOBHUNT_TEST_PG_URL` on Postgres

## 6. The private parser package

- [x] 6.1 Ask the user for the private package's name, location and parser name. Create its repository with `pyproject.toml` depending on `jobhunt` and registering the parser under `jobhunt.parsers`, then install both packages editable in this venv. Verify that `parsers.installed()` lists both parsers
- [x] 6.2 Port `extract.py` and `dates.py` into the private parser, as design D13 and the private notes describe, with the source taken from the site's host without `www.`. Move the synthetic and private fixtures, `test_extract`, `test_dates`, `test_golden` and the import cases that use its files into it. Verify that its suite passes against the public package
- [x] 6.3 Move the `posting-extraction` spec unchanged into the private repository's `openspec/specs/`, add an import capability for its files with the three requirements removed from `capture-import` here, and write its `CLAUDE.md` with the capture workflow from this repository's `CLAUDE.md`. Verify that `openspec validate --specs` passes there
- [x] 6.4 Delete from the public tree `extract.py`, `dates.py`, `PARSER_VERSION`, `tests/fixtures/synthetic/`, `tests/fixtures/private/`, and the moved tests. Verify that the public suite passes with only the built-in parser installed, and that a case-insensitive grep for the site's name in `src/` and `tests/` finds nothing

## 7. The user's database

- [x] 7.1 Upgrade a copy of `data/jobhunt.db` (`0008` → `0009` → `0010_baseline`) with `--db` pointing at the copy. Verify that row counts per table match the original, that every foreign key's posting has the same external ID as before, that the private fingerprint check (D13) passes for every snapshot, and how many stored descriptions have a non-http link (report the number to the user). Then open `jobhunt serve --db <copy>` with the user on a posting, the board and Insights
- [x] 7.2 With the user's go-ahead, upgrade the real database and repeat 7.1's checks against it

## 8. Squash the migration chain

- [x] 8.1 Confirm that `migrate.current_revision` on `data/jobhunt.db` is `0010_baseline`, and ask the user whether to tag the current commit (for example `pre-baseline`) so that older backups can still be upgraded. Verify the tag exists if one was wanted
- [x] 8.2 Replace `versions/0001`–`0010` with a single `0010_baseline.py` (`down_revision = None`, autogenerated against an empty database, then reviewed). Drop the pre-versioning adoption from `migrate.py`, and add `migrate.TooOld` with exit 2 and the spec's message in the CLI. Delete `tests/test_upgrade_profile.py`, `tests/profile_0007.py` and the old-revision cases, and add the two refusal cases to `tests/test_migrate.py`. Verify that the full suite passes on SQLite and Postgres, and that `jobhunt serve` on the real database starts with no upgrade (the revision is unchanged, and the database file's checksum is unchanged after a read-only page load)

## 9. Documentation and wrap-up

- [x] 9.1 Update `CLAUDE.md`. The status line; the architecture (`parsers/`, `sanitize.py`, no `extract.py` or `dates.py`); "Decided so far" (entry-point parsers, reinstalling after an entry-point change); the scraped data kinds (source, external ID, details); a source-neutral "Getting postings in" (inbox, installed parsers, the posting file format) in place of the capture workflow; the four-data-kinds note on the import report; "Schema migrations" (the baseline; `--rev-id 0011` next); and "Data and backups" (databases older than the baseline need the tagged commit). Verify with a grep that `CLAUDE.md` mentions neither `extract.py`, `dates.py`, `PARSER_VERSION` nor the site's name
- [x] 9.2 Move section 4's private notes into the private package's own docs, then delete section 4 and its index line from `FUTURE_CHANGE.md`. Verify that the notes are in the private package and that the file's remaining sections are intact
- [x] 9.3 Run `openspec validate separate-capture-parser --strict` and `openspec validate --specs`, and a case-insensitive grep for the site's name over `openspec/changes/separate-capture-parser/`. Verify that all are clean before archiving
