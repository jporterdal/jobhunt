## Why

The project exists to show which roles and skills suit the user, and where to focus their CV and learning. Every posting now carries skill marks and model suggestions, but nothing records what the user actually has. The only trace is a `have / missing / learning` level per skill, and none of the 224 skills has one. The user's CV is the obvious source. Uploading a document already extracts its text, but nothing reads that text for skills, and the CV (an ODT file) isn't one of the formats text can be extracted from.

Matching also needs skill identity. Postings and CVs name the same skill differently: `LLMs` against "large language models", or `CI/CD` against "GitHub Actions". Exact names will under-count badly. The user's own profile is the natural vocabulary to match against: each posting skill only needs to be linked to a profile skill, not placed in a global taxonomy.

This change builds the user's **main profile** (the internal "main CV") and links posting skills to it. Scoring postings against the profile is the next change, and it depends on both.

## What Changes

- **Main profile.** A user-owned, structured record of the user's CV content, separate from any formatting:
  - sections (contact, summary, claims, experience, education, publications, projects, other)
  - entries (a role, a degree, a paper), each with an optional title, organisation, location, dates and URL
  - bullets, under an entry or directly under a section
  - the user's skills, each with a level and evidence pointing at the entries and bullets that show it.
  
  Everything is editable: add, edit, delete and reorder.
- **One level scale.** Skill levels become `missing < learning < familiar < proficient < expert`, replacing `have / missing / learning`. No skill has a level yet, so nothing needs converting.
- **Reading documents into the profile.** Uploading a CV queues extraction automatically. Any other document with text can be added to the profile with an action. A pipeline in the style of the posting pipeline produces suggested sections, entries, bullets, skills, claimed years and levels from the document's text. Every quote is checked against that text, and unverified items never reach the profile.
- **Model output lands and counts.** Verified results are merged into the profile automatically, marked "from model", and count straight away. The user changes or deletes only what's wrong. A row the user has edited is theirs, and later merges never overwrite it. A model-made row the user deletes is remembered and not brought back by a later document. Each merge is logged and can be rolled back without undoing the user's later edits.
- **ODT text extraction.** ODT joins PDF, DOCX, text and markdown. Tab stops are kept, because CVs use them to align dates.
- **Posting skills linked to profile skills.** A posting's skills are its marks plus the verified suggestions the user hasn't rejected, from the latest successful run on its current snapshot. Each posting skill gets a link to the profile:
  - The same skill key links as `same` with no model call.
  - Otherwise embeddings shortlist candidate profile skills, and the chat model judges the relation: `same`, `specific` (the profile skill is a specific form of the posting skill), `general` (a more general form), `related`, or none.
  - Model links count until the user overrides them. Overrides are never re-judged.
  - Links are re-judged automatically when profile skills or posting skills change. This is the first model work the app queues without being asked.
- **Settings.** The embedding model is chosen from the installed models that can produce embeddings, defaulting to `nomic-embed-text`.
- **The queue takes more kinds of work.** Jobs can extract a document or judge links, as well as extract a posting.

Next change (`add-skill-match`, decided in exploration and recorded here):
- A posting's score uses its skills (marks plus verified, unrejected suggestions, ignoring rejected ones for either reason), each credited by its link's relation and the linked profile skill's level. Relation and level credit values have initial defaults chosen by the implementer and are editable in Settings. `learning` earns partial credit.
- A posting skill with no link is a gap that scores 0. "Not in profile" is shown apart from "confirmed missing" (level `missing`), with a one-click "I have this" that adds the skill to the profile.
- Sorting and filtering the posting list by score, a per-requirement table on the posting page, CV gaps (profile skills that no entry or bullet shows) and learning gaps.

Later changes (ideas, not committed):
- **Clustering unmatched posting skills.** Posting skills with no profile link (`LLM`, `LLMs`) split demand counts. A separate clustering pass should group them into canonical skills.
- **The summary section as a preference signal.** A CV's statement of goals says what the user wants. Ranking could use it.
- **Tailored CV generation** from the profile, with skills and bullets chosen and ordered by what a posting asks for.

Out of scope:
- An eval harness for CV extraction or link quality. The CV sources are well structured, and the user reviews the profile directly.
- Clean-up of near-duplicate profile skills ("Python" and "Python 3"). The user merges these by hand.

## Capabilities

### New Capabilities

- `skill-profile`: the main profile: contact details, sections, entries, bullets, profile skills with levels and evidence, row origin (model or user), editing and reordering, remembered deletions.
- `profile-extraction`: reading a document into the profile: the extraction pipeline and its checks against the document text, run storage, automatic extraction of uploaded CVs, automatic merging, the merge log and rollback.
- `skill-linking`: which skills a posting has, links from posting skills to profile skills (key equality, embedding shortlist, model-judged relation), overrides, automatic re-judging, and where links are shown and changed.

### Modified Capabilities

- `posting-triage`: "Skill levels" uses the five-level scale, and a skill's level is its profile level.
- `application-tracking`: "Documents" extracts text from ODT files, keeping tab stops.
- `llm-connection`: "Model settings" adds the embedding model. "Job queue" adds document-extraction and link-judging jobs, and allows the system to queue link judging and CV extraction without a user request. "Request options" covers embedding requests.

## Impact

- **Order.** Independent of `FUTURE_CHANGE.md` (eval same-line matching). `add-skill-match` follows this change.
- **Code.**
  - `documents.py`: ODT extraction.
  - `db.py` and one migration (`0005`): profile tables, evidence, deletion records, the merge log, link overrides, document runs, embeddings, link judgments, and generalised `llm_jobs`.
  - `userdata.py`: profile writes, merge and rollback, overrides, the new level scale, the embedding-model setting.
  - New `enrich/` modules: CV segmentation, line labelling and skill extraction; embeddings and link judging. `enrich/ollama.py` gains an embedding call. `enrich/derived.py` writes the new derived tables. `enrich/jobs.py` gains the new job kinds and automatic queuing.
  - `queries.py`: profile and link read models.
  - `web/`: a profile page and a merge history, plus link display and overrides on the skills page.
- **Data kinds.**
  - Profile content, evidence, levels, deletion records, the merge log and link overrides are user-authored, written only by `userdata.py`. Model-made profile rows are user-authored rows marked "from model": a merge copies verified run output into them, as accepting a suggestion does today.
  - Document runs, embeddings and link judgments are derived, written only by `enrich/derived.py`.
  - Marks, rejected suggestions and the eval are unchanged.
- **Dependencies.** None. ODT is a zip of XML, read with the standard library. Similarity is computed in Python.
- **GPU.** CV extraction and link judging run on the user's GPU through the queue, sometimes queued automatically. A full link pass is about one short call per distinct posting skill (around 250 today), and later passes only judge what changed. Building and testing need no GPU. Tests use the existing fakes.
- **Docs.** CLAUDE.md: architecture, data kinds, settings, the profile and the new tables.
