# skill-linking Specification

## Purpose

Linking each skill a posting asks for to the user's own profile skills, so postings and profile can be compared even when they name the same skill differently. Model-judged links count until the user overrides them.

## Requirements

### Requirement: Skills a posting has
A posting's skills SHALL be:
- its skill marks, with their importance and quote
- plus the verified suggestions from its latest successful app run on its latest snapshot (see "Derived data is stored separately and never edited" in `posting-enrichment`), except suggestions the user rejected for that posting, for any reason.

When a mark and a suggestion name the same skill, the mark SHALL be used. A posting skill SHALL be identified by its name, trimmed, case-insensitively and with whitespace collapsed. Posting skills from runs on older snapshots SHALL NOT be used, and neither SHALL posting skills from eval runs.

#### Scenario: Marks and suggestions combined
- **WHEN** a posting has the mark `Python` (required), and its latest run on the latest snapshot suggests `python` (preferred), `Docker` and `Kubernetes`, of which `Kubernetes` was rejected as not for me
- **THEN** the posting's skills are `Python` (required, from the mark) and `Docker`

#### Scenario: Unverified suggestion left out
- **WHEN** the latest run has an unverified suggestion `Terraform`
- **THEN** `Terraform` is not one of the posting's skills

#### Scenario: Eval run left out
- **WHEN** a labelled posting has 26 marks, no app run, and an eval run that suggests `Prompt engineering`, which no mark names
- **THEN** the posting's skills are its 26 marks, `Prompt engineering` is not among them, and link judging doesn't consider it for this posting

### Requirement: Links to profile skills
Each posting skill SHALL have at most one link to a profile skill (a skill with a claim, see "Claims and levels" in `skill-profile`), with one of these relations, stated from the profile skill's side:
- `same`: the same skill
- `specific`: the profile skill is a specific form of the posting skill
- `general`: the profile skill is a more general form of the posting skill
- `related`: they overlap, but neither is a form of the other

The link SHALL be found in this order:
1. The user's override, if there is one (see "Link overrides").
2. A profile skill with the same identity as the posting skill, or of which the posting skill's identity is an alias (see "Skill aliases" in `skill-profile`), as `same`, without a model request.
3. Otherwise, candidates are found by comparing skills by embedding similarity. The app's current method SHALL compare names: each skill's name is embedded, and a profile skill's similarity to the posting skill is that of the two names. A method that expands (see "Skill expansion") compares phrases instead: each skill's phrases are its name and its expansion's phrasings, each embedded on its own, and a profile skill's similarity is that of their most similar pair of phrases. The most similar profile skills, up to the method's fixed number and above its similarity floor, go to the model. The model judges each one's relation, and the strongest relation wins, in the order `same`, `specific`, `general`, `related`.

A posting skill with no candidate above the floor, or whose candidates the model judges unrelated, SHALL have no link, without further requests. The app SHALL use one linking method, named by the code: one way of finding candidates and one judging version. It SHALL NOT offer a choice between linking methods.

#### Scenario: Same identity
- **WHEN** a posting asks for `python` and the profile has `Python`
- **THEN** the link is `Python`, `same`, and no model request is made for it

#### Scenario: Alias
- **WHEN** a posting asks for `Postgres`, and `Postgres` is an alias of the profile skill `PostgreSQL`
- **THEN** the link is `PostgreSQL`, `same`, and no model request is made for it

#### Scenario: Specific form
- **WHEN** a posting asks for `CI/CD`, the profile has `GitHub Actions`, and the model judges it a specific form
- **THEN** the link is `GitHub Actions`, `specific`

#### Scenario: Strongest relation wins
- **WHEN** the model judges `LLM fine-tuning` as `general` and `Large language models` as `related` for the posting skill `LoRA`
- **THEN** the link is `LLM fine-tuning`, `general`

#### Scenario: Nothing similar
- **WHEN** no profile skill is above the similarity floor for `Salesforce`
- **THEN** `Salesforce` has no link and no model request is made for it

#### Scenario: Similar meaning, different spelling
- **WHEN** a method that expands is measured, the posting skill `Claude Code` has the phrasing `AI coding agent`, the profile skill `agentic AI workflows` has the phrasing `AI agent workflows`, and that pair is more similar than any pair involving the bare names
- **THEN** `agentic AI workflows`'s similarity to `Claude Code` is the similarity of that pair

### Requirement: Model links count until overridden
A link judged by the model SHALL take effect as soon as it is stored, without review. Each link SHALL show its source: same identity, model, or the user. The latest successful judgment of a posting skill SHALL be used until a newer one succeeds. A judged relation to a skill that has since left the profile SHALL be ignored.

#### Scenario: Link used before review
- **WHEN** the model links `CI/CD` to `GitHub Actions` and the user has not looked at it
- **THEN** the link is in effect and is shown as from the model

### Requirement: Link overrides
For any posting skill, the user SHALL be able to choose a profile skill and a relation, or choose "no link", and to remove that choice. A user choice SHALL take precedence over every other source and SHALL never be judged again. A choice naming a skill that has since left the profile SHALL be shown as stale and SHALL NOT take effect until the skill is in the profile again or the user changes the choice.

#### Scenario: Overriding a model link
- **WHEN** the model linked `MLOps` to `Docker` as `related` and the user chooses "no link"
- **THEN** `MLOps` has no link, and later judging never changes that

#### Scenario: Stale override
- **WHEN** the user linked `Spark` to `PySpark` and then removed `PySpark` from the profile
- **THEN** the override is shown as stale and `Spark` is linked as if there were no override

### Requirement: Re-judging when skills change
Judging SHALL be queued automatically, without a user request, after:
- the user accepting a document suggestion that adds or changes a claim, ground or highlight coverage
- the user adding, renaming or removing a profile skill, adding or removing a ground or a highlight's coverage of a claim, merging a skill into another, or removing an alias
- a posting run that succeeds
- the user adding or removing a mark, or rejecting a suggestion or undoing a rejection
- a change of embedding model
- the start of the web interface, when some posting skill's latest judgment was made by a linking method version other than the current one.

A queued judging job SHALL first expand the skills that need it when the current method expands (see "Skill expansion"), then judge only the posting skills that have no user choice and no same-identity profile skill, and that either have never been judged, or whose candidate profile skills, embedding model or linking method version differ from those of their latest judgment. A posting skill's latest judgment SHALL keep taking effect until it is judged again. At most one judging job SHALL wait in the queue at a time. A change of chat model SHALL NOT cause re-judging or expansion by itself. The links page SHALL offer an action to re-judge every posting skill without a user choice.

#### Scenario: New closer profile skill
- **WHEN** `CI/CD` was judged against candidates that did not include `GitHub Actions`, and the user adds `GitHub Actions` to the profile and it is among the top candidates
- **THEN** `CI/CD` is judged again, and posting skills whose candidates did not change are not

#### Scenario: Accepting a claim suggestion
- **WHEN** the user accepts a document's claim suggestion for `Docker`
- **THEN** a judging job is queued

#### Scenario: Nothing changed
- **WHEN** a judging job runs and no posting skill's candidates have changed since its latest judgment
- **THEN** no model requests are made

#### Scenario: Changes coalesce
- **WHEN** the user adds three profile skills in a row while a judging job is waiting in the queue
- **THEN** the queue still holds one waiting judging job

#### Scenario: New linking method version
- **WHEN** the code's linking method becomes `link-judge@5` while every posting skill's latest judgment was made with `link-judge@2`
- **THEN** starting the web interface queues a judging job that judges every posting skill without a user choice or same-identity profile skill again, and each keeps its `link-judge@2` link until its new judgment is stored

#### Scenario: Start-up with nothing to re-judge
- **WHEN** the web interface starts and every latest judgment was made with the current linking method
- **THEN** no judging job is queued at start-up

### Requirement: Links page
The interface SHALL provide a page, reachable from the profile page, listing every posting skill with its number of postings, its link (profile skill and relation) or "no link", and the link's source. It SHALL be sorted by number of postings, most first. Each row SHALL offer the override actions from "Link overrides". Each profile skill on the profile page SHALL show the posting skills linked to it.

#### Scenario: Most-asked skills first
- **WHEN** `Python` appears in 9 postings and `Dask` in 2
- **THEN** `Python` is listed above `Dask`

### Requirement: Link data kinds
Model judgments, expansions and the embeddings used to shortlist candidates SHALL be stored as derived data that is never edited. A new judgment or expansion SHALL add a record. Link overrides SHALL be stored as user-authored data, and judging SHALL never change them. Skill marks, rejected suggestions and the evaluation's results SHALL NOT be changed by linking. Judgments made while measuring links (see `link-evaluation`) SHALL be stored apart from the app's judgments and SHALL never determine a link.

#### Scenario: Re-judging keeps history
- **WHEN** `CI/CD` is judged a second time
- **THEN** both judgments are stored, and the newer one is used

#### Scenario: Measuring doesn't change links
- **WHEN** link measurement judges the overridden posting skill `Git` with a candidate judging version, and the user then removes the override on `Git`
- **THEN** `Git`'s link comes from the app's own latest judgment, not from the measurement

### Requirement: Skill expansion
A candidate-finding method MAY expand skills before candidates are found: it asks the chat model for up to six alternative phrasings of each skill, namely synonyms, the expanded form of an abbreviation, the usual name of the tool or practice, and a short description of what kind of skill it is. The request SHALL include the skill's name and its context: for a posting skill, one quote from a posting that asks for it; for a profile skill, its expansion context (see "Expansion context from grounds and highlights"), or no context when it has none. Phrasings that have the same identity as the skill's name or as an earlier phrasing, and phrasings longer than eight words, SHALL be dropped.

Skills SHALL be expanded only for a method that expands: by a judging job when the app's current method expands, and by link measurement for the methods it measures (see `link-evaluation`). The app's current method compares names and SHALL NOT expand. A method that expands SHALL expand every profile skill, and every posting skill that is judged (no user choice and no same-identity profile skill). A posting skill SHALL be expanded once per expansion step version, whatever later quotes it has. A profile skill SHALL be expanded once per expansion step version and context. Expansions SHALL be reused rather than requested again, by the app and by measurement alike. When an expansion fails, the skill SHALL be compared by its name alone, and expansion SHALL be tried again by the next judging job or measurement.

#### Scenario: The app's method doesn't expand
- **WHEN** a judging job runs while the app's current method compares names
- **THEN** no expansion request is made

#### Scenario: Ambiguous name read in context
- **WHEN** a posting asks for `Attention` with the quote "experience with attention mechanisms in transformers", and a method that expands is measured
- **THEN** the expansion request includes that quote, and the stored phrasings are about the neural-network technique

#### Scenario: Duplicate phrasings dropped
- **WHEN** the model answers `["claude code", "AI coding agent", "AI coding agent", "a command-line AI coding assistant made by Anthropic for writing code"]` for `Claude Code`
- **THEN** the stored phrasings are `AI coding agent` only

#### Scenario: Expanded once
- **WHEN** `Docker` was expanded and a new posting also asks for `Docker` with a different quote
- **THEN** no new expansion request is made for `Docker`

#### Scenario: Failed expansion
- **WHEN** the expansion request for `Kubernetes` fails while a method that expands is in use
- **THEN** `Kubernetes` is compared by its name that time, and the next judging job or measurement requests its expansion again

### Requirement: Expansion context from grounds and highlights
A profile skill's expansion context SHALL be the quote of the oldest of its claim's grounds and highlight coverages, by when each was added, or no context when it has none or the oldest has no quote. Grounds and coverage carried over by the upgrade (see "Upgrading an existing profile" in `skill-profile`) SHALL keep the time their evidence was added, so each profile skill keeps the context it had before the upgrade.

When a profile skill's expansion context changes, a method that expands SHALL expand the skill again for the new context. An expansion made for an earlier context SHALL be reused if that context returns. Model judging requests SHALL show each candidate profile skill with its expansion context, or, for a judging version that shows CV lines, with the line the context was found in: the description line of the ground's record that contains the quote (else the record's title and organisation), or the covering highlight's text.

#### Scenario: A later ground doesn't change the context
- **WHEN** `Python`'s context is the quote of its ground on "tidyplots", and the user later accepts a ground on "price_tracker"
- **THEN** `Python`'s expansion context is unchanged, and no expansion request is made for it

#### Scenario: Removing the oldest ground
- **WHEN** the user removes `Python`'s ground on "tidyplots", and its next oldest is a highlight's coverage with the quote "8+ years experience with Python"
- **THEN** `Python`'s expansion context is that quote, and a method that expands expands it for that context

#### Scenario: A skill added by hand
- **WHEN** the user adds `Rust` to the profile without grounds
- **THEN** `Rust`'s expansion context is none, and it becomes the quote of the first ground or coverage the user adds

#### Scenario: Context kept by the upgrade
- **WHEN** before the upgrade `NumPy`'s oldest evidence was a claims item with the quote "NumPy", and that item becomes a highlight
- **THEN** after the upgrade `NumPy`'s expansion context is still "NumPy", and the judge is shown the same context as before
