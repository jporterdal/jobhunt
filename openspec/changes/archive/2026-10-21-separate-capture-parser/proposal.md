## Why

The app reads postings from one job site through a parser that the user keeps private. The public repository must neither publish that parser nor mention it, and `prepare-public-release` can't sanitize the tree until the split is done (its design, D10). Today the site's parser runs throughout the app: a posting's identity is the site's job ID, the importer only understands that site's files, and every page links to the site by name. A public app with no parser would also have no way to import anything.

## What Changes

- **Source-neutral posting identity. BREAKING (schema, URLs).** A posting gets an auto-numbered integer key, which the app keeps calling `job_id`, and a `(source, external_id)` pair that is unique. One migration renumbers existing postings and rewrites the key in every table that references them. Each existing posting keeps its old ID as its external ID, and its source is the host of its stored URL, taken from the data so the migration names no site. Posting URLs change from `/postings/<site ID>` to `/postings/<number>`, and the posting search also matches the external ID, so an old ID still finds its posting.
- **Parsers are plug-ins.** Installed packages register parsers in a `jobhunt.parsers` entry-point group. A parser looks at a file's contents (not its type) and either accepts it as a posting from its origin, rejects it with a reason, or doesn't recognise it. The importer tries every installed parser on every file in the inbox, and imports a file only when exactly one parser accepts it. Parsers can name companion files that move with a file. The inbox, file moves, report, duplicate detection and "Import inbox" button stay public.
- **A public import format.** A built-in parser reads one JSON file per posting (`"format": "jobhunt-posting"`, `"version": 1`). The file carries the source, external ID, URL, title, company, optional location, workplace and employment type, posted date and precision, the description HTML, and optional source-specific details. It may also give a capture time.
- **Sanitizing is public and stricter.** The importer sanitizes every parser's description HTML with the existing allowlist and derives the plain text when the parser gives none. Links keep only `http`, `https` and `mailto` addresses, since files can now come from anywhere.
- **Site-specific fields become details.** Snapshots keep the core fields: title, company, location, workplace type, employment type, posted date, description. The site's own fields move into two kinds of details, both shown on the posting page: compared details and volatile details, which aren't compared. Captures record the parser that accepted them (`name@version`) instead of a page type. Existing values are migrated, and fingerprints are recomputed so that an unchanged re-capture stays `unchanged`.
- **Neutral wording.** Posting links read "Original posting ↗" wherever a posting appears, and the posting page shows the source.
- **The site's parser moves out.** Its extraction and date-estimation code, version constant, filename check, file-handling rules, fixtures (synthetic and private), golden tests, and the extraction and import tests over them move to a separate private package that depends on `jobhunt` and registers its parser. The `posting-extraction` capability leaves the public specs, and the `CLAUDE.md` capture workflow goes with it.
- **The migration chain is squashed. BREAKING (old databases).** Once the user's database has been upgraded through the conversion, revisions `0001`–`0010` are replaced by one baseline revision with the same id as the last one. The public tree then holds only the current schema, and the user's database needs no stamp. Databases at older revisions, or made before versioning, are refused with a message instead of being upgraded.
- Not in this change: a public parser for schema.org `JobPosting` JSON-LD (a later change), and rewording the remaining site mentions in other specs, archives and comments (`prepare-public-release`).

## Capabilities

### New Capabilities
<!-- None: the plug-in point and the import format are part of capture-import. -->

### Modified Capabilities
- `capture-import`: becomes source-neutral. Parsers are installed plug-ins tried on every inbox file. There is a built-in JSON posting format, descriptions are sanitized at import, and companions are named by parsers. Identity comes from the accepting parser's source and external ID. The filename-mismatch requirement leaves with the private parser.
- `posting-storage`: postings have an integer key and a unique source and external ID; existing postings are migrated; snapshots split core fields from compared and volatile details; captures record their parser; databases older than the baseline are refused.
- `posting-extraction`: retired from the public specs. Every requirement moves to the private parser package.
- `web-interface`: posting links say "Original posting" and the detail page shows the source, the posting search also matches the external ID, the browser import accepts any file a parser recognises, and posting URLs use the integer key.
- `application-tracking`: a hand-made application is described as having no imported posting, not as having no posting from the site.

## Impact

- **Code:** `extract.py` and `dates.py` leave the package, along with `PARSER_VERSION` in `__init__.py`. New: `parsers/` (the protocol, entry-point loading, the built-in JSON parser) and a public sanitizer. `importer.py` (parser selection, companions), `store.py` (identity, details, fingerprint), `db.py`, `queries.py` (search, details, the diff fields), the posting routes in `web/` (`<int:job_id>`), the 14 templates that use the link macro, `cli.py` (help text), and `pyproject.toml` (entry points).
- **Schema:** revision `0010_baseline` converts the database (posting key, source, external ID, details, capture parser). Then `0001`–`0010` are squashed into one `0010_baseline` revision with no history, and `migrate.py` drops the pre-versioning adoption.
- **Data:** the user's database is upgraded once, after a backup of `data/`. Every posting's `/postings/<id>` URL changes. Backups at older revisions open only with the code from before the squash, which stays in the private history.
- **Tests:** the HTML fixtures and the tests over them move to the private package. Public tests build postings from invented JSON posting files. The tests that pin a site ID as a string key change to the integer key, and tests of upgrades through the old revisions go with the squash.
- **Private package:** a new repository next to this one (the user chooses its name and place), with its own OpenSpec folder holding `posting-extraction` and the import rules for its files. Its tests run against `jobhunt` installed in editable mode.
- **Ordering:** `prepare-public-release` starts its sanitizing after this change is archived. That change's demo uses the JSON posting format, and its README describes the format and the plug-in point. This change's artifacts don't name the site, so its archive can be published.
