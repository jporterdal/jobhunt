## Purpose

The user's main profile: a structured, user-owned record of their CV content and skills, kept separate from formatting. Documents and manual edits build it, and matching and later CV generation read it.

## ADDED Requirements

### Requirement: Profile structure
The system SHALL keep one profile, made of ordered sections. Each section SHALL have a name and a kind: `contact`, `summary`, `claims`, `experience`, `education`, `publication`, `project` or `other`.
- **Entries.** A section SHALL hold ordered entries (such as a role, a degree or a paper), each with an optional title, organisation, location, start date, end date and URL, and a flag for an entry that is ongoing. Dates SHALL be stored to the precision the source gives, either a year or a year and month.
- **Items.** A section SHALL also hold ordered items (bullets, lines of prose or contact details), either inside an entry or directly under the section. Each item SHALL have text, and SHALL allow an optional label (such as "Email") and its own start and end dates.

The profile SHALL store content only: no fonts, emphasis or page layout.

#### Scenario: Claims directly under a section
- **WHEN** the profile has a `claims` section named "Skills & Experience" with the item "8+ years experience with Python (incl. NumPy, scikit-learn)"
- **THEN** the item belongs to the section without belonging to any entry

#### Scenario: Entry with a detail line and dated items
- **WHEN** an `education` entry has the title "PhD Computer Science", the end date 2022 and an item holding the thesis title, and an `experience` entry has items for courses dated 2016 and 2024
- **THEN** the profile shows each item under its entry, with its own date where it has one

#### Scenario: Ongoing entry
- **WHEN** a `project` entry starts in 2025-03 and is ongoing
- **THEN** it is shown as running from March 2025 to the present

### Requirement: Profile skills and levels
A skill SHALL be part of the profile when it has a level. The levels SHALL form one ordered scale: `missing`, `learning`, `familiar`, `proficient`, `expert`. The user SHALL be able to add a skill to the profile with a level, change its level, and remove it from the profile. Removing a skill SHALL clear its level and its evidence, and SHALL leave its marks on postings unchanged. A skill's level SHALL record whether the model or the user set it.

#### Scenario: Adding a skill by hand
- **WHEN** the user adds `Docker` to the profile at `proficient`
- **THEN** `Docker` is a profile skill at `proficient`, and its level is shown as set by the user

#### Scenario: Removing a skill keeps posting marks
- **WHEN** the user removes `Python` from the profile while three postings mark `Python`
- **THEN** `Python` has no level and no evidence, and the three postings still mark it

### Requirement: Skill evidence
A profile skill SHALL have zero or more pieces of evidence. Each SHALL point at one entry or one item, and SHALL have the quote that names the skill, the number of years claimed (if the source states one), and the document it came from (if any). The user SHALL be able to add evidence by choosing an entry or item, and to remove evidence. The profile SHALL show each skill's evidence with a link to the entry or item it points at.

#### Scenario: Evidence with claimed years
- **WHEN** a merge adds `Python` with the quote "8+ years experience with Python" and claimed years 8, pointing at a claims item
- **THEN** the profile shows `Python` with that quote and 8 years, linked to the claims item

#### Scenario: One skill, several contexts
- **WHEN** `Python` has evidence in a claims item, a course item and a publication entry
- **THEN** the profile lists all three under `Python`

### Requirement: Origin of profile data
Every section, entry, item, piece of evidence and skill level SHALL record whether it came from the model or from the user. A user change to a row's content SHALL make the row the user's. Moving a row up or down SHALL NOT change its origin. Rows that came from the model SHALL be shown as model-derived until the user changes them.

#### Scenario: Editing a model-made bullet
- **WHEN** the user edits the text of a bullet that came from a document merge
- **THEN** the bullet is shown as the user's and no longer as model-derived

#### Scenario: Reordering keeps origin
- **WHEN** the user moves a model-made entry up
- **THEN** the entry is still shown as model-derived

### Requirement: Editing the profile
The user SHALL be able to add, edit and delete sections, entries, items and evidence, change a section's name and kind, and move sections, entries and items up and down within their parent. Deleting a section or entry SHALL also delete everything inside it, including evidence that points at it. Changes SHALL be saved when made, without a separate save step.

#### Scenario: Deleting an entry
- **WHEN** the user deletes an entry that has two items, and `Linux` has evidence pointing at one of the items
- **THEN** the entry, both items and that evidence are gone, and `Linux` stays in the profile with its other evidence

#### Scenario: Changing a section's kind
- **WHEN** the user changes a section from `other` to `project`
- **THEN** the section is shown and treated as a project section

### Requirement: Remembered deletions
When the user deletes a section, entry, item, piece of evidence or profile skill, the system SHALL remember the deletion. Later document merges SHALL NOT add that content back, nor anything inside a deleted section or entry. The user SHALL be able to see remembered deletions and to forget one. Forgetting a deletion SHALL NOT recreate the content, but SHALL let a later merge add it again.

#### Scenario: Deleted entry stays deleted
- **WHEN** the user deletes a model-made entry and then adds another document that describes the same entry
- **THEN** the entry is not added back

#### Scenario: Forgetting a deletion
- **WHEN** the user forgets that deletion and merges the document again
- **THEN** the entry is added back

### Requirement: Profile page
The interface SHALL provide a profile page, reachable from the navigation. It SHALL show the sections in order, each with its entries and items, and a skills panel grouping profile skills by level with their evidence. Every editing action in "Editing the profile" SHALL be available from this page.

#### Scenario: Viewing the profile
- **WHEN** the profile has five sections and twelve skills
- **THEN** the profile page shows the five sections in order, and the twelve skills grouped by level, each with its evidence

### Requirement: Profile data is user-authored
The profile (sections, entries, items, evidence, skill levels, remembered deletions and merge history) SHALL be stored as user-authored data. Importing or re-capturing postings and extracting postings SHALL leave it unchanged. Only the user's edits, document merges and rollbacks SHALL change it, and a merge or rollback SHALL never change a row the user has changed.

#### Scenario: Posting extraction leaves the profile alone
- **WHEN** a posting is extracted and its suggestions name `Kubernetes`, which is not in the profile
- **THEN** the profile is unchanged
