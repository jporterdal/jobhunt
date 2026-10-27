## Context

See proposal.md, "Why". The motivation is not repeated here.

Current state:

- **Tables.** `postings`, `captures` and `posting_snapshots` hold scraped data only, defined in SQLAlchemy Core in `db.py`.
- **Schema setup.** `init_db` calls `metadata.create_all()`. The earlier design (D6, Risks) said the first change that needs schema evolution must introduce migrations, and this is that change.
- **Writers.** `store.py` writes scraped data. `importer.py` handles discovery, per-file transactions and file moves, and returns `FileResult`s. `cli.py` has a single `import` subcommand.
- **Description.** `description_html` is already sanitized at import time (D4 of the earlier design). It uses an allowlist of `p br ul ol li strong b em i u a h1-h6`, with `href` as the only attribute.
- **Tests.** An `engine` fixture runs against a temporary SQLite file and, when `JOBCHECKER_TEST_PG_URL` is set, against a throwaway Postgres schema selected through `search_path`.
- **Data.** None is stored locally yet; nine captures are waiting in `inbox/`.

Constraints carried over from CLAUDE.md:

- SQL must be portable between Postgres and SQLite.
- Re-collection must never overwrite user metadata.
- History is preserved rather than overwritten.
- Every posting shown links to its original URL.

## Goals / Non-Goals

**Goals:**

- The three data kinds (scraped, user-authored, derived) are separated in both the code and the schema, and each kind has exactly one writer.
- The web interface is server-rendered and needs no JavaScript toolchain.
- The schema can evolve safely from this change on, on both databases.
- The derived-data layout is reserved now, so the Ollama phase only adds tables and UI panels and doesn't need to restructure anything.

**Non-Goals:**

- Creating the derived-data tables, or calling any model.
- Charts or statistical analysis, beyond the counts on the skills page.
- Deleting applications, documents, companies or contacts. Editing their fields is supported; deleting events and links is supported as specified.
- Full-text search indexes. The data set is hundreds of rows, so pattern matching is enough.
- Multiple users, authentication, or HTTPS.
- Extracting the job site's company slug. Companies are matched by name for now (see Open Questions).

## Decisions

### D1. Flask + Jinja2 + htmx, server-rendered

- **Flask** is synchronous, which matches the existing synchronous SQLAlchemy Core engine. It is small and brings Jinja2 with it.
- **htmx** covers star ratings, tag chips, inline note editing, event adding and filtering. Each of these posts a form and swaps in the HTML fragment the server returns. It is vendored as one file under `web/static/`, so it works offline with no CDN.
- **One small vanilla script** (`marks.js`) handles selecting text and highlighting quotes (D7). That is the only custom JavaScript.

Alternatives considered:

- **FastAPI.** Its async model and Pydantic models add nothing here, and async gives no benefit with a sync engine.
- **A Streamlit or notebook UI.** These are good for the later analysis, but awkward for editing records and stable URLs.
- **A React or Vue single-page app.** It would need a build toolchain and a JSON API layer, which is too much for a single-user local tool.

### D2. Package layout and where code lives

```
src/jobhunt/
    db.py           + user-data tables (scraped tables unchanged); init_db -> migrations
    migrate.py      programmatic Alembic: upgrade, stamp pre-versioning DBs
    migrations/     Alembic env.py + versions/ (shipped as package data)
    userdata.py     all writes of user-authored data (no HTML, no Flask)
    queries.py      read models: posting list/filter, detail, board, company page (no Flask)
    documents.py    content-addressed file store + text extraction (no Flask)
    web/
        __init__.py create_app(engine, inbox, documents_dir) - app factory
        guard.py    Host/Origin checks (D6)
        postings.py list, detail, diff, capture download, import action
        triage.py   ratings, tags, notes, dismissals, skill marks, skills page
        applications.py  applications, events, board, documents, companies, contacts
        templates/  Jinja2 (base layout, pages, htmx fragments)
        static/     htmx.min.js, marks.js, app.css
```

- **Separation.** The rule from the earlier design ("`extract.py` has no DB code, `store.py` has no HTML code") extends here. `userdata.py`, `queries.py` and `documents.py` know nothing about HTTP and are tested directly. Route modules stay thin.
- **Writers.** `store.py` remains the only writer of scraped tables. `userdata.py` is the only writer of user tables. This gives the "one writer per kind" rule from the proposal a concrete home.
- **Packaging.** `pyproject.toml` gains `[tool.setuptools.package-data]` for `web/templates/**`, `web/static/**` and `migrations/**`.

### D3. Three data kinds, and the reserved derived layout

```
SCRAPED (store.py)          USER-AUTHORED (userdata.py)        DERIVED (later change)
postings                    posting_triage, tags, posting_tags  posting_enrichments
captures                    dismiss_reasons, posting_dismissals analyses
posting_snapshots           posting_dismissal_reasons
                            skills, posting_skill_marks
                            companies, contacts, contact_emails
                            applications, application_events
                            documents, application_documents,
                            application_contacts
```

The derived tables are **not created** in this change. Their intended shape is recorded here so the UI keeps room for them:

- `posting_enrichments(id, job_id, snapshot_id, model, prompt_version, created_at, output_json)` will hold per-posting extraction. Keying it by snapshot records exactly which description text the model read. Keying it by model and prompt version allows side-by-side comparison, which is the same idea as `parser_version`.
- `analyses(id, kind, scope_json, model, prompt_version, created_at, output_markdown, output_json)` will hold analyses across many postings, shown in Insights.
- A suggestion the user accepts is copied into user-authored tables (for example a `posting_skill_marks` row). Derived rows are never edited, so they can always be regenerated.

In the UI, three CSS classes (`.src-scraped`, `.src-user`, `.src-derived`) give each kind a distinct look. The posting detail page reserves a "Model says" panel, which stays hidden until derived data exists.

### D4. User-data schema

Every table uses `Integer` autoincrement ids, `UTCDateTime` timestamps and `Date` for user-entered dates. Columns are portable types only, with no JSON or array types.

```
posting_triage      job_id PK FK->postings, interest SMALLINT NULL, fit SMALLINT NULL,
                    notes TEXT NULL, updated_at
tags                id, name, key UNIQUE                      -- key = casefolded, trimmed, spaces collapsed
posting_tags        job_id FK, tag_id FK, created_at, PK(job_id, tag_id)
dismiss_reasons     id, label, key UNIQUE, position           -- defaults seeded by the migration
posting_dismissals  id, job_id FK, dismissed_at, comment NULL, restored_at NULL
posting_dismissal_reasons  dismissal_id FK, reason_id FK, PK(both)
skills              id, name, key UNIQUE, level NULL ('have'|'missing'|'learning'), updated_at
posting_skill_marks id, job_id FK, skill_id FK, quote TEXT, snapshot_id FK, created_at
companies           id, name, key UNIQUE, website_url, careers_url, notes, created_at, updated_at
contacts            id, name, company_id FK NULL, role, profile_url, notes, created_at, updated_at
contact_emails      id, contact_id FK, email
applications        id, job_id FK NULL UNIQUE, title, company, url NULL,
                    status, status_date,                     -- cached, see below
                    next_action NULL, next_action_due DATE NULL, compensation_notes NULL,
                    created_at, updated_at
application_events  id, application_id FK, kind, event_date DATE, note NULL, created_at
documents           id, sha256, label, kind, original_filename, media_type, size_bytes,
                    uploaded_at, text_content NULL, text_status   -- 'extracted'|'unsupported'|'failed: ...'
application_documents  application_id FK, document_id FK, PK(both)
application_contacts   application_id FK, contact_id FK, PK(both)
```

- **Dismissal history.** A posting is dismissed when it has a `posting_dismissals` row with `restored_at` NULL. Restoring fills in `restored_at` and never deletes the row, so the full history stays available for preference analysis. `userdata.py` enforces "at most one open dismissal" inside the same transaction, rather than with a partial index, which keeps the DDL simple.
- **Nullable unique `applications.job_id`.** Both Postgres and SQLite treat NULLs as distinct in a unique constraint. So "at most one application per posting" holds, and any number of manual applications can exist.
- **Cached `status`.** `status` and `status_date` are recomputed by one function, `userdata.recompute_status`, in the same transaction as every event insert or delete. The board and list filters then need no window functions or correlated subqueries. Events stay the source of truth, and the cache can be rebuilt from them. With no events, the status is `interested`.
- **Company name on applications.** An application keeps its own `title` and `company` text, copied from the posting when it is started from one. Manual applications therefore need nothing else, and a later re-capture never changes them.
- **Company matching.** Applications and postings are matched to `companies.key` in Python, using the same key function as tags and skills. SQLite's `lower()` only folds ASCII. At hundreds of rows, loading the distinct company names from the latest snapshots and matching them in Python is cheap and behaves the same on both databases.

### D5. Migrations with Alembic, run in-process

- **Where it lives.** The Alembic environment ships inside the package (`jobhunt/migrations/`) and is driven programmatically by `migrate.py`. `init_db(engine)` keeps its signature, so callers and the test fixture don't change. It now:
  1. Opens a connection and hands it to Alembic through `config.attributes["connection"]`. This is how the Postgres test schema chosen by `search_path` is respected.
  2. Stamps the baseline revision when `postings` exists but `alembic_version` does not, which covers databases created by the first release.
  3. Upgrades to `head`.
- **Revisions.**
  - `0001_baseline` creates the three scraped tables exactly as `create_all` produced them.
  - `0002_user_data` creates the user tables (D4) and seeds `dismiss_reasons`.
- **SQLite.** `env.py` sets `render_as_batch=True`, so that future `ALTER`s work on SQLite through batch mode.
- **Developer workflow.** A repo-root `alembic.ini` points at the package's migrations, so `alembic revision --autogenerate -m ...` works during development. A test asserts that the upgraded schema matches `db.metadata` (Alembic's `compare_metadata` finds no differences) on both databases. This catches a forgotten migration.
- **Alternatives considered.**
  - Keep `create_all` and add hand-written `ALTER` statements: not portable, and there is no version tracking.
  - Hand-rolled version table: reinvents Alembic poorly.

### D6. Request safety without authentication

The interface has no authentication, but other sites open in the same browser should not be able to change its data. A `before_request` hook in `web/guard.py` adds two checks:

- **Host check, every request.** The `Host` header must be one of the configured `host:port` pairs. When bound to loopback, that is `127.0.0.1`, `localhost` and `[::1]` at the bound port. This blocks DNS-rebinding reads and writes.
- **Origin check, non-GET/HEAD requests.** `Origin`, or `Referer` when `Origin` is missing, must match an allowed origin. A request with neither header is rejected. Browsers send `Origin` on form posts and fetch/htmx calls, so legitimate use is unaffected.

GET handlers never write. Downloading a capture or document is a GET.

CSRF tokens were considered. They add per-form plumbing, and the origin check gives equivalent protection for a single-origin local app.

### D7. Rendering descriptions, highlights and notes

- **Descriptions.** `description_html` is rendered with `|safe`, because it was already reduced to the allowlist at import time. Templates never mark any other stored text as safe.
- **Skill highlights, client side.** The detail page embeds the posting's mark quotes as JSON. `marks.js` walks the description's text nodes and wraps whitespace-normalized, case-insensitive matches in `<mark>`. On text selection, it shows a small "Mark skill" form that posts the selected text, with whitespace collapsed, together with a skill name. Server-side highlighting was rejected: it would mean re-parsing and re-serializing the sanitized HTML on every view, and it is no more robust.
- **"Not found in current description".** This is decided on the server. The quote and the latest snapshot's description are both reduced to text with whitespace collapsed and casefolded (BeautifulSoup `get_text(" ")` over `description_html`), and checked for containment. That matches what the user could select.
- **Quote snapshot.** A mark stores the `snapshot_id` it was made on, so the quote can still be shown in context after a description changes.
- **Notes.** Notes are rendered with `markdown-it-py` in `commonmark` mode with `html` disabled, so raw HTML is escaped. Its link validation rejects `javascript:` URLs.
- **Escaping.** Every URL the user enters (company, contact, manual application) goes through autoescaping. Only `http`, `https` and `mailto` URLs are rendered as links; anything else is shown as text.

### D8. Documents: content-addressed folder, metadata in the database

- **Location and layout.** Files live under a documents directory set by `--documents DIR`, `$JOBHUNT_DOCUMENTS`, or the default `data/documents`. Each file is stored as `<dir>/<sha256[:2]>/<sha256>`, written to a temporary file and renamed into place. Identical uploads therefore share one file, and a partial write never appears under a real hash.
- **Metadata.** The `documents` row carries the original filename, the media type (guessed from the extension and the browser's report) and the size. The download sets `Content-Disposition` to the original filename.
- **Upload limit.** Flask's `MAX_CONTENT_LENGTH` is set to 25 MB.
- **Text extraction** (`documents.py`) runs at upload time:
  - `.pdf` uses `pypdf`, `.docx` uses `python-docx`, and `.txt`/`.md` are decoded as UTF-8 with replacement characters.
  - Other types are recorded as `unsupported`.
  - Any extraction exception is caught and recorded as `failed: <message>`, and the upload still succeeds.
  - Both libraries are pure Python. `python-docx` reuses lxml, which is already a dependency.
- **Why a folder and not database blobs** (the captures approach): the files are user documents that can be large and are binary. Keeping them out of the database keeps Postgres and SQLite dumps small. The trade-off is that a backup must include `data/documents/` as well as the database; see Risks.

### D9. The `serve` command

```
jobhunt serve [--host 127.0.0.1] [--port 8000] [--db URL] [--inbox DIR]
                      [--documents DIR] [--debug]
```

- **Defaults.** It shares the `--db` and `--inbox` defaults and environment variables with `import`; these are factored into a shared argparse helper.
- **Startup.** It calls `init_db`, builds the app with `create_app`, and serves it through Werkzeug's server, multi-threaded. `--debug` turns on the reloader and the debugger.
- **Warnings.** It prints a warning for a non-loopback `--host`.
- **Why Werkzeug's server.** It is enough for one local user. A production WSGI server such as waitress or gunicorn would add a dependency without benefit.

### D10. Import from the browser reuses the importer unchanged

`POST /import` calls `discover(inbox)` and `import_files(engine, paths, inbox)`, the same functions the CLI uses. It then renders the returned `FileResult`s in a template that has the same fields as `format_report`, plus links. It runs synchronously, because a batch is a handful of files.

### D11. Search and filtering

- **Latest snapshot.** The "latest snapshot per posting" is a `max(id) GROUP BY job_id` subquery joined back to the snapshots. The triage, open-dismissal and application tables are outer-joined to it.
- **Text search.** SQLAlchemy's `ilike` renders as `ILIKE` on Postgres and as `lower() LIKE lower()` on SQLite, applied to title, company and description text. User input is escaped for `%` and `_`.
- **Tag filter.** This is an `EXISTS` subquery.
- **Query string.** Filters arrive as query parameters, so the URL encodes the list state. htmx updates the list with `hx-push-url`.

### D12. Tests

- **Schema.** The existing `engine` fixture now goes through migrations. A new test builds a database with the first release's `create_all` schema plus data, runs `init_db`, and checks that it was stamped and upgraded with the data intact. Another test asserts that `compare_metadata` reports no differences.
- **Writers and read models.** `userdata.py` and `queries.py` are tested against the `engine` fixture, so they also run on Postgres when it is configured. This includes "re-import leaves user data unchanged", which imports a synthetic fixture, adds triage and an application, then re-imports a changed synthetic page.
- **Web.** Flask test-client tests cover each route and fragment, the guard (bad Host, cross-origin POST, missing Origin), the 404 page, capture download bytes, and the import action against a temp inbox of synthetic pages.
- **Documents.** Small generated PDF and DOCX files are created in the test, so no binary fixtures are committed. The tests cover deduplication, byte-identical download and the unsupported and failed paths.
- **JavaScript.** `marks.js` has no automated tests. Its server half, storing a quote and the found/not-found check, is covered.

### D13. Rename to `jobhunt`, done first, with no compatibility aliases

The rename is the first implementation step. Every new module in this change is then created under `src/jobhunt/` from the start, and the diff for the web work isn't mixed with rename churn.

| Old | New |
|---|---|
| distribution `jobchecker`, package `src/jobchecker/` | `jobhunt`, `src/jobhunt/` (`git mv`, history kept) |
| console script `jobchecker` | `jobhunt` |
| `JOBCHECKER_DB_URL`, `JOBCHECKER_INBOX`, `JOBCHECKER_TEST_PG_URL` | `JOBHUNT_DB_URL`, `JOBHUNT_INBOX`, `JOBHUNT_TEST_PG_URL`; `JOBHUNT_DOCUMENTS` is new (D8) |
| default `sqlite:///data/jobchecker.db` | `sqlite:///data/jobhunt.db` |
| Postgres examples `jobchecker`, `jobchecker_test` | `jobhunt`, `jobhunt_test` |
| `origin` `github.com/janedoe-example/jobchecker.git` | `github.com/janedoe-example/jobhunt.git` |

Notes on scope:

- **No aliases.** No fallback for the old env vars and no old console script. Nothing is stored yet and there is one user, so aliases would be clutter that never gets removed.
- **History stays as written.** The archived first change is not rewritten. The accepted specs don't name the tool, so they need no change.
- **Description text.** The `pyproject.toml` description, the CLI `prog` and its help text, and the module docstrings say "job postings and applications" instead of naming the job site. This doesn't apply where the text really is about the site's pages, as in the parser.
- **Local checkout folder.** Renaming `~/work/jobchecker` to `~/work/jobhunt` is left to the user as the last step. The venv's scripts have absolute paths in their shebangs, so the venv must be recreated after the move. The Claude Code session and its project memory are tied to the folder path too, so it's done outside a session.
- **Outside the repo.** `.claude/settings.local.json` contains an `init-jobchecker-…` hook profile ID that belongs to an external tool. It is left alone, because changing an ID that tool owns could break its hook.

## Risks / Trade-offs

- **Rename leaves stale artifacts.** The old `jobchecker` console script and `jobchecker.egg-info` stay in the venv. → `pip uninstall jobchecker` before reinstalling, and delete the egg-info. A repo-wide `grep -ri jobchecker`, excluding the archive, `venv/`, `inbox/` and `.claude/`, must come back empty.

- **Non-ASCII case-insensitive search differs on SQLite** (`lower()` only folds ASCII). → Accepted for search; a search for "é" in a different case may miss on SQLite. Company, tag and skill matching use Python casefolding (D4), so identity never differs between databases.
- **Quote matching is approximate.** A selection that spans list items, or text the site later reflows, may not be found. → Marks are never lost, only labelled "not found". The quote and its snapshot are kept.
- **Documents live outside the database** → a database backup alone is incomplete. → `serve` prints the documents path at startup, and CLAUDE.md documents "back up `data/`". A missing file is shown as "file missing" on the document page instead of an error.
- **Cached application status could drift** if a future writer bypasses `userdata.py`. → Only `recompute_status` writes it, and a test checks it against a recomputation from events.
- **No authentication.** → Loopback by default, a warning otherwise, and the Host/Origin guard (D6). Anyone with local shell access can already read the database file, so authentication would add little.
- **Development server.** → Fine for one user. Swapping in a production WSGI server later is a change to `serve` alone.
- **Migrations on existing data.** → The baseline stamping path is tested. A downgrade below `0002` drops user tables, so the docs say to copy the database before a downgrade.

## Migration Plan

1. Upgrade the package: `pip uninstall -y jobchecker`, then `pip install -e ".[dev,postgres]"`, which installs the `jobhunt` command and the new dependencies.
2. The next `import` or `serve` run calls `init_db`. It stamps a first-release database as `0001_baseline` and upgrades it to `0002_user_data`. A new database is created at `head`.
3. Rollback: reinstall the previous version. Its `create_all` ignores the extra tables and `alembic_version`, so scraped data keeps working. `alembic downgrade 0001_baseline` removes the user tables, destroying user data, if a clean schema is wanted.

4. After the change is merged, the user renames the local folder outside a Claude Code session (`mv ~/work/jobchecker ~/work/jobhunt`), then recreates the venv (`rm -rf venv && python3 -m venv venv && venv/bin/pip install -e ".[dev,postgres]"`).

There is no stored data locally yet, so the first real run will be a fresh `head` creation.

## Open Questions

- **Company slug.** Should a later parser change extract the job site's company slug and use it, rather than the name, to match companies? Name matching works for now, and `companies` can gain a nullable `site_slug` column in a later migration without changing these specs.
- **Default port.** `8000` may clash with other local tools. It is configurable, and the default can change without affecting anything else.
