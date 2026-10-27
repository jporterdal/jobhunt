## Context

See proposal.md for motivation, and `specs/release-privacy/spec.md` and `specs/demo-data/spec.md` for the behaviour. The current state that shapes the approach (read-only audit, 2026-10-17):

- **Where personal values sit.** Of the database's distinctive values, these appear in git history: 7 of 27 record titles, 5 of 11 record organisations, 3 of 43 record lines, 3 of 13 source addresses (a repository, a thesis handle, a DOI), 4 of 12 profile details (location, availability, GitHub handle, a degree), and 9 of 112 posting job IDs. In the working tree they are in about 25 test modules and fixtures, 9 accepted specs, 13 archived changes, `generate-tailored-cv`, the untracked `FUTURE_CHANGE.md`, and three code comments. Real employers' names also appear in tests (`test_companies.py`, `test_importer.py`, `test_documents.py`) and in spec scenarios. 51 passages in `openspec/` describe "the user's CV/data" in prose (degrees held, courses taught, the CV's sections), which no value match will find.
- **Synthetic fixtures** (`tests/fixtures/synthetic/`) already use `Example …` organisations and job IDs in the `9000000xxx` range, but several titles and company names are lightly reworded copies of real postings the user saved.
- **Git metadata:** every commit is authored with the user's real name and institutional email. The remote is a GitHub repository under the user's handle; its visibility couldn't be checked (no `gh` here).
- **The capture parser** is site-specific and is to stay private (user's decision, 2026-10-17). The job site is named, or its page markers used, about 50 times in `src/` (the parser and date parsing, plus the posting link label in 14 templates), 38 times in 7 accepted specs, 127 times in the archives, and throughout `tests/` (mostly the saved-page fixtures). Posting identity was the site's job ID.
- **Since the audit (2026-10-21):** `separate-capture-parser` is archived. A posting is identified by its source and external ID, with an integer key (`postings.job_id`) that every other table refers to; a posting's old site ID became its external ID (`postings.external_id`). The posting link is labelled "Original posting". `capture-import` stayed in `openspec/specs/`, rewritten in source-neutral terms, and holds the public import format (the built-in posting file); only `posting-extraction` left. The saved-page fixtures are gone from `tests/`; the posting-file fixtures in `tests/fixtures/postings/` use `example.com` and `example.org` sources. A few accepted specs still name the site or say user data is keyed by its job ID (task 5.5).
- **Hazards outside git:** `data.bak-2026-10-15/` (database copy, CVs, a cover letter, `content.js`) is untracked and not ignored. `copy.html` and `copy2.htm` at the root are ignored only by name. `.claude/settings.local.json` (with home-directory paths) is ignored only by the user's global git ignore, which a clone doesn't have.
- **Presentation today:** no README, LICENSE, CI, linter or package metadata beyond name and version. 1493 tests and about 13.8k lines of source; `src/` lines run to about 120 characters. `CLAUDE.md` (43 KB) is the only architecture document. The specs and archives are a detailed, dated design record, with measurement write-ups (paired sign tests, held-out sets, methods measured and not adopted).
- **Visibility of the existing repository** (confirmed by the user, 2026-10-26): private, and never public. Its contents are not treated as already published.
- **Decided by the user:** a fresh public repository (not history rewriting); no real name in committed files at first, with attribution added by the user later; the AI-assisted, spec-driven process kept visible and explained; the capture parser kept private and never mentioned publicly, split out by its own change before this one.

## Goals / Non-Goals

**Goals:**
- A public tree and history in which no automated check or careful reader finds the user's identity, CV facts, job search or contacts.
- A guard that keeps it that way after release, since development continues in public.
- A repo a recruiter can understand in two minutes (README, screenshots) and verify in ten (CI green, `jobhunt demo`, tests, the design record).

**Non-Goals:**
- Changing the private repository or its history, `data/`, or the user's database.
- New product features beyond `privacy-check`, `demo` and the demo label.
- Secret scanning. The project has no keys or tokens. Patterns cover what this project could leak; a general secrets scanner can be added later.
- Making the GitHub account itself anonymous. The handle is the public identity the user chose.
- Packaging for PyPI.
- Splitting out the parser, making posting identity source-neutral, or designing the public import format. Those are `separate-capture-parser`'s (D10).

## Decisions

### D1. Publish a new repository from one sanitized snapshot

Sanitizing happens on a branch of the private repo, so its commits can hold real values safely. When the full check passes, the tree is exported (`git archive` of that commit) into a new directory. There it gets `git init`, a per-repo identity (`user.name` = the GitHub handle, `user.email` = its `…@users.noreply.github.com` address), and one commit. The full `--history` check then runs against the user's database before the first push. The new repo goes to a new GitHub repository. The old one stays private, renamed to free the name if wanted. Development then moves to the public working copy, with `data/` and `inbox/` moved over (both stay ignored).

- *Alternative: rewrite history with git-filter-repo.* It keeps the timeline, but every old commit becomes a place to miss a value, and the user chose against it.
- *Alternative: an orphan branch in the same repo.* It shares the object store and remote with the old history, so one wrong push of another ref publishes it.
- The dated `openspec/changes/archive/` folders keep the development story the lost history would have told.

### D2. One fictional cast, following the fixtures' `Example …` convention

All invented data comes from one cast, documented in `docs/fictional-data.md`, so tests, specs, docs and the demo agree:

- Person: `Jane Doe` (already in tests), `jane@example.com`, phone `+1 555 555 0100`.
- Organisations: `Example University`, `Example Polytechnic`, `Example Bank`, `Example Advisory`, `Example Province`, `Example Labs`. A conference: `EXCONF 2024`.
- Places: `Example City, EX`. Course codes: `COMP 1000`-style. DOIs: the `10.5555/` example prefix. Repositories: `https://github.com/janedoe-example/…`, which keeps source-kind detection working. Posting IDs: `9000000001` and up.

Names with "Example" can't collide with a real person or employer. Real area codes, provinces and conference names hint at a location or a paper, so they are replaced too. Synthetic posting titles and descriptions are rewritten freely, not as near-copies of real postings. Real employers' public names are never used, even with invented details ("Jane Doe at <real bank>" still says who was looked at).

### D3. The real-to-fictional map is private

The concrete map (real value → cast value) is kept at `data/release/replacements.tsv`, under the ignored `data/`. A throwaway script in the scratch directory applies it, not a tracked one. Replacements are applied in one pass, then tests run, then the remaining findings are fixed by hand (a replacement can change a length, sort order or quote position a test relies on). This change's own artifacts describe values only by category, since they will be published.

### D4. Accepted specs and archives are edited in place, without deltas

Replacing an example value in a scenario doesn't change a requirement, so no delta specs are written for the nine affected capabilities. A delta would have to copy each affected requirement whole, and archives can't be changed through deltas at all. The edit is editorial and checked with `openspec validate --all --strict`. Measurement write-ups keep their numbers and verdicts. Postings are named `posting A`, `posting B`, … per write-up instead of by job ID or title, and a note at the top of `openspec/changes/archive/README.md` says that example values and posting names in the record were replaced. Mentions of the job site, its page markers and the capture workflow are rewritten in source-neutral terms ("the capture parser", "an imported posting"), except in archives D10 moves out. Where a spec still says a posting is identified by, or user data keyed by, the site's job ID, the rewrite states the current identity (the posting's key, or its source and external ID). That changes what the passage says, so a term match can't check it and each one is read; it needs no delta, because `posting-storage` already specifies that behaviour. Prose about the user's data is rewritten generically: "the profile had 31 records" stays, "a PhD and ten taught courses" becomes "several degrees and many single-term course records".

### D5. Privacy check: `src/jobhunt/privacy.py`, `jobhunt privacy-check`

- **Terms.** Read-only SQLAlchemy Core selects over the columns listed in the spec. It never calls `init_db`. A database that isn't at head is refused with exit 2 and a message, since the check must not migrate it. Skill names, levels and marks aren't collected: they are generic ("Python") and alone identify no one. The prose review in D4 covers profile-shaped descriptions.
- **Matching.** Each term is normalised (casefold, whitespace runs → `\s+`) and gets `\b` at alphanumeric ends. All terms go into one compiled alternation, longest first; a few thousand terms is well within `re`. Patterns are separate named regexes, each with an allow predicate (the reserved ranges in the spec).
- **Scopes.** Tracked: `git ls-files -z` plus the working-tree file. Staged: `git diff --cached --name-only -z` plus `git show :<path>`. History: `git rev-list --all`, then per commit `git ls-tree -r` and `git log -1 --format=%an%x00%ae%x00%cn%x00%ce%x00%B`. Blob contents are read once per blob id through `git cat-file --batch`, and each finding is reported against the first commit and path seen. Binary blobs (with a NUL byte) are scanned only for forbidden kinds. Untracked files come from `git ls-files --others --exclude-standard`, grouped by top-level folder.
- **Files.** The default term file is `data/privacy-terms.txt` and the allow file `data/privacy-allow.txt`. Both are optional, one value per line, `#` comments; an allow line `path-prefix<TAB>value` is scoped to that prefix. Exit codes: 0 clean, 1 findings, 2 usage or database error.
- **Its own tests** build bad strings at runtime (`"jane@" + "real-domain.com"`, `"4" + "1" * 9`), so the tracked test file never matches its own patterns. No `privacy: allow` markers are needed in the repo.
- *Alternative: gitleaks or detect-secrets.* They find secrets, not a person's CV facts, and can't read this database.

### D6. Pre-commit hook and CI

- `.pre-commit-config.yaml`: a `local` hook running `jobhunt privacy-check --staged` (`language: system`, so it uses the venv's install, `pass_filenames: false`), plus `ruff`. Without the database the hook runs patterns only and warns, so it still works in a fresh clone.
- `.github/workflows/ci.yml` runs on push and pull request, with actions pinned by version:
  - `test`: Python 3.11 and 3.13, SQLite.
  - `test-postgres`: Python 3.13 with a `postgres:16` service and `JOBHUNT_TEST_PG_URL`.
  - `lint`: `ruff check`.
  - `privacy`: checkout with `fetch-depth: 0`, then `jobhunt privacy-check --patterns-only --history`.
  - `specs`: `npx @fission-ai/openspec@1.13.0 validate --all --strict`.
  If 3.11 fails, `requires-python` is raised to what passes rather than leaving a claim CI doesn't test.
- **Ruff:** `line-length = 120`, rules `E`, `F`, `W`, `I`, `B`, `UP`, with findings fixed rather than silenced, except per-rule ignores with a reason. `ruff format` is adopted only if its diff touches under about 5% of lines. Otherwise formatting is left as is, since a mass reformat buries the code in noise. *Measured 2026-10-26:* `ruff format --diff` would change 1,657 of 25,823 lines (6.4%), so formatting isn't adopted; the lines over 120 characters were rewrapped one statement at a time (`ruff format --range`), and per-file ignores cover model prompts and ODF markup, whose text is output.

### D7. Demo: `src/jobhunt/demo/`, through the app's own writers

- **Layout.** `persona.py` holds the profile, triage, applications, contacts and the per-posting skill lists as plain data. `postings/` holds about 10 synthetic postings in the public import format that `separate-capture-parser` defines (shipped as package data). `scripted.py` is a chat and embed client with the Ollama client's interface. `seed.py` holds `build(engine, documents_dir)`.
- **Writers.** Postings go through the public import entry point, so captured tables are written only by `store.py`. User data goes through `userdata` (and `documents` for the CV document). Model output comes from the real queue: `seed` enqueues posting and links jobs and drains them with `jobs.run_next(engine, scripted_client)`, so `derived.py` stays the only writer of derived tables and runs are stored with origin `app`. The saved CV is `tailor.propose` plus `userdata.save_tailored_cv`.
- **Scripted answers** are derived from the declarative skill lists rather than written as raw JSON. The client labels lines by their headings for `llm-lines`, returns each group's listed skills (with quotes taken from the page text) for `atomic@2`, returns the pay line for `paylines`, and judges links from a small relation table in `persona.py`. Embeddings are the character-trigram vectors `tests/fakes.FakeOllama` already uses. That function moves into `demo/scripted.py`, and `tests/fakes.py` imports it, so there is one copy. No GPU is used to build the answers, and none is needed to run the demo.
- **Fixed dates.** `seed` passes a fixed `now` (the constant `DEMO_DATE`) to the writers. Where the importer, store or a `userdata` function takes the current time internally, it gains an optional keyword `now` that defaults to the current time. Existing callers are unchanged.
- **Label.** `userdata.set_setting(conn, "demo.created_at", …)` marks the database. A context processor in `web/__init__.py` reads it, and `base.html` shows "Demo data" in the header. `app_settings` already exists, so no migration is needed.
- *Alternative: a committed demo `.db` file.* The privacy check forbids database files, the schema changes with each revision, and a seed script stays honest because tests build it.

### D8. Presentation for a technical reader

- **README.md:** a one-paragraph pitch (a local-first tool that keeps a searchable, annotated record of job postings and matches them against a structured CV, with local models only); 3–5 screenshots; a quick start (`pip install -e .`, `jobhunt demo`, `jobhunt serve --db …`, Ollama optional); features; "Design decisions" (human-in-the-loop capture and why; captured vs user-authored vs derived data with one writer each; portable SQL on SQLite and Postgres, migrations checked against the metadata; model output is a suggestion validated against the text; local-only models); "Measuring the models" (labelled sets, held-out postings, sign-test verdicts, methods kept or deleted on evidence, with links into the archive); "Known limitations" (the weak spots now in `CLAUDE.md`); "Getting postings in"; "How this was built"; and the licence.
- **"How this was built"** says plainly that the project was built with Claude Code through OpenSpec changes. The author set requirements and constraints, labelled data, ran and judged every measurement, chose what to keep, and reviewed the code. The model drafted most code, tests and spec text. Commits carry no AI attribution trailers (the user's decision, 2026-10-26: the README already says how the project was built, and the trailer's address would trip the history check's email pattern). Specific, checkable claims serve better than vague ones.
- **"Getting postings in":** the public import format and the plug-in point for capture parsers, as `separate-capture-parser` defines them, described generically. It names no site and says nothing about any private parser.
- **Terminology.** "Scraped data" suggests unattended collection, which the project never does, so the data kind is called **captured** in docs, comments, UI text and the CSS class (`.src-scraped` → `.src-captured`). Table names stay, so the schema is unchanged.
- **docs/:** `architecture.md` (module map and data-kind diagram, adapted from `CLAUDE.md`), `measurement.md` (methodology and the headline results, fictionalised per D4), `fictional-data.md` (D2), and `images/`.
- **Other files:** `LICENSE` (MIT, "Copyright (c) 2026 The jobhunt authors"); `SECURITY.md` (binds to 127.0.0.1, no authentication, Host/Origin checks, report through GitHub private advisories); `ROADMAP.md` (planned work in general terms, from `FUTURE_CHANGE.md`, which stays private and untracked). `pyproject.toml` gains `readme`, `license`, `keywords`, `classifiers`, and `ruff`/`pre-commit` in `dev`, with no `authors` or `urls` yet (D1: attribution comes later).
- `CLAUDE.md` and `.claude/` stay. `CLAUDE.md` is scrubbed, its "Project status" paragraph trimmed to a pointer at the archive, and it is linked from the README as the working guide for contributors and agents.

### D9. Checks a script can't make

Screenshots come only from a demo database, taken in a browser profile with no bookmarks, extensions or other tabs, and cropped to the page. The user looks at each one before it is committed. Paraphrased facts (D4) are found by a list of greps run during the review (`the user's`, `their CV`, `PhD`, `taught`, `thesis`, `hackathon`, `portfolio`, place names, and words that describe the private parser's site without naming it, kept in the private term notes), then read by the user. The user reads the full public tree once before the first push. Nothing is pushed until the user says so.

**Sign-off (2026-10-27):** the user read the public tree and approved it, along with the screenshots, the README's "How this was built" wording and every allow-file entry. The public repository is `jobsearch`, a new repository; the package stays `jobhunt`. Its commits use the GitHub handle and its noreply address, never the private repo's identity.

**Published (2026-10-27)** as the public `jobsearch` repository on GitHub. The first CI run failed the Python 3.11 job: `recommend.pool` used `math.sumprod`, which needs 3.12. After the fix (`f32f5dc`), every job passed on `67348c3`.

### D10. The boundary with `separate-capture-parser`

That change, made first, owns the split. It makes the public app source-neutral: posting identity by source and external ID, neutral link labels and wording in the UI, a public import format, and a plug-in point that a private parser registers with. It moves the parser and its date parsing, `PARSER_VERSION`, the saved-page fixtures (synthetic and private), the extraction and import tests over them, the `posting-extraction` spec (`capture-import` stays, rewritten in source-neutral terms, since it holds the public import format), and the capture workflow in `CLAUDE.md` to a private repository. It also lists the archived changes that are only about the parser, which move there as well. That list is kept in its private notes (moved into the private parser repository's docs), not in either change's artifacts, so the archives are named nowhere in the public tree.

This change then removes what's left: mentions in the remaining specs, archives, `CLAUDE.md`, `.claude/` and comments, rewritten per D4. It enforces the result through the private term file (the site's name, domain and page-marker names). The public code and this change's own artifacts never name the site, so the change can be archived in the public repo as it is. The separation change's own archive is published only if it is written the same way; otherwise it goes to the private repository too.

- *Alternative: do the split in this change.* That makes one change hard to review, and the split has design questions of its own (identity migration, the plug-in interface, what a public parser could support).
- *Alternative: keep the parser public under a neutral name.* The user ruled this out.

## Risks / Trade-offs

- [A paraphrased personal fact survives, since the check only matches exact values] → the D9 grep list, the user's read-through, and the history check against the user's private term file, to which the user adds anything found by hand.
- [A personal value is too short or too generic to collect, such as a two-letter initial or a common first name] → the private term file. The 4-character floor is a default, and short terms can be listed there.
- [Fictionalised archives no longer show the exact postings measurements ran on] → the archive README says so. Numbers and verdicts are unchanged, which is what a reader needs.
- [Replacements break tests in quiet ways, such as quote offsets or sort orders] → one replacement pass, then the full suite on SQLite and Postgres, then hand fixes. No test is loosened to pass.
- [The old GitHub repository is, or was, public] → the user confirms its visibility before anything else. If it was ever public, its contents must be treated as already published, which changes nothing here but is worth knowing.
- [The site's name survives in a paraphrase, a filename, an identifier or a commit message] → the site's name, domain and page-marker names in the private term file, so the tracked and `--history` checks report them anywhere, filenames included (they are scanned as paths).
- [The public app is less useful without a parser] → the public import format, the demo, and a README section on plugging in a source. Whether the public app should ship a parser for a common, permissively usable format is `separate-capture-parser`'s question.
- [False positives make the check noisy and get it ignored] → the allow file, scoped allows, and a per-category summary. Generic posting titles are expected there.
- [Recruiters discount AI-written code] → the openness of D8, plus checks a reader can verify: CI green, lint clean, tests, demo, and the measurement record showing judgment.
- [The demo rots as the app changes] → `tests/test_demo.py` builds it on SQLite and Postgres and checks every page and the reproducibility rule, so a breaking change fails the suite.
- [Adding `now` parameters touches writers] → keyword-only with the current default, covered by the existing tests.

## Migration Plan

1. Archive `generate-tailored-cv` (its last tasks use the real profile), then propose, implement and archive `separate-capture-parser` (D10).
2. Fix the immediate hazard: ignore rules, including `data*/` style backups (tasks group 1).
3. Build `privacy-check` and run it to get the full inventory.
4. Sanitize on a private branch until the full check passes and the user signs off on the D9 review.
5. Add demo, docs, CI and lint (they don't depend on step 4 and can run alongside it).
6. Export to the new repo, run the `--history` check, and have the user push (D1).
7. Rollback: the public repo can be deleted or made private within minutes. If anything personal is found after the push, delete the repo, fix it, and republish from a new snapshot. Forks and caches can't be recalled, which is why steps 4 and 6 come first.

## Open Questions

- The licence: MIT is the default here. Apache-2.0 would work the same for this plan.
- ~~The public repository's name.~~ Settled: `jobsearch`, a new repository beside the private `jobhunt` one (see D9's sign-off).
- Which 3–5 pages to screenshot. The demo makes any of them possible.
