## 1. Rename to `jobhunt` (D13)

- [x] 1.1 `git mv src/jobchecker src/jobhunt`. Update `pyproject.toml` (name, console script `jobhunt = "jobhunt.cli:main"`, description), every `jobchecker` import in `src/` and `tests/`, the CLI `prog` and its help text, and the module docstrings. Delete `src/jobchecker.egg-info`, run `venv/bin/pip uninstall -y jobchecker`, then reinstall. Verify that `venv/bin/jobhunt --help` works, that `venv/bin/jobchecker` no longer exists, and that `pytest` passes.
- [x] 1.2 Rename the env vars to `JOBHUNT_DB_URL`, `JOBHUNT_INBOX` and `JOBHUNT_TEST_PG_URL`, and the default database to `sqlite:///data/jobhunt.db`, with no fallbacks. Verify with a CLI test that `JOBHUNT_DB_URL` is honored and the default path is `data/jobhunt.db`, and that `JOBCHECKER_TEST_PG_URL=... pytest` no longer enables the Postgres tests.
- [x] 1.3 Update CLAUDE.md (title and purpose wording, the package path, commands, env vars, Postgres example database names `jobhunt` and `jobhunt_test`) and run `git remote set-url origin https://github.com/janedoe-example/jobhunt.git`. Verify that `git remote -v` shows the new URL, that `git ls-remote origin` succeeds, and that `grep -rIi jobchecker . --exclude-dir={venv,inbox,.git,.claude,archive}` returns nothing.

## 2. Dependencies and packaging

- [x] 2.1 Add `flask>=3`, `alembic>=1.13`, `markdown-it-py>=3`, `pypdf>=4` and `python-docx>=1.1` to `pyproject.toml`. Add `[tool.setuptools.package-data]` for `web/templates/**`, `web/static/**` and `migrations/**` (D2). Verify that `venv/bin/pip install -e ".[dev,postgres]"` succeeds and that `venv/bin/python -c "import flask, alembic, markdown_it, pypdf, docx"` works.

## 3. Schema migrations (`migrate.py`, `migrations/`)

- [x] 3.1 Create the in-package Alembic environment, with `env.py` taking its connection from `config.attributes["connection"]` and setting `render_as_batch=True`. Add a repo-root `alembic.ini` for development (D5). Verify that `venv/bin/alembic history` runs.
- [x] 3.2 Write `0001_baseline`, creating `postings`, `captures` and `posting_snapshots` exactly as the current `create_all` does. Verify with a test that upgrading an empty database to `0001` and then running `compare_metadata` against the scraped tables shows no differences.
- [x] 3.3 Implement `migrate.py` and switch `init_db` to it: stamp `0001` when `postings` exists without `alembic_version`, then upgrade to head. Verify that the existing test suite still passes on SQLite, and on Postgres with `JOBHUNT_TEST_PG_URL` set. Also verify with a new test that a database built with the first release's `create_all` and holding imported data is stamped and upgraded, and that its postings, snapshots and captures are unchanged ("Pre-versioning database" scenario).

## 4. User-data tables and writers (`db.py`, `userdata.py`)

- [x] 4.1 Define the D4 user tables in `db.py` and write `0002_user_data`, which creates them and seeds `dismiss_reasons` with the eight default reasons. Verify with a test that `compare_metadata` against the full `db.metadata` shows no differences after upgrading to head, on both databases.
- [x] 4.2 Implement the shared name-key function, plus tag, skill and company get-or-create by key in `userdata.py`. Verify with tests that ` ML ` reuses `ml`, and that two different-case names never create duplicates.
- [x] 4.3 Implement the triage writers in `userdata.py`: set and clear the interest and fit ratings (validated to 1-5), save notes, and add and remove tags. Verify with tests for the rating, clearing, tag reuse and no-duplicate-tag scenarios.
- [x] 4.4 Implement dismiss (one or more reasons, an optional comment, at most one open dismissal) and restore (sets `restored_at` and keeps the row). Also implement adding a custom reason. Verify with tests for the dismiss, restore and re-dismiss history scenario.
- [x] 4.5 Implement skill marks (quote with whitespace collapsed, `snapshot_id`, remove), skill level set and clear, and the found-in-current-description check (D7). Verify with tests for marking, the description-changed "not found" case and level propagation across postings.
- [x] 4.6 Add the "user data survives re-import" test: import a synthetic page, add triage data, re-import a changed synthetic page, then assert that every user table is unchanged. Verify that it passes on both databases.

## 5. Read models (`queries.py`)

- [x] 5.1 Implement the posting list query: latest snapshot per posting with outer-joined triage, open dismissal, tags and application status. Support text search (escaped `ilike`), the tag, minimum-interest, unrated, workplace, application-status and dismissed filters, and the four sort orders (D11). Verify with tests covering each filter, the combined search-and-filter scenario and the default hiding of dismissed postings, on both databases.
- [x] 5.2 Implement the posting detail read model (latest snapshot, capture list, snapshot list, triage, dismissal history, marks with found flags, application) and the snapshot diff (changed fields plus a `difflib` line diff of `description_text`). Verify with tests for the detail of a stored posting, an unknown job ID returning None, and the edited-description diff.
- [x] 5.3 Implement the skills page query (level, postings marking the skill, how many of them have interest of 4 or more). Verify with a test for the 3-postings, 2-high-interest scenario.

## 6. Web app skeleton (`web/`, `cli.py`)

- [x] 6.1 Create `create_app(engine, inbox, documents_dir)`, the base layout with navigation (Postings, Applications, Companies, Skills, Insights), `app.css` with the `.src-scraped`, `.src-user` and `.src-derived` styles, vendored `htmx.min.js`, and a 404 page. Verify with a test-client test that `/` renders and that an unknown URL returns 404.
- [x] 6.2 Implement the Host and Origin guard (D6). Verify with tests: a wrong `Host` gets 403, a cross-origin POST gets 403 with no data change, a POST with neither `Origin` nor `Referer` gets 403, and a same-origin POST succeeds.
- [x] 6.3 Add the `serve` subcommand, with `--host`, `--port`, `--db`, `--inbox`, `--documents` and `--debug`, environment defaults shared with `import`, `init_db` at startup, the address and documents path printed, and a warning for a non-loopback host (D9). Verify with tests: argument parsing and defaults, the warning printed for `--host 0.0.0.0`, and a fresh database file created with the full schema.

## 7. Browsing postings

- [x] 7.1 Build the posting list page with filter controls bound to query parameters, htmx list refresh with `hx-push-url`, and original-posting links that open in a new tab. Verify with test-client tests: the default list order, a filtered URL returning the expected rows, and every row containing a `target="_blank"` link to its canonical URL.
- [x] 7.2 Build the posting detail page: scraped fields, the sanitized description, first and last seen, the captures list with downloads, and the original-posting link. Verify with tests: the page content for a synthetic posting, and a capture download whose bytes match the original file.
- [x] 7.3 Build the snapshot history and diff view. Verify with tests: a diff is offered and renders for a posting with two snapshots, and no diff action appears for a posting with one.
- [x] 7.4 Build the import action and report page, reusing `discover` and `import_files` (D10). Verify with tests: a temp inbox holding one new and one unrecognised synthetic file produces one `new` row (with detail and original-posting links) and one `rejected` row with its reason, both files are moved, and a missing inbox shows an error.
- [x] 7.5 Add the Insights placeholder page and the hidden "Model says" panel slot on the detail page (D3). Verify with a test that `/insights` explains that no analyses exist.

## 8. Triage UI

- [x] 8.1 Add the rating, tag (with existing-tag suggestions) and markdown notes controls as htmx fragments on the detail page and the list rows. Notes are rendered with `markdown-it-py` with HTML disabled (D7). Verify with test-client tests: rating, clearing, tag add and remove, and the `**Ask** about <b>visa</b>` rendering scenario.
- [x] 8.2 Add dismiss (reason checkboxes, adding a reason, a comment), restore, and the dismissal history on the detail page. Verify with test-client tests for the dismiss and restore scenarios and their effect on the default list.
- [x] 8.3 Add `marks.js` (selection -> "Mark skill" form; highlighting quotes from the embedded JSON), the marks list with "not found in current description" labels, and skill level controls. Verify with test-client tests for creating and removing a mark through the endpoint and the not-found label. Also manually check, in a browser against imported real captures, that highlighting and selection work.
- [x] 8.4 Build the skills page. Verify with a test-client test for the counts scenario.

## 9. Applications

- [x] 9.1 Implement the application writers in `userdata.py`: start from a posting (copy title, company and URL, one per posting), create manually, link a manual application to an unclaimed posting, edit fields, next action and compensation notes. Verify with tests for the one-per-posting, manual and link-later scenarios.
- [x] 9.2 Implement events (add with date, kind and note; delete) and `recompute_status`. Verify with tests for the progressing, back-dated and deleting-a-mistake scenarios, and that the cached status always equals a recomputation from events.
- [x] 9.3 Build the application page (fields, event timeline, add-event form, next-action editing with a "due" highlight) and the start-application action on posting detail. Verify with test-client tests: starting from a posting, the overdue highlight, and the posting row showing the status.
- [x] 9.4 Build the applications board (open statuses in pipeline order, collapsible closed group, next-action list sorted by due date, links to the original posting or the manual URL). Verify with a test-client test for the board grouping scenario.

## 10. Documents (`documents.py`)

- [x] 10.1 Implement the content-addressed store (temporary file then rename, `<sha[:2]>/<sha>`) and text extraction for PDF, DOCX, TXT and MD with `unsupported` and `failed: ...` outcomes (D8). Verify with tests using PDF and DOCX files generated in the test: deduplication of identical bytes, byte-identical read-back, extracted text, `.png` stored as unsupported, and a corrupt PDF stored as failed.
- [x] 10.2 Build the upload form (kind, label, 25 MB limit), the documents list, the document page (extracted text, linked applications, "file missing" state), the download with the original filename, and linking and unlinking from the application page. Verify with test-client tests for the upload-a-CV, same-file-twice, unsupported-type and one-CV-two-applications scenarios.

## 11. Companies and contacts

- [x] 11.1 Implement company and contact writers (company by key; contact with emails, role, profile URL, notes, optional company; link and unlink a contact to an application) and the company page query, matching postings and applications by key in Python (D4). Verify with tests on both databases for the company page and recruiter contact scenarios.
- [x] 11.2 Build the companies list, company page, contact forms and contact display, with `mailto:` links and http/https/mailto-only URL rendering (D7). Company names on postings and applications link to the company page, or offer to create one. Verify with test-client tests: a contact email renders as a `mailto:` link, and a `javascript:` URL renders as plain text.

## 12. End-to-end check and docs

- [x] 12.1 Copy `inbox/` to the scratchpad, run `jobhunt serve --inbox <scratch>/inbox --db sqlite:///<scratch>/e2e.db --documents <scratch>/docs`, import through the browser, then triage a posting, mark a skill, start an application with an event and a document, and add a company contact. Never point it at the real `inbox/` during the check. Verify that every page renders and that a second import reports the postings as `unchanged`, with the user data intact.
- [x] 12.2 Run the full suite on SQLite, and on Postgres with `JOBHUNT_TEST_PG_URL` set. Verify that all tests pass on both.
- [x] 12.3 Update `CLAUDE.md`: the `serve` command and its options, the `web/`, `userdata.py`, `queries.py`, `documents.py` and `migrations/` layout, the three data kinds and their writers, how to add a migration, and "back up `data/` (database and documents)". Verify that the documented commands run as written.
- [x] 12.4 Tell the user how to rename the local folder and recreate the venv (design Migration Plan step 4). Don't do it from inside the session. Verify that the instructions are in the final summary for the change.
