## ADDED Requirements

### Requirement: Skill expansion
A candidate-finding method MAY expand skills before candidates are found: it asks the chat model for up to six alternative phrasings of each skill, namely synonyms, the expanded form of an abbreviation, the usual name of the tool or practice, and a short description of what kind of skill it is. The request SHALL include the skill's name and its context: for a posting skill, one quote from a posting that asks for it; for a profile skill, its expansion context (see "Expansion context of a profile skill"), or no context when it has none. Phrasings that have the same identity as the skill's name or as an earlier phrasing, and phrasings longer than eight words, SHALL be dropped.

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

### Requirement: Expansion context of a profile skill
A profile skill's expansion context SHALL be the quote of one of its evidence records, chosen in this order:
1. The first evidence that the newest merge recorded as rewriting phrasings added to the skill, among merges that have not been rolled back.
2. Otherwise, its oldest evidence.
3. Otherwise, no context.

A document extraction job MAY carry the choice to rewrite phrasings. Its merge SHALL record the choice, and merging a rolled-back run again SHALL keep the merge's original choice. The web interface SHALL NOT offer the choice while the app's current method doesn't expand, so merges made from it SHALL be recorded as not rewriting phrasings.

When a profile skill's expansion context changes, a method that expands SHALL expand the skill again for the new context. An expansion made for an earlier context SHALL be reused if that context returns. Model judging requests SHALL show each candidate profile skill with its expansion context, or, for a judging version that shows CV lines, with the CV line that context was found in.

#### Scenario: Evidence from a later document doesn't change phrasings
- **WHEN** `Python` was expanded from its evidence in `cv-2025.odt`, and a merge of `cv-2026.odt` that doesn't rewrite phrasings adds new evidence for `Python`
- **THEN** `Python`'s expansion context is unchanged, and no expansion request is made for it

#### Scenario: Rewriting phrasings from a document
- **WHEN** a merge of `cv-2026.odt` recorded as rewriting phrasings adds evidence for `Python`
- **THEN** `Python`'s expansion context is its evidence from `cv-2026.odt`, and a method that expands expands it again

#### Scenario: Rolling back the rewriting merge
- **WHEN** the merge of `cv-2026.odt` that rewrote `Python`'s phrasings is rolled back
- **THEN** `Python`'s expansion context is its evidence from `cv-2025.odt` again, and its earlier expansion is used without a new request

#### Scenario: A skill added by hand
- **WHEN** the user adds `Rust` to the profile without evidence
- **THEN** `Rust`'s expansion context is none, and it becomes the quote of the first evidence the user adds

#### Scenario: No choice offered
- **WHEN** the user uploads a CV in the web interface
- **THEN** the upload offers no option to rewrite phrasings, and the document's merge is recorded as not rewriting them

## MODIFIED Requirements

### Requirement: Links to profile skills
Each posting skill SHALL have at most one link to a profile skill, with one of these relations, stated from the profile skill's side:
- `same`: the same skill
- `specific`: the profile skill is a specific form of the posting skill
- `general`: the profile skill is a more general form of the posting skill
- `related`: they overlap, but neither is a form of the other

The link SHALL be found in this order:
1. The user's override, if there is one (see "Link overrides").
2. A profile skill with the same identity as the posting skill, as `same`, without a model request.
3. Otherwise, candidates are found by comparing skills by embedding similarity. The app's current method SHALL compare names: each skill's name is embedded, and a profile skill's similarity to the posting skill is that of the two names. A method that expands (see "Skill expansion") compares phrases instead: each skill's phrases are its name and its expansion's phrasings, each embedded on its own, and a profile skill's similarity is that of their most similar pair of phrases. The most similar profile skills, up to the method's fixed number and above its similarity floor, go to the model. The model judges each one's relation, and the strongest relation wins, in the order `same`, `specific`, `general`, `related`.

A posting skill with no candidate above the floor, or whose candidates the model judges unrelated, SHALL have no link, without further requests. The app SHALL use one linking method, named by the code: one way of finding candidates and one judging version. It SHALL NOT offer a choice between linking methods.

#### Scenario: Same identity
- **WHEN** a posting asks for `python` and the profile has `Python`
- **THEN** the link is `Python`, `same`, and no model request is made for it

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

### Requirement: Re-judging when skills change
Judging SHALL be queued automatically, without a user request, after:
- a document merge or its rollback
- the user adding, renaming or removing a profile skill, or adding or removing a profile skill's evidence
- a posting run that succeeds
- the user adding or removing a mark, or rejecting a suggestion or undoing a rejection
- a change of embedding model
- the start of the web interface, when some posting skill's latest judgment was made by a linking method version other than the current one.

A queued judging job SHALL first expand the skills that need it when the current method expands (see "Skill expansion"), then judge only the posting skills that have no user choice and no same-identity profile skill, and that either have never been judged, or whose candidate profile skills, embedding model or linking method version differ from those of their latest judgment. A posting skill's latest judgment SHALL keep taking effect until it is judged again. At most one judging job SHALL wait in the queue at a time. A change of chat model SHALL NOT cause re-judging or expansion by itself. The links page SHALL offer an action to re-judge every posting skill without a user choice.

#### Scenario: New closer profile skill
- **WHEN** `CI/CD` was judged against candidates that did not include `GitHub Actions`, and the user adds `GitHub Actions` to the profile and it is among the top candidates
- **THEN** `CI/CD` is judged again, and posting skills whose candidates did not change are not

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

### Requirement: Link data kinds
Model judgments, expansions and the embeddings used to shortlist candidates SHALL be stored as derived data that is never edited. A new judgment or expansion SHALL add a record. Link overrides SHALL be stored as user-authored data, and judging SHALL never change them. Skill marks, rejected suggestions and the evaluation's results SHALL NOT be changed by linking. Judgments made while measuring links (see `link-evaluation`) SHALL be stored apart from the app's judgments and SHALL never determine a link.

#### Scenario: Re-judging keeps history
- **WHEN** `CI/CD` is judged a second time
- **THEN** both judgments are stored, and the newer one is used

#### Scenario: Measuring doesn't change links
- **WHEN** link measurement judges the overridden posting skill `Git` with a candidate judging version, and the user then removes the override on `Git`
- **THEN** `Git`'s link comes from the app's own latest judgment, not from the measurement
