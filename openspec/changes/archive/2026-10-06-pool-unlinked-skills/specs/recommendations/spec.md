## MODIFIED Requirements

### Requirement: Skill recommendations
The system SHALL rank candidate skills by their gain: the rise in match score, times the interest factor, summed over the postings that posting recommendations would consider, if the user had the skill at `proficient`. Candidates SHALL be:
- each pool of posting skills without a link (see "Pooled unlinked skills"); having it would give every member credit 0.85 wherever it is asked for
- each profile skill below `proficient`, including `missing`; having it would raise its level to `proficient`, and so the credit of every posting skill with a link to it

Candidates with no gain SHALL be left out. The top 15 SHALL be shown, each with its gain in percentage points, its current level (for a profile skill), the other names in its pool (for a pool with more than one member), the number of postings it would improve, and up to five of those postings, most improved first.

#### Scenario: Asked for more often
- **WHEN** `AWS` (no link) would raise two unrated postings by 0.34 each and `Docker` (no link) would raise one unrated posting by 0.2
- **THEN** `AWS` (+68) is ranked above `Docker` (+20)

#### Scenario: Variants grouped under a missing skill
- **WHEN** the profile has `AWS` at `missing`, a posting asks for `AWS` and another asks for `Amazon Bedrock`, which is judged `general` to `AWS`
- **THEN** `AWS` is one candidate whose gain counts both postings (credits 0.85 and 0.51), and `Amazon Bedrock` is not a candidate of its own

#### Scenario: Skill already proficient
- **WHEN** a posting skill's only link is to a profile skill at `proficient` or `expert`
- **THEN** neither of them is a candidate

## ADDED Requirements

### Requirement: Pooled unlinked skills
Posting skills without a link, among those asked for by the postings that posting recommendations would consider, SHALL be grouped into pools for skill recommendations:
- Skills SHALL be taken in order of the number of those postings asking for them, most first, then shorter name first, then by identity.
- Each skill SHALL join the existing pool whose first member it is most similar to, among the pools it qualifies for. It qualifies for a pool when its name embedding and the first member's have a cosine similarity of at least 0.90, or when every word of the first member's name appears, whole and in order, in its name (case, hyphens and a plural `s` ignored) and their similarity is at least 0.80.
- A skill that qualifies for no pool SHALL start a new pool. A pool SHALL be named after its first member.

Similarity SHALL use the name embeddings stored by link judging, for the embedding model of the newest link judgment. A skill without a stored embedding for that model SHALL be in a pool of its own. When no link judgment exists, every skill SHALL be in a pool of its own. Pools SHALL affect only skill recommendations: match scores, gaps and posting recommendations SHALL count each posting skill as before. Pooling SHALL make no model requests and SHALL store nothing.

#### Scenario: One name inside another
- **WHEN** `fine-tuning` is asked for in 9 postings and `LLM fine-tuning` in 4, both without a link, and their similarity is 0.857
- **THEN** they are one candidate named `fine-tuning`, its gain counts every posting asking for either, and its row lists `LLM fine-tuning`

#### Scenario: Similar names
- **WHEN** `Azure` and `Microsoft Azure` have no link and a similarity of 0.957
- **THEN** they are one candidate named after whichever is asked for in more postings

#### Scenario: A shared word is not enough
- **WHEN** `Planning` and `Sprint planning` have no link and a similarity of 0.78
- **THEN** they are separate candidates

#### Scenario: Pools don't chain
- **WHEN** `Kubernetes` is asked for most, `Container orchestration` has similarity 0.92 to it, and `Containers` has similarity 0.92 to `Container orchestration` but 0.85 to `Kubernetes`, with no shared words
- **THEN** `Kubernetes` and `Container orchestration` are one pool, and `Containers` starts its own

#### Scenario: Linked skills are not pooled
- **WHEN** `Docker` has a link to a profile skill and the unlinked `Containerization` is similar to it
- **THEN** `Containerization` is not pooled with `Docker`

#### Scenario: No stored embeddings
- **WHEN** link judging has never run
- **THEN** every unlinked posting skill is a candidate of its own, as before pooling

#### Scenario: Answering a pool
- **WHEN** the user answers "don't have it" for the pool `fine-tuning` that also holds `LLM fine-tuning`
- **THEN** `fine-tuning` is added to the profile at `missing` and link judging is queued, and `LLM fine-tuning` is a candidate apart from it until a judgment links it to `fine-tuning`
