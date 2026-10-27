## Purpose

Recommends which postings to look at first, by how well the user's profile covers the skills each asks for and how interested the user is, and which skills would raise those matches most if the user learned them.

## ADDED Requirements

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
The system SHALL rank postings by match score times an interest factor: the user's interest rating divided by 3, with an unrated posting counting as 3. Ties SHALL be broken by last seen, newest first. Postings that are dismissed, that have an application, or that have no score SHALL be left out; the number left out for having no skills SHALL be stated. The top 20 SHALL be shown, each with its title, company, score, the number of its skills without a link, up to three gaps (the skills that lose the most weighted credit, required first), a link to its detail page and its original-posting link.

#### Scenario: Interest lifts a posting
- **WHEN** posting A scores 50% with interest 5 and posting B scores 60% unrated
- **THEN** A is ranked above B (0.83 against 0.60)

#### Scenario: Dismissed and applied postings
- **WHEN** a posting is dismissed, or has an application
- **THEN** it is not among the recommended postings

### Requirement: Skill recommendations
The system SHALL rank candidate skills by their gain: the rise in match score, times the interest factor, summed over the postings that posting recommendations would consider, if the user had the skill at `proficient`. Candidates SHALL be:
- each posting skill without a link, by identity; having it would give it credit 0.85 wherever it is asked for
- each profile skill below `proficient`, including `missing`; having it would raise its level to `proficient`, and so the credit of every posting skill with a link to it

Candidates with no gain SHALL be left out. The top 15 SHALL be shown, each with its gain in percentage points, its current level (for a profile skill), the number of postings it would improve, and up to five of those postings, most improved first.

#### Scenario: Asked for more often
- **WHEN** `AWS` (no link) would raise two unrated postings by 0.34 each and `Docker` (no link) would raise one unrated posting by 0.2
- **THEN** `AWS` (+68) is ranked above `Docker` (+20)

#### Scenario: Variants grouped under a missing skill
- **WHEN** the profile has `AWS` at `missing`, a posting asks for `AWS` and another asks for `Amazon Bedrock`, which is judged `general` to `AWS`
- **THEN** `AWS` is one candidate whose gain counts both postings (credits 0.85 and 0.51), and `Amazon Bedrock` is not a candidate of its own

#### Scenario: Skill already proficient
- **WHEN** a posting skill's only link is to a profile skill at `proficient` or `expert`
- **THEN** neither of them is a candidate

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
