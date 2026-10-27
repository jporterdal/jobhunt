## Purpose

Linking each skill a posting asks for to the user's own profile skills, so postings and profile can be compared even when they name the same skill differently. Model-judged links count until the user overrides them.

## ADDED Requirements

### Requirement: Skills a posting has
A posting's skills SHALL be:
- its skill marks, with their importance and quote
- plus the verified suggestions from its latest successful run on its latest snapshot, except suggestions the user rejected for that posting, for any reason.

When a mark and a suggestion name the same skill, the mark SHALL be used. A posting skill SHALL be identified by its name, trimmed, case-insensitively and with whitespace collapsed. Posting skills from runs on older snapshots SHALL NOT be used.

#### Scenario: Marks and suggestions combined
- **WHEN** a posting has the mark `Python` (required), and its latest run on the latest snapshot suggests `python` (preferred), `Docker` and `Kubernetes`, of which `Kubernetes` was rejected as not for me
- **THEN** the posting's skills are `Python` (required, from the mark) and `Docker`

#### Scenario: Unverified suggestion left out
- **WHEN** the latest run has an unverified suggestion `Terraform`
- **THEN** `Terraform` is not one of the posting's skills

### Requirement: Links to profile skills
Each posting skill SHALL have at most one link to a profile skill, with one of these relations, stated from the profile skill's side:
- `same`: the same skill
- `specific`: the profile skill is a specific form of the posting skill
- `general`: the profile skill is a more general form of the posting skill
- `related`: they overlap, but neither is a form of the other

The link SHALL be found in this order:
1. The user's override, if there is one (see "Link overrides").
2. A profile skill with the same identity as the posting skill, as `same`, without a model request.
3. Otherwise, the most similar profile skills by embedding, up to a fixed number and above a similarity floor, go to the model. The model judges each one's relation, and the strongest relation wins, in the order `same`, `specific`, `general`, `related`.

A posting skill with no candidate above the floor, or whose candidates the model judges unrelated, SHALL have no link, without further requests.

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
- a document merge or its rollback
- the user adding, renaming or removing a profile skill
- a posting run that succeeds
- the user adding or removing a mark, or rejecting a suggestion or undoing a rejection
- a change of embedding model.

A queued judging job SHALL judge only the posting skills that have no user choice and no same-identity profile skill, and that either have never been judged or whose candidate profile skills or embedding model differ from those of their latest judgment. At most one judging job SHALL wait in the queue at a time. A change of chat model SHALL NOT cause re-judging by itself. The links page SHALL offer an action to re-judge every posting skill without a user choice.

#### Scenario: New closer profile skill
- **WHEN** `CI/CD` was judged against candidates that did not include `GitHub Actions`, and the user adds `GitHub Actions` to the profile and it is among the top candidates
- **THEN** `CI/CD` is judged again, and posting skills whose candidates did not change are not

#### Scenario: Nothing changed
- **WHEN** a judging job runs and no posting skill's candidates have changed since its latest judgment
- **THEN** no model requests are made

#### Scenario: Changes coalesce
- **WHEN** the user adds three profile skills in a row while a judging job is waiting in the queue
- **THEN** the queue still holds one waiting judging job

### Requirement: Links page
The interface SHALL provide a page, reachable from the profile page, listing every posting skill with its number of postings, its link (profile skill and relation) or "no link", and the link's source. It SHALL be sorted by number of postings, most first. Each row SHALL offer the override actions from "Link overrides". Each profile skill on the profile page SHALL show the posting skills linked to it.

#### Scenario: Most-asked skills first
- **WHEN** `Python` appears in 9 postings and `Dask` in 2
- **THEN** `Python` is listed above `Dask`

### Requirement: Link data kinds
Model judgments and the embeddings used to shortlist candidates SHALL be stored as derived data that is never edited. A new judgment SHALL add a record. Link overrides SHALL be stored as user-authored data, and judging SHALL never change them. Skill marks, rejected suggestions and the evaluation's results SHALL NOT be changed by linking.

#### Scenario: Re-judging keeps history
- **WHEN** `CI/CD` is judged a second time
- **THEN** both judgments are stored, and the newer one is used
