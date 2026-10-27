## Why

Saved postings can now be imported into the database, but the only way to see them is to query it by hand. Nothing exists yet for the user's own data: interest, fit, whether they applied, which CV they sent, who they spoke to. The project exists to combine postings with that data. A local web interface is where the user will review postings and record their decisions. Those recorded decisions are also what the later analysis and Ollama phase will read, so they need to start building up now.

The project is also renamed from `jobchecker` to `jobhunt`. It now does more than check postings: it tracks applications that have no posting, the documents sent and the people contacted. The GitHub repository has already been renamed.

## What Changes

- **BREAKING: rename the project to `jobhunt`.** This covers the distribution name, the Python package (`src/jobhunt/`), the command (`jobhunt import`, `jobhunt serve`), the environment variables (`JOBHUNT_DB_URL`, `JOBHUNT_INBOX`, `JOBHUNT_TEST_PG_URL`), the default database file (`data/jobhunt.db`), the git remote URL, and the references in CLAUDE.md and the docs. The old names get no aliases: there is one user and no stored data yet.
- **Add `jobhunt serve`**, a local Flask web app bound to `127.0.0.1`. It renders pages on the server, uses htmx for inline edits and needs no JavaScript build step. Every posting shown links to its original URL.
- **Browse and triage postings (first priority).**
  - A filterable, searchable posting list.
  - A posting detail page showing the sanitized description, the scraped fields, first-seen and last-seen times, and a diff between snapshots.
  - A button that imports the inbox and shows the same report as the CLI. A person still starts every import.
- **Record triage data on each posting.**
  - Interest and fit ratings, free-form tags, and markdown notes.
  - Dismissing a posting with one or more reasons, then restoring it later.
  - Marking skills a posting asks for by highlighting text in its description.
  - Rating the user's own level for each skill: have, missing, or learning.
- **Track applications.**
  - An application can be linked to a stored posting or entered by hand, with a title, company and URL, for jobs found elsewhere.
  - Each application has an append-only, dated event history that drives its status (interested -> applied -> screening -> interviewing -> offer, or rejected / ghosted / withdrawn).
  - It can also have a next-action date and compensation notes.
  - An applications board groups applications by status.
- **Store documents** such as CV versions and cover letters. Uploaded files are copied into a content-addressed folder under `data/documents/`, and their text is extracted when possible. One document can be linked to many applications.
- **Companies and contacts.** User-owned company records hold a careers or listing URL and notes, and are matched to postings by company name. Contacts hold a name, emails, role and notes, and can be linked to companies and applications.
- **Introduce schema migrations (Alembic).** User-authored data cannot be rebuilt from captures, so the schema must change safely from now on. A baseline migration covers the existing scraped tables, and existing databases are adopted without losing data. `init_db` runs the migrations instead of `create_all`.
- **Reserve space for the Ollama phase.** The UI gets an Insights tab placeholder. The design fixes how model-derived data will be keyed and shown, but no enrichment is built in this change.

Not in this change: LLM enrichment or analysis, charts and preference analytics, authentication, remote access, re-parse tooling, grouping duplicate postings, CSV export.

## Capabilities

### New Capabilities

- `web-interface`: The `serve` command, local-only binding and request-origin checks, navigation, the posting list with search and filters, the posting detail page with snapshot diff, the import-from-browser action, original-posting links wherever postings appear, and the Insights placeholder.
- `posting-triage`: User-authored triage data on postings: ratings, tags, notes, dismissal with reasons, posting skills marked from description text, and the user's skill self-assessment.
- `application-tracking`: Applications with or without a stored posting, the append-only event history and derived status, next actions, the applications board, documents (managed storage, text extraction, links to applications), companies and contacts.

### Modified Capabilities

- `posting-storage`:
  - "Scraped data is separate from user data" now covers real user-authored tables. Neither import nor re-import may change them, and the web interface writes only user-authored data.
  - "Storage runs on Postgres and SQLite" now creates and upgrades the schema through versioned migrations, including adopting databases created before migrations existed.

## Impact

- **New code**: a `web/` subpackage (Flask app, routes, Jinja2 templates, static htmx and a small script for highlighting), user-data tables and queries, document storage and text extraction, an Alembic environment and migrations shipped inside the package, the `serve` subcommand, and tests.
- **Changed code**: `db.py` (new tables; `init_db` runs migrations) and `cli.py` (new subcommand). The extraction and import logic does not change.
- **New dependencies**: Flask (which brings Jinja2), Alembic, a markdown renderer, and PDF and DOCX text extraction libraries. The specific packages are chosen in design.md. htmx is vendored as a static file, so no CDN or Node is needed.
- **Data**: `data/documents/` holds uploaded files and is already covered by the `data/` gitignore. Existing SQLite and Postgres databases are upgraded in place.
- **Rename**: every module and test import, `pyproject.toml`, the `origin` remote, the stale `jobchecker.egg-info`, and the installed console script all change. The archived first change is left as written, as a historical record. The local checkout folder is renamed by the user as a last step outside the session, because the venv's scripts contain absolute paths and the venv has to be recreated afterwards.
- **CLAUDE.md**: the project name, the env vars, the Commands and Architecture sections need the `serve` command, the web package, migrations and the three data kinds.
