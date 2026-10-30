# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

Early stage, built one OpenSpec change at a time: each change's proposal, design (with its measurement results) and tasks are in `openspec/changes/archive/`, in date order, and the accepted behaviour is in `openspec/specs/`. Later rounds of recommendations and preference analysis will be settled through **OpenSpec** (see below). Keep this file's commands and architecture current. Don't assume tooling or libraries that haven't been chosen yet.

## Purpose

`jobhunt` is a Python tool that collects job postings over time, adds the user's own annotations to each one, tracks the user's applications, and analyzes the results. The analysis should show which roles and skills the user prefers and suggest where to focus their resume and their learning or experience.

## Decided so far

- **Language:** Python
- **Package manager:** pip, always inside the project venv at `venv/` (Python 3.13). Never install into the system or user site-packages. Activate it with `source venv/bin/activate`, or call `venv/bin/pip` / `venv/bin/python` / `venv/bin/pytest` directly.
- **Tests:** pytest
- **Lint:** ruff (`[tool.ruff]` in `pyproject.toml`: line length 120, rules `E F W I B UP`; any ignore carries its reason). `ruff format` isn't used. `pre-commit` runs `privacy-check --staged` and ruff on each commit (`.pre-commit-config.yaml`).
- **CI:** `.github/workflows/ci.yml`: tests on Python 3.11 and 3.13 (SQLite), tests on Postgres, ruff, the privacy check (`--patterns-only --history`) and `openspec validate --all --strict`.
- **OpenSpec schema:** `jobhunt-driven` (`openspec/schemas/jobhunt-driven/`, the default in `openspec/config.yaml`), forked from OpenSpec 1.13.0's `spec-driven` with one more required artifact, `parser-impact` (needed before `tasks`). A fork doesn't receive upstream changes to `spec-driven`'s instructions; compare with `openspec schema which --all` after upgrading OpenSpec. Changes archived before the fork keep `schema: spec-driven`.
- **Storage:** Postgres is the main database, with SQLite as a fallback. Data-access code must work on both. Don't rely on Postgres-only features (JSONB operators, arrays, `ON CONFLICT` variants, etc.) unless they're behind a portable abstraction or have an SQLite equivalent.
- **Libraries:** BeautifulSoup 4 + lxml for HTML parsing; SQLAlchemy Core 2.x (no ORM) for portable storage; Alembic for schema migrations; `psycopg` for Postgres (optional extra); `argparse` for the CLI; Flask + Jinja2 with vendored htmx for the web UI (no JavaScript build step); `markdown-it-py` for notes; `pypdf` and `python-docx` for document text extraction. The Ollama client uses the standard library (`urllib`); don't add the `ollama` package.
- **Models:** a local Ollama server only. No data leaves the machine, and model output is a suggestion until the user accepts it.
- **Parsers:** installed plug-ins, registered by packages under the `jobhunt.parsers` entry-point group (the built-in `posting-file` parser is registered the same way in `pyproject.toml`). Entry points come from installed metadata, so after changing a `pyproject.toml` entry point run `pip install -e .` again. Parsers recognise files by their contents, not their type.
- **Interface:** a local web app (`jobhunt serve`); notebooks may come later for analysis. Keep each posting's original URL and show it as a link ("Original posting") wherever postings appear in output.

## Spec-driven workflow (OpenSpec)

Design decisions and features go through OpenSpec, which is installed globally as the `openspec` CLI. Specs live under `openspec/` (`openspec/specs/` for accepted capabilities, `openspec/changes/` for proposals in progress):

- Before implementing a feature, check for an existing spec or change proposal (`openspec list`, `openspec list --specs`, `openspec show <item>`), and implement against it.
- Open design questions should be handled as OpenSpec change proposals, not settled on the fly in code.
- Run `openspec validate` on changes, and use `openspec archive <change>` once a change is fully implemented.
- **Parser changes:** every change has a `parser-impact.md` artifact (required by the project's `jobhunt-driven` schema) stating its parser impact: none, optional or required. When it isn't none, that file is a self-contained brief for parser maintainers, and `docs/parsers.md` (the guide for parser authors) gets a contract changelog entry. Parsers can live in other repositories, private ones included, so never edit them from here: tell the user when a change needs parser work, both when proposing it and before archiving it, and point them to the brief.

## Commits

- **Prefixes:** a commit that changes code starts with `feat: `, `fix: ` or `chore: `, whichever applies. A commit of a new change's docs starts with `opsx change <change-name>`; a commit of a change's sync and archive starts with `opsx archive <change-name>`.
- **Ask first:** don't commit without checking with the user and showing them the full commit message first; commit only once they agree to it.
- **Never push**, and never offer or ask to push, without an explicit instruction from the user.
- **No AI attribution:** no `Co-Authored-By` trailer or "Generated with" line in commits or PRs, whatever a harness default says.
- **Identity:** commit only as the noreply GitHub identity set in this repository's git config, never as another address.
- **Hooks need the venv:** the pre-commit hooks run `jobhunt` and `ruff` from `PATH`, so commit with the venv active in the same command (`source venv/bin/activate && git commit ...`); an agent's shell doesn't keep an earlier activation. If a hook fails, fix the cause; never skip hooks with `--no-verify`.

## Intended functional areas

1. **Collection:** brings job postings in from files a person collects, through installed parsers. It always runs **under human supervision** (see constraints below).
2. **Storage:** keeps every posting over time. At minimum it records the description, post date, the company or entity that posted it, and the URL.
3. **User metadata:** the user's own notes on each posting, such as interest level, fit, whether they applied, and tags.
4. **Analysis and insights:** combines postings and user metadata to show preference patterns, plus which skills and keywords appear most often in preferred postings, to guide resume emphasis and learning priorities.

## Design constraints

- **Human-in-the-loop collection:** don't build unattended or bulk scraping, background crawlers, or anything designed to get around a site's rate limits or anti-automation measures. A human starts collection runs and can watch or step through them.
- Keep captured data (which can change or disappear at its source) separate from user-authored data (which is permanent and belongs to the user). Re-collecting a posting must never overwrite user metadata.
- Record when each posting was first and last seen, and preserve history rather than overwriting it, so trends can be analyzed over time.

## Getting postings in

1. Put the files to import into `inbox/`: posting files (below), or files an installed parser reads.
2. Run `jobhunt import`, or press "Import inbox" in the web UI. Every installed parser is tried on every file; a file is imported only when exactly one parser accepts it, and otherwise rejected with the reason (each rejecting parser's reason, the accepting parsers' names, or the installed parsers when none recognises it). Files move to `inbox/processed/` or `inbox/rejected/` with their companions (named by parsers, plus `<name>:Zone.Identifier` download metadata); the import deletes nothing.
3. **The prune** (`prune.py`) is the only deletion: it removes the companions an installed parser marks **discardable** (optional `discardable(path)`, counted only when the same parser's `companions(path)` names it; never the file or its download metadata) for files directly inside `processed/` and `rejected/`, asking every installed parser, and follows no links. `serve` prunes at start-up when no prune of its (resolved) inbox is recorded in the last 24 hours, then daily; `jobhunt inbox prune [--dry-run]` prunes by hand. The first `serve` after the change removes the existing pile. Each prune (not a dry run) is a row of `inbox_prunes`, and the Import page shows the latest. `docs/parsers.md` is the guide for parser authors, with the contract changelog.

A **posting file** (the built-in `posting-file@1` parser, `parsers/posting_file.py`) is one JSON object: `"format": "jobhunt-posting"`, `"version": 1`, non-empty `source` (lowercase letters, digits, dots and hyphens; a website's host without `www.`), `external_id`, `url` (http or https), `title`, `company` and `description_html`; optionally `location`, `workplace_type` (`On-site`, `Hybrid`, `Remote`), `employment_type`, `posted_on` (ISO date) with `posted_precision` (`minute` … `year`, default `day`), `captured_at` (ISO date-time with a zone; else the file's mtime), and `details` / `volatile_details` (name → text, number, true/false, list of text or null). Unknown fields, wrong types and other versions are rejected, naming the field. `tests/fixtures/postings/` has examples.

The importer never trusts the filename: identity is the accepting parser's source and external ID.

## Architecture

```
src/jobhunt/
    parsers/
        __init__.py   CaptureFile, ParsedPosting, Rejected, the Parser protocol, loading `jobhunt.parsers` entry points (installed())
        posting_file.py  the built-in posting-file parser (one JSON posting per file)
    sanitize.py   description HTML -> allowlisted HTML (links: http, https, mailto only), and its plain text (no DB code)
    db.py         SQLAlchemy Core tables (captured + user-authored + derived + operational), engine setup; init_db runs migrations
    migrate.py    programmatic Alembic: upgrades to head (SQLite foreign keys off while revisions run, checked before commit); refuses databases older than the baseline (TooOld)
    migrations/   Alembic env.py + versions/ (shipped as package data)
    store.py      writes captures/postings/snapshots for a ParsedPosting: identity by source and external ID, sanitizing, canonical details, fingerprint; history is appended, never rewritten
    importer.py   inbox discovery (companions), every parser on every file, per-file transaction, file moves, report
    prune.py      plan/run a prune of discardable companions in processed/ and rejected/ (links not followed, problems reported),
                  record it (inbox_prunes), latest(), the Pruner thread serve runs daily
    units.py      format_size, shared by the CLI and the web `size` filter
    userdata.py   every write of user-authored data, incl. the profile (records, lines, sources, part_of, disclosure, claims, grounds,
                  highlights, aliases, details), identities and remembered rejections, accepting/rejecting document suggestions,
                  reset_knowledge_base, link overrides, saved CVs (save, move/remove an item, delete) (no HTML, no Flask)
    queries.py    read models: posting list/filters, detail, snapshot diff, skills, board, companies, profile, document suggestions
                  (profile_suggestions), expansion contexts, posting skills, effective links, saved CVs (no Flask)
    documents.py  content-addressed document store + text extraction: PDF, DOCX, ODT (tabs kept), TXT, MD (no Flask)
    recommend.py  match credits and scores, posting ranking, unlinked-skill pooling, skill gains, a posting's Have / Don't have summary (`posting_summary`); computed on each view, no writes (no Flask)
    tailor.py     a CV proposal for a posting (`cv-rank@1`): Choice (the only parser of its URL), highlight cover, records by kind,
                  details, gaps, private-record checks; computed on each view, no writes (no Flask)
    cvdoc/
        model.py      CV content (payloads, JSON at content_version 1) and the laid-out Cv dataclasses. No DB.
        layout.py     section order, headings, date and term wording, course condensing, nesting: build(content) -> Cv
        styles.py     every ODF style of an exported CV (styles.xml) and the style names
        odt.py        write(cv) -> ODT bytes (stdlib zipfile + ElementTree, deterministic)
    cli.py        `jobhunt import`, `jobhunt inbox prune`, `jobhunt serve`, `jobhunt eval`, `jobhunt profile reset`, `jobhunt privacy-check`, `jobhunt demo`
    privacy.py    the release privacy check: personal values from the database (read-only) and the private term file, patterns
                  (posting IDs, emails, phones, home paths), forbidden file kinds; tracked, staged and history scopes
    demo/
        persona.py    the demo's fictional person as plain data: profile, notes, applications, skill terms, relation table
        scripted.py   ScriptedClient (the Ollama client's interface, answered from persona.py) and trigram_vector (also used by tests)
        seed.py       build(engine, documents_dir) through the app's own writers and job queue; refusal of non-empty targets
        postings/     the demo's posting files (package data)
    enrich/
        ollama.py     Ollama HTTP client (urllib): status, models, chat_json with fixed options, embed (batched). No DB.
        pipeline.py   Segment/SkillItem/SalaryItem, step protocols and registry, pipeline_id, run_pipeline. No DB, no HTTP.
        segment.py    segmenters "rules" (headings, no model) and "llm-lines" (model labels numbered lines; default); duties count as required
        skills.py     skill extractor "atomic@2" (the app's, `CURRENT_SKILLS`; room for one candidate): one call per required/preferred group, retry once on empty
        salary.py     salary extractor "paylines": only lines that mention pay go to the model
        validate.py   quote and amount checks against the text, whole-word quote placement (shared with the eval), normalised-to-raw offset map, higher-importance-wins merge (pure Python)
        derived.py    the only writer of derived tables; each posting run is stored as an `app` or `eval` run; a document run with its suggestions
        jobs.py       the llm_jobs queue (only writer): posting, document and links jobs, enqueue_links, and the Worker thread
        cv.py         document pipeline: caps@1 sections (no model), llm@1 line labels, rules@1 records/lines/sources/highlights,
                      cv-claims@1 skills as claims, part-of@1 context links (the user's guideline word for word), validation; run_document
        terms.py      "Taught <Term> <Year>, ..." -> one dated term each (Winter Jan-Apr, Summer May-Aug, Fall Sep-Dec), pure Python
        links.py      candidate-finding methods (RETRIEVALS: names, skill-expand@1) and judges (JUDGES: link-judge@5, @6), the
                      app's method (CURRENT_RETRIEVAL, CURRENT_JUDGE, PIPELINE), phrase-pair shortlist, plan, judge_links loop
        expand.py     skill-expand@1: alternative phrasings of a skill name (measured, not used by the app), stored expansions
        link_eval.py  link measurement against the user's overrides: reference set, plan/execute with reuse, sweep, paired verdicts
        evaluate.py   labelled set (with each posting's stored dev/holdout set), whole-word mark placement, key-then-overlap matching, per-posting scoring by mark origin, miss attribution, wrong-by-reason, plan/execute, report, method comparison
    web/
        __init__.py   create_app(engine, inbox, documents_dir), shared helpers and filters
        guard.py      Host check on every request, Origin/Referer check on non-GET requests
        postings.py   list, detail, snapshot diff, capture download, import action (with the latest prune), /insights (recommendations, "have it"/"don't have it")
        triage.py     ratings, tags, notes, dismissals, skill marks, skills page
        applications.py  applications, events, board, documents, companies, contacts
        llm.py        status badge, settings (incl. holdout share, embedding model), extract actions, queue, accept/reject suggestions with a reason
        profile.py    /profile (details, records, skills, highlights and their edits), /profile/suggestions (accept, reject, accept all),
                      /profile/rejections (forget), /profile/links
        cvs.py        /postings/<id>/cv (proposal, read-only), saving, /cvs/<id> (saved CV, move/remove/delete), /cvs/<id>.odt
        templates/    Jinja2 pages and htmx fragments
        static/       htmx.min.js (vendored), marks.js, app.css
```

- `postings` is one row per source and external ID, with an integer key `job_id` (assigned by the database, used in every other table and in `/postings/<int:job_id>` URLs) and first/last seen. A snapshot holds the core fields (title, company, location, workplace and employment type, posted date and precision, description HTML and text) plus `details_json` (compared) and `volatile_json` (not compared), in `store.canonical_details` form (no null, "" or [] values, keys sorted). A new `posting_snapshots` row is added only when the fingerprint (`store.fingerprint`: core fields except the posted date, plus details) changes. `captures` keeps every accepted original file (`raw_gz`) and the accepting parser's `name@version`; snapshots record it too (`1` for snapshots stored before parsers were plug-ins).
- A parser bumps its own `version` when its output changes. Postings from a source keep its details' names and value forms, or every re-capture becomes `updated`.
- Imported files can hold personal data. `inbox/` and `data/` are gitignored; keep it that way.

### Four data kinds, one writer each

- **Captured** (`postings` with source and external ID, `captures` with their parser, `posting_snapshots` with details): written only by `store.py`, through the importer. The import report (CLI and web) shows each file's outcome, source, external ID, title, company and URL, with parser warnings or the rejection reason; an import writes nothing else.
- **User-authored** (triage including the skill-labelling-complete flag, when it was first set and the posting's eval set, tags, dismissals, skills and skill marks with importance and origin, rejected suggestions with their reasons, applications and events, documents, companies, contacts, `app_settings`, and the profile: `records`, `record_lines`, `record_sources`, `claims` (the level and `level_origin`), `claim_records` (grounds), `highlights`, `highlight_claims` (coverage), `skill_aliases`, `profile_details`, `profile_rejections`, `skill_link_overrides`), and saved CVs (`tailored_cvs`, `tailored_cv_items`): written only by `userdata.py`. Import, re-import and extraction never touch these tables, and the web UI never writes captured tables. Applications cache `status`; only `userdata.recompute_status` sets it, from the events.
- **Derived** (`posting_enrichments`, `enrichment_skills`, `enrichment_salaries`, `document_runs`, `profile_suggestions`, `skill_embeddings`, `link_judgments`, `link_relations`, `skill_expansions`, `link_measurements`): written only by `enrich/derived.py`. Each `posting_enrichments` row has an `origin`: `app` (stored by the job queue) or `eval` (stored by `jobhunt eval`). Only `evaluate.py` reads eval runs; every app read (`queries`' posting skills, salary, panel and bulk count, and `userdata` accepting) filters to app runs. `link_measurements` holds judgments made by `eval --links` and is read only by `link_eval.py`, so it never decides a link. A run or judgment is never edited; extracting or judging again adds one. `userdata.accept_suggestion` reads a verified suggestion and copies it into a skill mark (origin `suggestion`); `userdata.accept_profile_suggestion` likewise copies what a document suggestion offers into profile rows with `origin='suggestion'`. `analyses` is still not created.
- **Operational** (`llm_jobs`, the work queue: `kind` is `posting`, `document` or `links`): written only by `enrich/jobs.py`. `inbox_prunes` (one appended row per prune: inbox path, start and finish, companions and bytes removed, problems with the first 50 as JSON): written only by `prune.py`.

The UI marks captured, user and derived data with `.src-captured`, `.src-user` and `.src-derived`. `USER_TABLES`, `DERIVED_TABLES` and `OPERATIONAL_TABLES` in `db.py` list them.

### Model enrichment

- **Ollama address:** `--ollama-url`, else `$JOBHUNT_OLLAMA_URL`, else `http://localhost:11434`. It is fixed at startup and never taken from the browser. With Ollama down, everything else works and model actions are disabled.
- **Settings page** (`/settings`, stored in `app_settings`): the model (installed text models only), the context size (default 8192), the segmenter (default `llm-lines`), the embedding model (`llm.embed_model`, installed models with the `embedding` capability; unset means an installed `nomic-embed-text`), and the holdout share for the eval (`eval.holdout_share`, 0.1–0.9, default 0.5, saved by its own form at `POST /settings/eval`, with the number of labelled postings in each set and help on when to change it).
- **Worker:** `serve` starts one `jobs.Worker` thread (not in the debug reloader's parent). It runs queued jobs in order across kinds, outside any transaction. A links job is skipped (it waits, without blocking later jobs) while no embedding model is chosen or installed. While Ollama is unreachable, jobs stay queued. Jobs left running at shutdown are queued again at the next start. Cancelling takes effect between steps. `create_app` never starts the worker; tests call `jobs.run_next(engine, client)`. Beside it, `serve` starts a `prune.Pruner` thread (same reloader guard), which prunes when due, re-reads the latest record at least hourly (`MAX_WAIT`) and prints one line per prune; tests drive `Pruner.run_once(now)`.
- **Pipeline:** a segment is a pair of character offsets into the snapshot's `description_text`, so steps cannot rewrite text. Every chat request uses temperature 0, seed 7, the context size, a JSON schema and `think: false` for thinking models. The validator checks each quote (and each salary amount) against the text; unverified items are stored but hidden, and cannot be accepted. When verified items name the same skill, only the first at the highest importance is kept (required beats preferred); the trace keeps them all. Skill kinds are `technical`, `soft` and `qualification` (runs before `atomic@2` stored `domain`). A run records its model and `pipeline` id (`seg=llm-lines@2 skills=atomic@2 salary=paylines@1 validate=v@3`). Bump a step's `version` when its output changes, so old and new runs aren't compared as equal. The app uses one skill extraction method, named by the code (`pipeline.CURRENT_SKILLS`, `atomic@2`), with no setting. Skill extractors are registered by `name@version`, so at most one candidate version can sit beside it while `jobhunt eval --skills` measures it; a candidate is never reachable from the app, and one that isn't adopted is deleted. A queued job whose pipeline names a version the code no longer has fails with an error. `derived.save_run` takes the run's origin (`app` from `jobs`, `eval` from `evaluate`); a posting with only eval runs has no "Model says" output and counts as unextracted.
- **Tests** never need Ollama: `tests/fakes.py` has `FakeLLM` (scripted answers keyed by the schema's top-level field) and `FakeOllama` (status, models and embeddings for web, queue and link tests: character-trigram vectors, or explicit ones via `vectors=`); `tests/test_ollama.py` runs the client against a stdlib HTTP stub.
- **Labelling and eval:** to measure extraction, label 5–10 postings *before* extracting them (mark every skill the posting asks for, with importance, then click "Labelling complete"). Then run `jobhunt eval`. Scoring is by mark origin: recall counts only marks you selected yourself; precision counts a suggestion right when it matches any mark (selected or accepted), wrong when you rejected it, and leaves the rest out as *unjudged* (reported beside it). Accepting a suggestion never removes a posting from the set. Label by your own bar, which is stricter than the default prompt: mark only expertise a hiring team would screen for, named in the text (practices and disciplines count even when worded as work, but not everyday activities any engineer does, basics any engineer has, or team practices a new hire adopts); duties count as required, and a skill marked at both importances is required. A skill you only noticed because the model suggested it should be **accepted, not selected by hand**: hand-selected marks count toward recall, so selecting after seeing suggestions flatters the model (the eval can't detect it). Marks are placed at every whole-word occurrence of their quote. The report attributes each missed skill to segmentation, extraction or "not located". Reject a suggestion as **not a skill** (by your definition) or **not for me** (a skill you don't want marked); the report breaks wrong suggestions down by reason (rejections made before reasons existed count as "no reason"; set one from the shown-rejected list). **Dev and holdout sets:** when a posting is first flagged complete, its set (`posting_triage.eval_set`, with `eval_set_origin`: `drawn`, `chosen`, `moved`, `before-random`) is drawn by `userdata.set_skills_complete`, or chosen by hand (Auto, Dev or Holdout beside "Labelling complete"). The draw puts it in holdout with P = 1 / (1 + ((1 − r) / r) · e^(−(r·N − H))) over the N postings flagged complete now, H of them holdout, and r the holdout share (`userdata.holdout_probability`). A posting keeps its set (clearing and re-setting the flag never draws again); a holdout posting can be moved to dev from its page (`POST /postings/<id>/eval-set`, `userdata.move_eval_set`), never dev to holdout, since prompts may have been tuned on it. Postings labelled before the sets were drawn (revision `0012`) are dev, or holdout if flagged after the old held-out start, origin `before-random`. The report shows dev, holdout, `holdout (drawn)` when some holdout posting wasn't drawn, and together (the top-level JSON figures; `sets.dev`, `sets.holdout`, `sets.holdout_drawn`; `set` and `set_origin` per posting). Labelling before extracting still applies: the set doesn't change what counts as unaided. The report warns about selected marks made after their posting already had a successful run (app or eval), since suggestions may have prompted them; they still count. The eval reuses any stored run (app or eval) with the same snapshot, model and pipeline, and stores new ones as eval runs, which the app never uses. `jobhunt eval --skills atomic@2,<candidate>` compares the app's method with a registered candidate side by side and lists the selected marks only some of them found; `--json` adds each posting's missed, wrong and unjudged items (`per_posting`). Don't run models against the user's GPU without asking.

### The profile and skill links

- **The profile is a knowledge base** for generating CVs, not a copy of a document's layout. **Records** are facts (`userdata.RECORD_KINDS`: role, course, project, publication, degree, award, event, task, other), flat, each with dates (partial ISO `2022`/`2022-09`, ongoing), ordered description lines, sources (repository, site, DOI, other, or an uploaded document; kind from the address by default), a disclosure (`public`/`private`) and at most one `part_of` link to the record that gives it context (the user's guideline, `cv.PART_OF_GUIDELINE`, is shown on the form; cycles are refused; deleting a context record clears its dependents' links and flags them `context_lost_at` until relinked or dismissed). Effective disclosure is computed (private if any record in the chain is), and `part_of` never counts as a ground. Records are sorted per kind by `queries.record_sort_key` (ongoing, then newest end-or-start date, undated last, ties by id). Courses are one record per term taught; condensing terms of one course (same title and organisation) is the CV's job (see "Tailored CVs"). A skill is in the profile when it has a **claim** (one per skill, holding the level on `missing < learning < familiar < proficient < expert` and its `level_origin`); setting a level anywhere creates or updates the claim, clearing it deletes the claim with its grounds and coverage. **Grounds** (`claim_records`) tie a claim to records, each with a quote (a hand-made ground quotes the record's title and organisation); a claim without grounds is flagged ungrounded unless at `missing`. **Highlights** are CV wording, each covering claims (`highlight_claims`, optional quote); a claim no highlight covers is flagged. **Aliases** (`skill_aliases`): `merge_skill` moves a skill's grounds and coverage to a profile skill, removes its claim, makes its key an alias (aliases of it follow) and re-points link overrides; marks, posting rejections and the eval are untouched; `queries.resolve_skill` resolves an alias for levels, suggestions and linking. **Details** (`profile_details`: name, headline, contact, summary, goal) are flat rows the user edits; documents never suggest them. Origins: `user`, `suggestion` (accepted), `model` (carried over from the old automatic merges); a content edit makes a row the user's, moving a line doesn't.
- **Identities and remembered rejections** (`userdata.identity_*`, design D6): a record by kind, title, organisation and dates; a line or source by its record's identity and its text or address; a claim by its (alias-resolved) skill key; a ground, `part_of` link, highlight, coverage and suggested level likewise, all compared by `name_key`. Deleting a row, or editing it so its identity changes, remembers the old identity in `profile_rejections`; adding the same by hand forgets it; `/profile/rejections` lists and forgets them.
- **Reading documents in:** uploading a `cv` document with extracted text queues a `document` job (when a chat model is chosen); any other document with text has "Add to profile". The pipeline id is `cvseg=caps@1 cvlines=llm@1 cvrecords=rules@1 cvskills=cv-claims@1 cvpartof=part-of@1 validate=v@3`. Contact and summary sections are never sent to the model and suggest nothing; claims sections aren't labelled (every line is a highlight). `rules@1` makes entries records (kind from the section), the rest of an entry's line its first line, following lines its description lines (a lone web address a source), lines before any entry highlights; a "Taught <Term> <Year>, ..." line (`enrich/terms.py`) splits its record into one `course` record per term, and an undated record takes its dates from its lines. `cv-claims@1` is `cv-atomic@1`'s request without claimed years: each verified skill becomes a claim grounded by the record(s) holding its line or covered by the highlight that is its line, repeats folded at the highest level. `part-of@1` makes one request per run (two records or more), with the guideline word for word and two invented examples; self, out-of-range and cyclic answers are dropped. Every quote is located in the text; a date counts only when its quote is in its own line; a date after a line's last tab is that line's date. Unverified items stay in the run's trace.
- **Suggestions, not merges:** a succeeded run stores its verified suggestions (`profile_suggestions`, by kind and position; grounds, coverage and `part_of` name the run's records and highlights by position) and changes nothing else, so a document job queues no link judging. `queries.profile_suggestions` works out on each read what each document's latest succeeded run offers against the current profile: `new`, or `adds` to an existing row (lines and sources a record lacks; grounds a claim lacks, and a higher level only when the claim's level came from the model; coverage a highlight lacks), merged across documents by identity, minus remembered rejections; grounds on records not yet in the profile wait (counted), grounds on rejected records are dropped, a `part_of` link waits for both records and a dependent without a link. `/profile/suggestions` lists records, claims, context links and highlights with accept, reject and "Accept all (n)" per kind (it accepts a snapshot; what that unlocks is offered afterwards). Accepting copies rows with origin `suggestion` (levels `level_origin='model'`) and `source_run_id`; rejecting remembers each offered identity. Runs from before suggestions existed offer nothing.
- **Comparing extractions:** `jobhunt profile reset --db URL --yes` deletes every record, claim and highlight (with lines, sources, grounds, coverage) without remembering them, keeping details, aliases, rejections, overrides, postings and documents, so a fresh extraction can be run on a copy of the database and compared.
- **Posting skills** (`queries.posting_skills`): a posting's marks plus the verified suggestions of its latest succeeded run on its latest snapshot, minus rejected keys; marks win; identified by key.
- **Links** (`queries.effective_links`), checked in order: the user's override (ignored and shown stale when its skill left the profile; `/profile/links` states how many are), a profile skill with the same key or of which the key is an alias (`same`, no model call; `queries.same_identity`), the latest succeeded judgment (best of `same > specific > general > related`, relations to skills outside the profile ignored), else no link. Judging embeds skill names once per model (`skill_embeddings`, float32), shortlists up to `SHORTLIST_K` profile skills at cosine ≥ `SHORTLIST_FLOOR`, and makes one `link-judge@5` request per posting key with candidates (none when the shortlist is empty). The floor is 0.75: nomic-embed-text scores any two skill names 0.65 or more. `@2` defines `same` strictly and picks the weaker relation when in doubt; `@1` called related skills the same; `@5` is `@2` with its two examples replaced, since they were among the user's own links and flattered its measurement. The app uses one linking method, named in `links.py` (`CURRENT_RETRIEVAL`, `CURRENT_JUDGE`; pipeline id `links=link-judge@5`), with no setting. A key whose latest judgment has another pipeline is judged again, and the worker queues that at start-up (`jobs.enqueue_links_if_outdated`); the old link stays in effect until replaced. The other registered entries, `skill-expand@1` (max-pair phrase similarity over expanded phrasings) and `link-judge@6` (shows each profile skill's CV line, `queries.context_lines`, instead of its quote), exist only to be measured; a measured method that isn't adopted is deleted, keeping at most one candidate each for candidate finding and judging. A profile skill's context (`queries.expansion_contexts`, shown to the judge and used for expansion) is the quote of the oldest of its claim's grounds and quoted coverages (ties: grounds first, then by record or highlight id); `queries.context_lines` gives `link-judge@6` the ground's record line holding the quote (else its title and organisation) or the highlight's text. The upgrade kept each ground's and coverage's time from its evidence, so every context, and `link-judge@5`'s input, stayed the same.
- **Automatic link judging** (`jobs.enqueue_links`) is queued after accepting a document suggestion that touches claims, grounds or coverage, a profile skill being added, renamed or removed, a ground or coverage added or removed (directly, or by deleting a record or highlight), a skill merged or an alias removed, a successful posting run, a mark added or removed, a rejection or its undoing, an override cleared, or an embedding-model change; a document run by itself queues nothing. It does nothing without a chosen chat model or any profile skills, coalesces with a queued links job, and queues another if one is running. The job only judges keys whose shortlist or embedding model changed since their latest judgment; "Re-judge all" on `/profile/links` judges every key without an override. Cancelling keeps the judgments already made.

- **Match score and recommendations** (`recommend.py`, shown on `/insights`): a posting skill's credit is the best relation weight × level weight over its link options (`effective_links`' `options`: the override's one link, the same-key skill's, else every usable relation of the latest judgment), so a `same` link to a `missing` skill doesn't hide a weaker link to a skill the user has; the link shown stays the strongest. A posting's score is the importance-weighted average credit (required 2, preferred and unspecified 1); postings rank by score × interest ÷ 3 (unrated counts as 3), leaving out dismissed postings and postings with an application. Skill gains ask "what if I had it at `proficient`" for pools of unlinked posting keys and profile skills below `proficient`. Pooling (`recommend.pool`) takes keys most asked first (then shorter name, then key) and compares each with every pool's first member only, so pools don't chain: it joins the most similar pool at cosine ≥ `POOL_SIMILARITY` (0.90), or ≥ `POOL_NAME_SIMILARITY` (0.80) when the leader's words are a run of its words (split on non-alphanumerics, a plural `s` dropped). Vectors are the stored `skill_embeddings` of the newest succeeded link judgment's `embed_model` (`queries.latest_embed_model`); with none, or for a key without a vector, a key is alone. A pool is named after its leader, its row lists the other names ("also: …"), and every member gets credit `same` × `proficient`; answering it adds the leader's name, and link judging decides the other members. Pools affect only skill gains: scores, gaps and posting ranking count each posting skill. The workplace filter (checkboxes on `/insights`, `?workplace=Remote&workplace=Hybrid`) narrows the postings both lists consider, by the latest snapshot's `workplace_type`, before ranking; `recommend.workplace_choice` is the only parser of the URL values, and none or all three ticked means no filter (postings without a type are then considered, and are left out otherwise). It isn't stored; answers and level changes on Insights return to the same filter through `next`. All weights and thresholds are constants at the top of `recommend.py` (guesses until there are ratings). Nothing is stored and no model is called; "have it"/"don't have it" (`POST /insights/skill`) call `userdata.add_profile_skill`, which queues link judging as any profile change does.

- **Known weak spots** (see the change's design, "Fourth round"): bare names miss concept-to-tool links (`Vector databases` → `ChromaDB`; 16 of 52 reference links aren't shortlisted), and expansion finds them but breaks refusals; the judge is stricter than the user on `general` and `related`; a "no link" override goes stale when the profile later gains a candidate, and nothing flags it; `cv-claims@1` still suggests near-duplicates, paper titles and fragment skills ("Chain"), now as suggestions to reject or skills to merge; and the shortlist floor is tuned on one profile only. Change linking as a new registered version, measure it with `jobhunt eval --links` against the user's overrides, and make it current only when its verdict is `better`. The verdict compares methods posting skill by posting skill: `better`/`worse` need a one-sided sign test at p ≤ 0.05 over the posting skills one fixes and the other breaks, otherwise `within noise`; re-judging the same skill flips a few answers, so a handful of reference links can't separate methods.

### Tailored CVs

- **The proposal** (`tailor.propose`, `GET /postings/<id>/cv`, "Tailor a CV" on the posting page) is computed from stored data on each view: no writes, no model. Its choices live in the URL (`tailor.Choice.from_args` is the only parser): `budget`, `count_<kind>`, and with `tuned=1` the ticked ids `h`/`r`/`d` and unticked `x_h`/`x_r`/`x_d`; the form also sends `a_*`, the ids the ranking chose by itself, so an unchecked one becomes an untick and a checked one stays with the ranking. Each posting skill's value for a profile skill is importance weight × relation weight × level weight, from `recommend.py`'s weights and `effective_links`' options. **Highlights**: greedy weighted cover up to the budget, each posting skill counting once at its best shown value, less `IRRELEVANT_COST` per covered claim no posting skill links to; ties to fewer claims, then lower id; hand-ticked ones print after. **Records**: `KIND_RULES` (role, course, degree, award: all; publication 3, project/event/task/other 0 by default), ranked kinds by relevance (Σ over posting skills of the best value among a record's grounds), filled by `record_sort_key`, printed in kind order. **Details**: `DEFAULT_DETAILS` (name, headline, contact, goal). **Gaps**: posting skills with credit > 0 that no chosen highlight or printed record shows. All constants sit at the top of `tailor.py`; a change that alters what is chosen for the same data bumps `METHOD` (`cv-rank@1` → `@2`).
- **Private records are never printed**: records whose effective disclosure is private are dropped before ranking, so they can't be offered, ticked, fill a count or close a gap; a highlight mentioning a private record's title, organisation (4+ characters) or source address is flagged and unticked unless the user ticks it.
- **Saving** (`POST /postings/<id>/cvs`) makes the proposal again from the posted ids inside the write and stores it with `userdata.save_tailored_cv`: one `tailored_cv_items` row per top-level item (section, position, `source_kind`, `source_id` with no foreign key, `payload_json`), the match score, the method, and `choice_json` (the choice and the kinds with records left out, for "Selected Publications"). A saved CV is a **frozen copy**: profile edits never change it; its page marks items whose source has since been deleted or become private, and the user can move items within a section, remove them (records printed under them go too) or delete the CV. Posting and application pages list a posting's saved CVs.
- **Presentation**: `cvdoc/layout.py` (section order, headings, dates, terms, condensing, `part_of` nesting: a record whose context is printed goes under it, else gets "Part of: …") and `cvdoc/styles.py` (fonts, sizes, tab stops, the bullet list) are the only places to change the look; the HTML preview (`cvs/_preview.html`) and the ODT export (`GET /cvs/<id>.odt`, only for saved CVs) render the same `Cv`. Payloads are field values, not formatted text, so restyling applies to saved CVs too; a payload shape change bumps `content_version`, and `content_from_json` keeps reading every version written.

### Privacy check and demo

- **Fictional data only** in tests, specs, docs and the demo: the cast in `docs/fictional-data.md` (Jane Doe, `Example …` organisations, `example.com` addresses, posting IDs from `9000000001`, `555-01xx` phones). Real-looking values a test needs are built at runtime.
- **`jobhunt privacy-check`** (`privacy.py`) reports values from the user's database (read-only; refused unless at head), lines of `data/privacy-terms.txt`, personal-looking patterns and forbidden file kinds (databases, office documents, `data/`, `inbox/`), with masked values unless `--show`. `data/privacy-allow.txt` holds allowed values (`path-prefix<TAB>value` for one place); a `privacy: allow` comment allows a pattern finding on its line, never a database value. Both files are ignored. Exit 0 clean, 1 findings, 2 usage or database problem. CI runs it `--patterns-only --history`; the pre-commit hook runs it `--staged` against the local database.
- **`jobhunt demo`** (`demo/seed.py`) builds a separate database (default `sqlite:///demo/jobhunt.db`, `demo/documents`; never the real defaults) and refuses one that holds postings, profile rows or documents. Postings go through the public import, user data through `userdata`, and model output through the real job queue with `ScriptedClient` (models `demo-scripted` and `demo-trigram`), so no model server or network is used. Times are fixed at `persona.DEMO_DATE`, so two builds hold the same rows apart from clock-written run times. `demo.created_at` marks the database, and every page then shows "Demo data". `tests/test_demo.py` builds it on both backends and checks every page, so a change that breaks the demo fails the suite.

### Web UI

- Server-rendered, bound to `127.0.0.1` by default, with no authentication. `web/guard.py` is the request-safety layer; keep GET handlers read-only.
- Route modules stay thin: logic goes in `userdata.py`, `queries.py` or `documents.py`, which are tested without Flask.
- Only `description_html` (sanitized at import) is rendered with `|safe`. Notes go through markdown-it with HTML disabled, and only `http`, `https` and `mailto` URLs become links.

### Schema migrations

The schema changes only through Alembic revisions in `src/jobhunt/migrations/versions/`. `init_db` applies them on every `import` and `serve`. To add one:

1. Change the tables in `db.py`.
2. Generate a revision against a scratch database upgraded to head (the `alembic` CLI reads `$JOBHUNT_DB_URL`, not `alembic.ini`):
   ```bash
   export JOBHUNT_DB_URL=sqlite:////tmp/jobhunt-mig.db
   alembic upgrade head
   alembic revision --autogenerate --rev-id 0011 -m "short description"
   ```
3. Review the generated file (keep it portable; `render_as_batch` handles SQLite `ALTER`s), and write `downgrade()`.
4. Run `pytest`, on Postgres too. `tests/test_migrate.py` fails if the migrated schema differs from `db.metadata`.

The chain starts at one baseline, `0010_baseline` (the whole schema and the default dismiss reasons; earlier revisions were squashed into it). A database at an older revision, or with tables but no version, is refused unchanged (`migrate.TooOld`, exit 2).

### Data and backups

The database and uploaded documents both live under `data/` by default (`data/jobhunt.db`, `data/documents/<sha[:2]>/<sha>`). Documents are files, not database rows, so **back up `data/` (database and documents)**, or the Postgres database plus the documents folder. Copy the database before any `alembic downgrade`; going below `0010_baseline` drops every table. A database older than the baseline is refused; it must first be upgraded by a release from before the baseline.

## Commands

```bash
python3 -m venv venv                     # once, if venv/ does not exist
source venv/bin/activate                 # all commands below assume the venv is active
pip install -e ".[dev,postgres]"         # install the package, pytest and the Postgres driver

jobhunt import                           # import everything in ./inbox (moves files afterwards)
jobhunt import path/to/posting.json      # import specific files in place
jobhunt import --inbox DIR --db URL

jobhunt inbox prune --dry-run            # list the discardable companions in inbox/processed/ and rejected/, with sizes
jobhunt inbox prune --inbox DIR --db URL # delete them and record the prune (serve does this daily); exit 1 on problems,
                                         # 2 with no inbox folder; a dry run doesn't open the database

jobhunt serve                            # web UI at http://127.0.0.1:8000/
jobhunt serve --host HOST --port PORT --db URL --inbox DIR --documents DIR --ollama-url URL --debug
# a non-loopback --host prints a warning: there is no authentication
# --debug turns on the Flask debugger and reloader (development only)

jobhunt eval                             # measure skill extraction on labelled postings (uses Ollama)
jobhunt eval --model phi4:latest --segmenter rules --fresh --json --db URL --ollama-url URL
jobhunt eval --skills atomic@2,atomic@5  # compare the app's method with a registered candidate (default: the app's)
# reuses stored runs for the same snapshot, model and pipeline unless --fresh; exits 1 with no labelled
# postings, or when Ollama is unreachable and runs are needed (states the new runs per method first and runs none
# then), or with an unknown --skills method

jobhunt profile reset --db URL --yes     # delete every record, claim and highlight (on a copy: back up data/ first);
                                         # keeps details, aliases, rejections, link overrides, postings, documents

jobhunt eval --links                     # measure skill linking against your link overrides (development use)
jobhunt eval --links --retrieval names,skill-expand@1 --judge link-judge@5,link-judge@6 --dry-run
# states the expansion, embedding and judging requests first (--dry-run stops there); reuses stored expansions,
# vectors and judgments (the app's too) unless --fresh (judgments only); --all-skills previews every other posting
# skill; exits 1 with no overrides, an unknown method or version, no chat or embedding model, or Ollama unreachable

# defaults: $JOBHUNT_INBOX or ./inbox; $JOBHUNT_DB_URL or sqlite:///data/jobhunt.db;
#           $JOBHUNT_DOCUMENTS or data/documents; $JOBHUNT_OLLAMA_URL or http://localhost:11434
# Postgres example: --db postgresql+psycopg:///jobhunt

jobhunt demo                             # build the demo into ./demo (refuses a non-empty database or folder)
jobhunt demo --db URL --documents DIR    # then: jobhunt serve --db URL --documents DIR

jobhunt privacy-check                    # tracked files against data/jobhunt.db; untracked, unignored files by kind only
jobhunt privacy-check --staged | --history | --patterns-only | --show
jobhunt privacy-check --repo DIR --db URL --terms FILE --allow FILE

alembic history                          # list schema revisions (see "Schema migrations")

pytest                                   # run all tests
pytest path/to/test_file.py              # run one file
pytest path/to/test_file.py::test_name   # run a single test
pytest -k "keyword"                      # run tests matching a name
ruff check                               # lint (CI runs the same)
pre-commit install                       # once: privacy check and ruff on every commit (venv active)

# Storage, query and web tests also run on Postgres when this is set (each test uses a throwaway schema):
JOBHUNT_TEST_PG_URL=postgresql+psycopg:///jobhunt_test pytest
```

Tests import invented posting files from `tests/fixtures/postings/` (`conftest.add_posting` returns the posting's key) and use `tests/fakes.FakeParser` for importer cases, so they never depend on which parsers are installed. `conftest.throwaway_engine` gives another empty database on either backend.
