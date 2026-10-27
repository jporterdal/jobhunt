## ADDED Requirements

### Requirement: User-authored triage data
Ratings, tags, notes, dismissals, skill marks (with their importance and origin), skill levels, the skill-labelling-complete flag and rejected model suggestions SHALL be stored as user-authored data keyed by job ID (skills by their own identity). Re-capturing a posting SHALL leave them unchanged. Extracting a posting with a model SHALL leave them unchanged, except when the user explicitly accepts or rejects a suggestion. Accepting a document suggestion SHALL change skill levels only as "Offered suggestions" in `profile-extraction` allows, and SHALL never change a level the user set.

#### Scenario: Re-capture after triage
- **WHEN** a rated, tagged posting is re-captured with a changed description
- **THEN** its ratings, tags, notes and skill marks are unchanged

#### Scenario: Extraction after triage
- **WHEN** a posting with skill marks and a rejected suggestion is extracted again
- **THEN** its marks, importances and rejections are unchanged

#### Scenario: Document suggestion after triage
- **WHEN** the user set `Kubernetes` to `missing` and a document run suggests `Kubernetes` at `familiar`
- **THEN** no change to `Kubernetes`'s level is offered, and it stays at `missing`

## MODIFIED Requirements

### Requirement: Skill self-assessment
For each skill, the user SHALL be able to record their own level as `missing`, `learning`, `familiar`, `proficient` or `expert`, or leave it unset. The levels SHALL form an ordered scale in that order. The level SHALL belong to the skill's claim (see "Claims and levels" in `skill-profile`), not to a posting, and SHALL be shown wherever the skill is marked. For a skill that is an alias of another, the level SHALL be that of the other skill's claim, and setting it SHALL set the other skill's claim. Setting a level from a posting or the skills page SHALL create the claim when the skill has none, adding the skill to the profile, and clearing it SHALL remove the claim, removing the skill from the profile. A skills page SHALL list every skill with its level, whether it is in the profile, the number of postings that ask for it, and how many of those postings the user rated 4 or more for interest.

#### Scenario: Setting a level
- **WHEN** the user sets `Kubernetes` to `missing` on one posting's detail page
- **THEN** every posting that marks Kubernetes shows it as missing, and `Kubernetes` has a claim at `missing`

#### Scenario: Level of an alias
- **WHEN** `Postgres` is an alias of `PostgreSQL`, whose claim is at `proficient`
- **THEN** a posting that marks `Postgres` shows it at `proficient`

#### Scenario: Skills page
- **WHEN** three postings mark `PyTorch` and two of them have interest 4 or more
- **THEN** the skills page shows `PyTorch` with 3 postings, 2 of them high-interest

#### Scenario: Old level values
- **WHEN** a database holds skills with the level `have` from before this change
- **THEN** after migration those skills are at `proficient`

## REMOVED Requirements

### Requirement: Triage data is user-authored
**Reason**: It allowed document merges to change skill levels; document runs now only suggest. Replaced by "User-authored triage data", which states the same rules for accepted document suggestions.
**Migration**: None needed; the stored data is unchanged.
