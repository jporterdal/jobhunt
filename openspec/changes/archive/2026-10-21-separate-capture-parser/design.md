See proposal.md for why, and the delta specs for the behaviour (`capture-import`, `posting-storage`, `web-interface`, `application-tracking`, and the retired `posting-extraction`).

## Context

The current state that shapes the approach (read-only survey, 2026-10-18):

- **The parser is wired in.** `importer.py` imports `extract()` directly, `store.py` imports `ExtractedPosting` and `estimate_posted` (`dates.py`), and `PARSER_VERSION` sits in `__init__.py`. Discovery, companion handling and the filename check are hard-coded for the one parser's files. Sanitizing (`description_html`) and plain-text conversion (`description_text`) are generic, but they live in `extract.py`. The sanitizer keeps a link's `href` whatever its scheme, and `description_html` is rendered with `|safe`.
- **Identity is the site's ID.** `postings.job_id` is a `String(32)` primary key holding the site's numeric job ID. Foreign keys to it sit in 11 tables: `captures`, `posting_snapshots`, `posting_triage`, `posting_tags`, `posting_dismissals`, `posting_skill_marks`, `rejected_suggestions`, `applications`, `tailored_cvs`, `posting_enrichments` and `llm_jobs`. Three of them include it in their primary key. There are about 500 references to `job_id` in `src/` and 90 in `tests/`. Every posting route is `/postings/<job_id>` with a string converter.
- **Snapshot columns mix core and site fields.** Seven snapshot columns hold site-specific fields: five are compared in the fingerprint, and two are stored but not compared. `captures.page_type` holds a value specific to the site. `queries.DIFF_FIELDS` and the detail page read the site fields by name. The column names and how each maps to a detail are kept in the private notes (`FUTURE_CHANGE.md`, section 4), not in this change.
- **The user's database:** at `0008_knowledge_base` (`0009_tailored_cv` hasn't run on it yet), with about a hundred postings. Every URL has the same host with a leading `www.`, every ID is numeric, and every snapshot has parser version `1`.
- **The public repository** starts from one sanitized snapshot of this tree (`prepare-public-release`, D1). Revision files in the tree are content, not history, so they can be squashed with no public trace of the old chain. Development continues in the public repository afterwards.
- **Archived changes only about the parser** (for `prepare-public-release` to move): one, the change that added the first importer (its folder name is in the private notes). `2026-10-02-add-local-web-ui` mentions the site about 60 times, but it is about the web UI, so it gets reworded, not moved. The other six archives mention it once to five times.

## Goals / Non-Goals

**Goals:**
- The public package imports postings only through installed parsers, and includes one parser of its own (the posting file).
- The user's database comes through with every user-authored, derived and operational row attached to the same posting. A re-capture by the private parser of an unchanged posting is still `unchanged`.
- The public tree holds one baseline revision and no trace of the old key or the site fields.

**Non-Goals:**
- A schema.org `JobPosting` parser (a later change), or any parser that reads web pages in the public package.
- Parser priority or per-parser settings. Two parsers accepting one file is an error (Open Questions).
- Re-parsing stored captures with a newer parser version. Captures keep their bytes and parser, so it stays possible.
- Rewording site mentions outside the specs this change modifies (`prepare-public-release`, D4/D10).

## Decisions

### D1. An integer key that keeps the name `job_id`

`postings.job_id` becomes an auto-numbered `Integer` primary key, and every referencing column becomes an `Integer` foreign key with the same name. Routes use `<int:job_id>`, and type hints change from `str` to `int`.

- Why keep the name: `job_id` names no site, and keeping it makes the change one of type, not of 500 identifiers. The key is internal: it's never sent to a parser or written to a file.
- *Alternative: rename to `posting_id`.* It's clearer, but it doubles the diff for no change in behaviour, and the public tree would show no difference.
- *Alternative: keep the external ID as the key, with a composite string (`source:external_id`).* It needs no new column, but every key is long, URLs carry a host, and two parsers' keys can still collide when one changes its source name.

### D2. `source` and `external_id`

`postings` gains `source` (`String(100)`, `^[a-z0-9][a-z0-9.-]*$`) and `external_id` (`String(200)`), both non-null, with `UniqueConstraint("source", "external_id")`. `store.store_capture` looks a posting up by the pair, inserts it when it's new and lets the database assign the key. By convention, a website's source is its host without `www.`. The upgrade (D9) derives existing rows' source this way from the stored URL, so the migration names no site, and the private parser must declare the same source.

### D3. The parser protocol and entry points

`src/jobhunt/parsers/__init__.py` holds the protocol and the loader. Nothing in it is site-specific.

```python
@dataclass(frozen=True)
class CaptureFile:            # what a parser is given
    path: Path                # for its name and for companions; parsers must not read other files
    raw: bytes
    modified_at: datetime     # the file's mtime, UTC

@dataclass(frozen=True)
class ParsedPosting:
    source: str; external_id: str; url: str; title: str; company: str
    description_html: str                   # sanitized again by the store (D6)
    description_text: str | None = None     # derived from the sanitized HTML when None
    location: str | None = None; workplace_type: str | None = None; employment_type: str | None = None
    posted_on: date | None = None; posted_precision: str | None = None
    captured_at: datetime | None = None     # else modified_at
    details: Mapping[str, Value] = {}       # compared
    volatile_details: Mapping[str, Value] = {}
    warnings: tuple[str, ...] = ()

@dataclass(frozen=True)
class Rejected:
    reason: str

class Parser(Protocol):
    name: str                 # e.g. "posting-file"
    version: str              # recorded as "name@version"
    def parse(self, file: CaptureFile) -> ParsedPosting | Rejected | None: ...   # None: not recognised
    def companions(self, path: Path) -> list[Path]: ...   # optional; files that belong to `path`
```

- **Loading.** `parsers.installed()` reads `importlib.metadata.entry_points(group="jobhunt.parsers")` and loads each one (an object, or a class instantiated with no arguments), sorted by name. Two parsers with the same name are an error. If an entry point fails to load, the import still runs with the rest, and the report starts with a warning naming it. The built-in parser is registered in `pyproject.toml` as `posting-file = "jobhunt.parsers.posting_file:PARSER"`, so it follows the same path as a plug-in.
- **Injection.** `importer.import_files(engine, paths, inbox, parsers=None)` uses `installed()` when `parsers` is `None`. `create_app` and the CLI load parsers once and pass them in. Tests pass a list (including `tests/fakes.FakeParser`), so they never depend on what's installed.
- *Alternative: parsers claim file suffixes or MIME types.* The user ruled it out: one file type can come from many origins, and only the contents tell them apart.
- *Alternative: a plug-in that converts files into posting files outside the app.* It's simpler for the app, but the original page isn't kept for re-parsing, and "Import inbox" can't read it.

### D4. Every parser tries every file

For each file not caught by the duplicate check (the bytes' hash, before any parsing, as today), the importer calls every parser's `parse`. Each result is collected, and an exception counts as `Rejected(f"{type}: {error}")` from that parser. Exactly one `ParsedPosting` means the file is accepted. Otherwise the file is rejected with the reason the spec gives for each case. The accepted posting's warnings and the store outcome go to the report as today.

- Why no priority: with no order to configure, a second parser that wrongly accepts a file shows up as an error rather than silently winning.
- Cost: N parses per file, where N is the number of installed parsers (two today). Parsing is milliseconds, and an import is a handful of files.

### D5. Discovery and companions

`discover(inbox, parsers)` lists the regular files directly in the inbox, oldest first, then leaves out companions. A companion is any path returned by any parser's `companions(f)` for an inbox file `f`, plus the download metadata that the operating system keeps beside a downloaded file (`f.name + ":Zone.Identifier"`), which belongs to no parser. When moving a file, `move_with_companions(path, dest, companions)` uses the accepting parser's companions plus that metadata file. For a rejected file it uses the union over all parsers. The renaming rule generalises today's: the destination stem gets ` (n)`, and each companion whose name starts with the file's stem gets the same new stem, so a file and its companions never split across numbers.

### D6. The public sanitizer

`src/jobhunt/sanitize.py` holds `clean_html(html: str) -> str` and `html_to_text(html: str) -> str`, moved from `extract.py`'s `description_html` and `description_text` with the same allowlist and line rules. Two changes:

- **Links.** `href` is kept only when its scheme is `http`, `https` or `mailto`. Anything else, including relative addresses, is dropped, and the `<a>` keeps its text.
- **Store-side.** `store.store_capture` runs `clean_html` on every parser's HTML. When the parser gives no `description_text`, it uses `html_to_text(cleaned)`. The private parser keeps passing the text it derives from the page itself, so its stored text stays byte-identical to today's, and model-run offsets and quote placement don't move. `clean_html` must be idempotent, which a property test over the fixtures checks.

### D7. Snapshots: core fields plus two detail maps

`posting_snapshots` keeps `title`, `company`, `location`, `workplace_type`, `employment_type`, `posted_on_estimate`, `posted_on_precision`, `description_html` and `description_text`. It drops the seven site columns and gains `details_json` and `volatile_json` (`Text`, JSON objects, for portability). `parser_version` is renamed `parser`, holding `name@version` (old rows keep `1`).

- **Canonical form.** `store.canonical_details` drops keys whose value is null, `""` or `[]`, and sorts the keys. A value is text, a number, a boolean or a list of text, and anything else is rejected at import as the parser's error.
- **Fingerprint.** It is the SHA-256 of `json.dumps([title, company, location, workplace_type, employment_type, description_html, description_text, canonical(details)], ensure_ascii=False)`. Volatile details and the posted date are not included, which matches today's rule for the fields that change on every visit.
- **Display.** The detail page shows each detail as a row, with its name made readable (`contract_length` would become "Contract length"). `queries.DIFF_FIELDS` becomes the core fields plus every detail key in either snapshot.
- *Alternative: keep the site columns as generic optional fields.* A few of them are common on job boards, but most are one parser's internals. A clean core with open details also lets a new parser add fields without a migration.

### D8. Captures

`html_gz` is renamed `raw_gz`, since it holds any file. `page_type` is dropped: it can be derived again from the stored bytes, and it was never shown. A nullable `parser` column (`name@version`) records which parser accepted the file, and is null for captures stored before the upgrade. The capture download keeps the original filename and bytes.

### D9. The conversion revision `0010_baseline`

The revision follows `0009_tailored_cv`. Its id is the one the squashed baseline will reuse (D10). Steps, portable except where noted:

1. On `postings`, add `new_key`, `source` and `external_id`. Fill them in Python: number rows from 1 by `(first_seen_at, job_id)`, `external_id = job_id`, and `source` = the URL's host, lowercased, without `www.`.
2. For each referencing table, add `new_job_id Integer` and fill it with a correlated `UPDATE … SET new_job_id = (SELECT new_key FROM postings WHERE postings.job_id = t.job_id)`. Rows whose `job_id` is null (hand-made applications, document and links jobs) stay null.
3. Recreate each referencing table without the old column, renaming `new_job_id` to `job_id`, and restoring its primary key, unique constraints, indexes and nullability. `batch_alter_table(recreate="always")` does this on both dialects. Then recreate `postings` with `job_id` as an integer primary key and the `(source, external_id)` constraint, and add the foreign keys back. On Postgres only, the revision creates a sequence for `postings.job_id`, sets it as the default and moves it past the maximum, the one dialect branch.
4. Move the site columns into `details_json` and `volatile_json` in canonical form, keyed by the old column names. The mapping is in the private notes, so the private parser can emit the same keys and value forms. Recompute `fingerprint` with a frozen copy of D7's rule: a migration never imports app code that can change later. Rename `parser_version` and `html_gz`, and add `captures.parser`.

`downgrade()` reverses the steps. It refuses, with a message, when two postings share an external ID, since keys can't then be restored. Details whose keys aren't the old columns are lost, as the downgrade note in `CLAUDE.md` will say. The downgrade exists only until D10's squash.

Verification goes beyond `test_migrate`'s metadata comparison. A data test builds a `0009` database with a row in every referencing table on both dialects, upgrades it, and checks every row against its posting's new key. `tests/test_migrate.py` also checks that the frozen fingerprint matches `store.fingerprint` for the same values.

### D10. Squash to one baseline with the same id

Once the user's database is at `0010_baseline` (Migration Plan step 5), `versions/0001`–`0010` are replaced by one `0010_baseline.py` with `down_revision = None`. Its `upgrade()` creates the whole schema, autogenerated against an empty database and then reviewed, and its `downgrade()` drops it. The user's database needs no stamp: its version row already names the head.

- `migrate.upgrade` drops the pre-versioning adoption (`BASELINE` and its stamp). Tables with no `alembic_version`, or a version the script directory doesn't know, raise `migrate.TooOld` before anything is written. The CLI prints the spec's message and exits 2.
- Tests of upgrades through old revisions (`tests/test_upgrade_profile.py`, `tests/profile_0007.py`, the step and adoption cases in `tests/test_migrate.py`, and the data test from D9) are deleted with the revisions. `test_migrate` keeps the empty-to-head metadata check and gains the two refusal cases.
- The last commit before the squash should be tagged in the private repository (for example `pre-baseline`), so older backups can still be upgraded with that code. The user decides whether to tag.
- *Alternative: a new baseline id plus a one-off rule that maps the old head onto it.* That rule would stay in `migrate.py` forever for one database.
- *Alternative: leave the chain and only reword its comments.* The public tree would then show the old string key and the site fields being created and converted.

### D11. Neutral links and labels

The posting-link macro in `macros.html`, and its CSS class, are renamed `original_link(url, label="Original posting ↗")` and `original-link` in the 14 templates that use them. "Open on …" labels become "Original posting ↗". The scraped-data label "from …" becomes "imported", and the detail page's meta table gains "Source" and "External ID". `new.html`'s hint becomes "For a job you haven't imported…". `cli.py`'s import help describes files and parsers.

### D12. External-ID search

`queries.ListFilters.q` also matches `postings.c.external_id == q` (exact, OR'ed with the text search). Notes and eval write-ups that cite old IDs still find their posting, which makes up for every `/postings/<id>` URL changing.

### D13. The private package

It lives in a new repository next to this one, which the user names and places. It depends on `jobhunt` (editable install) and registers its parser under `jobhunt.parsers`.

- **Code:** the parser, adapted from `extract.py` and `dates.py`, implementing D3. It recognises its files by their contents and rejects them for today's reasons. It reports the posted date and precision itself, emits D9's detail keys and value forms, passes its own description text, reports its filename check as a warning, and names its own companion files. The specifics are in the private notes.
- **Tests:** the synthetic and private fixtures, `test_extract`, `test_dates`, `test_golden`, and the cases of `test_importer` and `test_reimport` that use its files, run through `jobhunt.importer` with the parser passed in. A fingerprint check confirms D9: for every snapshot in a copy of the user's database, re-parsing its capture gives the snapshot's stored fingerprint. It is read-only and uses no models.
- **Specs:** its own `openspec/` with `posting-extraction` (moved unchanged) and an import capability for its files (the validation, identity-marker and filename-mismatch requirements removed here). `CLAUDE.md` gets the capture workflow.

### D14. Public test fixtures

`tests/fixtures/postings/*.json` holds about six invented posting files (sources such as `jobs.example.com` and `careers.example.org`), covering lists, emoji, unsafe markup, missing optional fields and a changed re-capture. `conftest.add_posting` writes a posting file and imports it through the built-in parser, returning the integer key. Tests that pass literal IDs (`"9000000001"`) use the returned key instead.

## Risks / Trade-offs

- [The conversion detaches or loses user data] → back up `data/` first, run on a copy, compare row counts per table and every foreign key's posting before and after, run the D9 data test on both dialects, and only then upgrade the real database.
- [The fingerprints after the split differ from the migrated ones, so every re-capture becomes `updated` and model runs end up on an older snapshot (re-extracting means GPU time)] → D7's canonical form on both sides, the private package's fingerprint check over the user's real captures before the real upgrade, and the private parser passing its own text (D6).
- [The new link rule changes stored descriptions] → it applies to new snapshots only, and the migration doesn't re-sanitize. Before the real upgrade, count the stored descriptions with a non-http link. A posting with one shows as `updated` on its next re-capture.
- [`jobhunt serve` or `import` upgrades the database as soon as the new code runs] → step 5 of the plan is deliberate. Until then, run the new code only with `--db` pointing at a copy.
- [Squashing before the user's database reaches `0010_baseline` strands it] → the plan orders the steps, the squash task first checks `migrate.current_revision` on `data/jobhunt.db`, and a stranded database is refused unchanged (with no partial upgrade), so the pre-squash tag can still rescue it.
- [Entry points come from installed metadata, so a changed `pyproject.toml` has no effect until reinstalled] → `pip install -e .` after the change (in both repositories). `CLAUDE.md` says so, and the "nothing recognises the file" reason lists the installed parsers, which shows a missing one at once.
- [Old `/postings/<site ID>` links and notes stop working] → D12's search. The integer keys are small, so an old ID won't collide with a new key in practice. It would give a 404 or another posting, never an error.
- [A future parser and the private parser both accept the same page] → the file is rejected with both names, which is safe but blocks import until one is uninstalled (Open Questions).

## Migration Plan

1. Back up `data/` (database and documents).
2. Rename the three requirement headers and reword the Purposes in place (tasks 1.x), then implement, with the full suite on SQLite and Postgres.
3. Create the private package, install both editable, and confirm that `parsers.installed()` lists both parsers.
4. Upgrade a copy of `data/jobhunt.db` (`0008` → `0009` → `0010_baseline`). Compare the counts and links, run the private fingerprint check, count the non-http links, and open the app on the copy.
5. With the user's go-ahead, upgrade the real database (any `import` or `serve` does it), then check it as in step 4.
6. Tag the pre-squash commit (if the user wants), squash (D10), and confirm the real database opens as a no-op at head.
7. Sync and archive. `prepare-public-release` can then start.

Rollback before step 6: restore the backup and check out the commit before the change. After step 6: restore the backup and use the tagged commit.

## Open Questions

- **Two parsers accepting one file.** Today it's an error. If a public JSON-LD parser arrives, the private parser's pages may embed JSON-LD too, and a priority or "prefer this parser" rule would be needed. That belongs to the change that adds the second page parser.
- **The private package's name, place and parser name.** These are the user's to choose at the start of tasks group 6. They don't affect the public side.
