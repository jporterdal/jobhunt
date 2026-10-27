# recommendations Specification

## Purpose

Recommends which postings to look at first, by how well the user's profile covers the skills each asks for and how interested the user is, and which skills would raise those matches most if the user learned them.

## Requirements

### Requirement: Skill credit
Each skill a posting asks for (see "Skills a posting has" in `skill-linking`) SHALL earn a credit between 0 and 1 from the profile: the weight of a link's relation times the weight of the linked profile skill's level.
- Relation weights: `same` 1.0, `specific` 1.0, `general` 0.6, `related` 0.3.
- Level weights: `missing` 0, `learning` 0.25, `familiar` 0.5, `proficient` 0.85, `expert` 1.0.

The links a credit can come from SHALL be found in the same order as "Links to profile skills": the user's override (one link, or none for "no link"), else a profile skill with the same identity (one `same` link), else every relation of the latest judgment to a skill in the profile. The credit SHALL be the highest over those links, and 0 when there are none. The link shown for a posting skill elsewhere SHALL NOT change.

#### Scenario: Same skill at a level
- **WHEN** a posting asks for `python` and the profile has `Python` at `proficient`
- **THEN** its credit is 0.85

#### Scenario: Best credit, not strongest relation
- **WHEN** the latest judgment for `LoRA` relates `LLM fine-tuning` (at `missing`) as `general` and `Large language models` (at `proficient`) as `related`
- **THEN** the link shown for `LoRA` is still `LLM fine-tuning`, `general`, and its credit is 0.255 (0.3 × 0.85)

#### Scenario: No link
- **WHEN** a posting skill has no link, or the user's override is "no link"
- **THEN** its credit is 0

### Requirement: Posting match score
Each posting with at least one skill SHALL have a match score: the average credit of its skills, with each required skill weighing 2 and each preferred skill weighing 1. The score SHALL be shown as a whole percentage, beside the number of the posting's skills that have no link.

#### Scenario: Three skills
- **WHEN** a posting asks for `Python` (required, credit 0.85), `AWS` (required, no link) and `Docker` (preferred, credit 0.6)
- **THEN** its score is 46% ((2 × 0.85 + 2 × 0 + 1 × 0.6) / 5), with 1 of 3 skills unlinked

#### Scenario: Posting without skills
- **WHEN** a posting has no marks and no app run with suggestions
- **THEN** it has no score

### Requirement: Posting recommendations
The system SHALL rank postings by match score times an interest factor: the user's interest rating divided by 3, with an unrated posting counting as 3. Ties SHALL be broken by last seen, newest first. Postings that are dismissed, that have an application, or that have no score SHALL be left out; the number left out for having no skills SHALL be stated. The top 20 SHALL be shown, each with its title, company, workplace type (`On-site`, `Hybrid` or `Remote`, or a dash when the posting has none), score, the number of its skills without a link, up to three gaps (the skills that lose the most weighted credit, required first), a link to its detail page and its original-posting link.

#### Scenario: Interest lifts a posting
- **WHEN** posting A scores 50% with interest 5 and posting B scores 60% unrated
- **THEN** A is ranked above B (0.83 against 0.60)

#### Scenario: Dismissed and applied postings
- **WHEN** a posting is dismissed, or has an application
- **THEN** it is not among the recommended postings

#### Scenario: Workplace type shown
- **WHEN** a recommended posting's latest snapshot has workplace type `Hybrid`, and another has none
- **THEN** the first posting's row shows `Hybrid` and the second's shows a dash

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

### Requirement: Answering a recommended skill
For a recommended posting skill without a link, the user SHALL be able to answer "have it" with a level (`learning`, `familiar`, `proficient` or `expert`), or "don't have it". Either answer SHALL add the skill to the profile under the posting skill's name, as a level the user set: "don't have it" at `missing`. This SHALL work for skills that only the model suggested. For a recommended profile skill, the user SHALL be able to change its level. After an answer, the recommendations SHALL be shown again, computed with it. Answers SHALL follow "Skill self-assessment" in `posting-triage`: the level belongs to the skill, and adding a skill to the profile queues link judging as any profile change does.

#### Scenario: Have it
- **WHEN** the user answers "have it" at `familiar` for the suggested skill `Docker`
- **THEN** `Docker` is in the profile at `familiar` set by the user, every posting asking for `Docker` gets credit 0.5 for it, and `Docker` stays a candidate as a profile skill at `familiar`, with a smaller gain than before

#### Scenario: Don't have it
- **WHEN** the user answers "don't have it" for `AWS`
- **THEN** `AWS` is in the profile at `missing`, its credit stays 0, it stays a candidate as a profile skill at `missing`, and link judging is queued

### Requirement: Recommendations are computed, not stored
Recommendations SHALL be computed from stored data each time they are shown. Computing them SHALL make no model requests and SHALL write nothing. Only answering a skill SHALL change data, and only user-authored data.

#### Scenario: Ollama down
- **WHEN** Ollama is unreachable and the user opens Insights
- **THEN** the recommendations are shown, computed from the stored links and levels

### Requirement: Skill summary on the posting page
A posting's detail page SHALL show a skill summary across the full width of the page, between the posting's header and its description and triage panels. It SHALL show the posting's match score (see "Posting match score"), then two lists:
- **Have**: the posting skills whose credit (see "Skill credit") is above 0. Each SHALL show the posting skill's name, the profile skill its credit comes from, that link's relation and the profile skill's level. The profile skill SHALL be the one giving the highest credit; on a tie, the first in the order of the credit's links. Its name SHALL link to that skill on the profile page. When the profile skill has the same identity as the posting skill, the name SHALL be shown once, as that link.
- **Don't have**: every other posting skill, each with one reason:
  - `missing`, when it has a link but every profile skill it could take credit from is at `missing`; the linked profile skill SHALL be named, as a link to it on the profile page;
  - `not judged yet`, when it has no link, no override and no succeeded link judgment;
  - `no link` otherwise (judged without a usable relation, or the user's "no link" override).

Every posting skill (see "Skills a posting has" in `skill-linking`) SHALL appear in exactly one list. Each list SHALL be split into required and preferred, plus "importance not set" for marks without an importance; empty groups SHALL be left out. Have SHALL be ordered by credit, highest first, then by name; Don't have by name. Skills from the user's marks SHALL be styled as user-authored, and skills from model suggestions as model-derived.

When the posting has no skills, the summary SHALL say so and show no score. When the profile has no skills, the summary SHALL say so, with a link to the profile page.

The summary SHALL be computed from stored data without model requests. When the user changes the posting's skills or a skill's level from the posting page (accepting or rejecting a suggestion, undoing a rejection, changing a mark's importance or level, removing a mark), the summary SHALL be refreshed along with the panel that changed, without reloading the page. When a model run of the posting finishes while the page is open, the summary SHALL be refreshed with the model output.

#### Scenario: Have and don't have
- **WHEN** a posting asks for `Python` (required, profile `Python` at `proficient`), `AWS` (required, judged with no link) and `Docker` (preferred, linked `general` to `Containers` at `expert`)
- **THEN** the summary shows 46%; Have lists `Python` (same, proficient) under required and `Docker` → `Containers` (general, expert) under preferred; Don't have lists `AWS` (no link) under required

#### Scenario: Credit from a weaker link
- **WHEN** the latest judgment for `LoRA` relates `LLM fine-tuning` (at `missing`) as `general` and `Large language models` (at `proficient`) as `related`
- **THEN** Have lists `LoRA` → `Large language models` (related, proficient), and `Large language models` links to that skill on the profile page

#### Scenario: Linked to a missing skill
- **WHEN** a posting asks for `Kubernetes` and the profile has `Kubernetes` at `missing`
- **THEN** Don't have lists `Kubernetes` as `missing`, with a link to `Kubernetes` on the profile page

#### Scenario: Not judged yet
- **WHEN** the user marks `Terraform`, which no profile skill shares an identity with, and no link judgment for it has succeeded yet
- **THEN** Don't have lists `Terraform` as `not judged yet`; once a judgment finds no relation, it is listed as `no link`

#### Scenario: Marks and suggestions told apart
- **WHEN** Have lists `Python` from the user's mark and `Docker` from an unaccepted suggestion
- **THEN** `Python` is styled as user-authored and `Docker` as model-derived

#### Scenario: Refreshed after rejecting
- **WHEN** the user rejects the suggestion `Docker` in "Model says"
- **THEN** without a page reload, `Docker` is no longer in the summary and the score no longer counts it

#### Scenario: Refreshed after a level change
- **WHEN** the user sets `AWS` to `familiar` in "Skills asked for"
- **THEN** without a page reload, Have lists `AWS` (same, familiar) and the score rises

#### Scenario: Posting without skills
- **WHEN** a posting has no marks and no app run with suggestions
- **THEN** the summary says it has no skills yet and shows no score

### Requirement: Workplace filter
Insights SHALL offer a workplace filter with one choice per workplace type (`On-site`, `Hybrid`, `Remote`), all chosen by default. The filter SHALL narrow the postings that recommendations consider, by each posting's latest snapshot, so it applies to both lists:
- posting recommendations, including the number of postings considered and the number left out for having no skills;
- skill recommendations, whose gains are summed over the postings considered.

Choosing every type, or none, SHALL mean no filter, and postings without a workplace type SHALL then be considered. When only some types are chosen, only postings of those types SHALL be considered; postings without a workplace type SHALL be left out.

The chosen types SHALL be encoded in the page URL, so reloading or bookmarking it reproduces the same recommendations. Unknown values SHALL be ignored. The filter SHALL NOT be stored. After the user answers a recommended skill or changes a level on Insights, the recommendations SHALL be shown again under the same filter.

When the filter leaves no posting to consider, both lists SHALL say that no posting of the chosen workplace types is left to recommend, rather than their usual empty messages.

#### Scenario: Default is every posting
- **WHEN** the user opens Insights without choosing any workplace type, and a considered posting has no workplace type
- **THEN** recommendations are the same as with every type chosen, and that posting is considered

#### Scenario: Remote and hybrid only
- **WHEN** the user unchooses `On-site`, and an `On-site` posting is the only one asking for `Kubernetes` (no link)
- **THEN** that posting is not among the recommended postings and is not counted as considered, `Kubernetes` is not a recommended skill, and the URL carries `Hybrid` and `Remote`

#### Scenario: Skill gain from filtered postings only
- **WHEN** `AWS` (no link) would raise one unrated `Remote` posting by 0.3 and one unrated `On-site` posting by 0.4, and only `Remote` is chosen
- **THEN** `AWS`'s gain is +30, improving 1 posting

#### Scenario: Posting without a workplace type
- **WHEN** a posting has no workplace type and only `Remote` is chosen
- **THEN** the posting is not considered

#### Scenario: Unknown value
- **WHEN** the URL's workplace values are `Remote` and `Moon`
- **THEN** only `Remote` is chosen; and when its only value is `Moon`, there is no filter

#### Scenario: Filter kept after an answer
- **WHEN** only `Remote` is chosen and the user answers "don't have it" for `AWS`
- **THEN** the recommendations shown next are computed with `AWS` at `missing` and only `Remote` chosen

#### Scenario: Nothing of the chosen types
- **WHEN** only `On-site` is chosen and every `On-site` posting is dismissed
- **THEN** both lists say no posting of the chosen workplace types is left to recommend
