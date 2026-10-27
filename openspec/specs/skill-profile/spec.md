# skill-profile Specification

## Purpose

The user's main profile as a knowledge base that CVs are generated from: records (facts, with dates, lines, sources, disclosure and context links), claims (one per skill, holding the level, grounded by records), highlights (CV wording covering claims), skill aliases and flat profile details. The user owns every row: documents only suggest, and matching and CV generation read it.

## Requirements

### Requirement: Records
The profile SHALL hold records: facts about the user's work and history. Each record SHALL have:
- a kind, one of `role`, `course`, `project`, `publication`, `degree`, `award`, `event`, `task` or `other`;
- an optional title, organisation and location;
- an optional start date and end date, each stored to the precision known (a year, or a year and month), and a flag for a record that is ongoing;
- ordered description lines, each with text;
- zero or more sources, each a web address (of kind repository, site, DOI or other) or an uploaded document.

Records SHALL be flat: no record contains another. Dates SHALL be stored on records only, not on lines, claims or highlights. Records of one kind SHALL be listed by end date (start date when there is none), newest first, with ongoing records first and records without dates last; records that tie SHALL be listed in the order they were created. The profile SHALL store content only: no fonts, emphasis or page layout.

#### Scenario: A project with lines and sources
- **WHEN** the profile has a `project` record "city-parking" with three description lines, a repository address and no dates
- **THEN** the profile shows the record with its lines in order and its repository as a link, listed after the dated projects

#### Scenario: One record per term taught
- **WHEN** the user taught COMP 1000 at Example Polytechnic in Winter 2025, Winter 2026 and Fall 2026
- **THEN** the profile holds three `course` records with the same title and organisation, dated 2025-01 to 2025-04, 2026-01 to 2026-04 and 2026-09 to 2026-12, listed Fall 2026 first

#### Scenario: Ongoing record
- **WHEN** a `project` record starts in 2025-03 and is ongoing
- **THEN** it is shown as running from March 2025 to the present, and listed before records that have ended

### Requirement: Record context
A record MAY name one other record it is part of. The guideline for when a record is part of another SHALL be the user's, shown wherever the user sets the link:

> a `part_of_id` reference is made by a Record entry when the existing entry is missing important context, may be misinterpreted, or may be difficult to understand without also considering its linked Record entry

The link SHALL point from the dependent record to the record that gives it context. A record SHALL NOT be part of itself, and a link that would make a record part of itself through other records SHALL be refused. A `part_of` link SHALL NOT count as a ground: a claim grounded by a record SHALL NOT thereby be grounded by the record it is part of, nor the reverse (see "Grounds"). When a record that others are part of is deleted, each of those records SHALL lose its link and SHALL be flagged as having lost its context, until the user sets a new link or dismisses the flag.

#### Scenario: Thesis part of the degree
- **WHEN** the user makes the record "PhD thesis" part of the record "PhD Computer Science"
- **THEN** the thesis is shown as part of the degree, and the degree lists the thesis among its dependent records

#### Scenario: Context does not ground
- **WHEN** "tidyplots" is part of the EXCONF 2024 paper, and `NumPy`'s claim is grounded by "tidyplots" only
- **THEN** `NumPy`'s claim is grounded by "tidyplots" and not by the paper

#### Scenario: Cycle refused
- **WHEN** "tidyplots" is part of the EXCONF 2024 paper and the user tries to make the paper part of "tidyplots"
- **THEN** the change is refused with a message, and the links are unchanged

#### Scenario: Deleting a context record
- **WHEN** the user deletes the record "city-parking" while the award record "Best Design" is part of it
- **THEN** "Best Design" is kept, is part of no record, and is flagged as having lost its context

### Requirement: Disclosure
Each record SHALL be `public` or `private`, `public` by default. A record's effective disclosure SHALL be `private` when the record or any record it is part of, directly or through other records, is `private`. A private record SHALL still ground claims and SHALL be shown on the profile page, marked as private. A record that is private only through its context SHALL be marked as such.

#### Scenario: Private project
- **WHEN** the user adds a private `project` record for a hobby web app and grounds `Django` with it
- **THEN** `Django`'s claim is grounded, and the profile page shows the record marked private

#### Scenario: Private through context
- **WHEN** a public `award` record is part of a private `project` record
- **THEN** the award's effective disclosure is private, and it is marked as private through its context

### Requirement: Claims and levels
A skill SHALL be part of the profile when it has a claim. A skill SHALL have at most one claim. Each claim SHALL have a level on one ordered scale: `missing`, `learning`, `familiar`, `proficient`, `expert`, and SHALL record whether the user set its level or it came from the model. The user SHALL be able to add a skill to the profile with a level, change its level, rename the skill, and remove it from the profile. Removing a skill SHALL delete its claim, with its grounds and the highlights' coverage of it, and SHALL leave the skill's marks on postings and the highlights themselves unchanged. A claim's level SHALL be the level used wherever the skill's level is shown or used.

#### Scenario: Adding a skill by hand
- **WHEN** the user adds `Docker` to the profile at `proficient`
- **THEN** `Docker` has a claim at `proficient`, shown as set by the user

#### Scenario: Removing a skill keeps posting marks and highlights
- **WHEN** the user removes `Python` from the profile while three postings mark `Python` and a highlight covers `Python` and `NumPy`
- **THEN** `Python` has no claim and no grounds, the three postings still mark it, and the highlight still exists, covering `NumPy` only

### Requirement: Grounds
A claim SHALL be grounded by zero or more records. Each ground SHALL name one record and SHALL have the quote that names the skill; a ground the user adds without a quote SHALL take the record's title and organisation as its quote. A claim SHALL have at most one ground per record. A claim with no grounds SHALL be shown as ungrounded, except a claim at `missing`. Being ungrounded SHALL NOT change a claim's level or how matching and recommendations use it. The user SHALL be able to add a ground by choosing a record, and to remove a ground. The profile SHALL show each claim's grounds with a link to the record each names.

#### Scenario: A claim grounded by two records
- **WHEN** `Flask`'s claim is grounded by "city-parking" with the quote "Flask" and by "price_tracker"
- **THEN** the profile shows `Flask` with both records, each linked

#### Scenario: Ungrounded claim
- **WHEN** `Leadership` has a claim at `proficient` and no grounds
- **THEN** the profile shows `Leadership` as ungrounded, and a posting asking for `Leadership` still gets credit for it

#### Scenario: Missing is never ungrounded
- **WHEN** `AWS` has a claim at `missing` and no grounds
- **THEN** `AWS` is not shown as ungrounded

### Requirement: Highlights
The profile SHALL hold highlights: lines of wording for a CV, each covering one or more claims. Each coverage MAY have a quote naming the skill in the highlight's text. The user SHALL be able to add, edit and delete highlights, and to add and remove the claims a highlight covers. A highlight whose covered claims have all been removed SHALL be kept and shown as covering no claims. Each claim SHALL show the highlights that cover it, and a claim no highlight covers SHALL be shown as having no highlight.

#### Scenario: A highlight covering three claims
- **WHEN** the highlight "8+ years experience with Python (incl. NumPy, matplotlib, scikit-learn)" covers `Python`, `NumPy` and `scikit-learn`
- **THEN** each of the three claims lists that highlight

#### Scenario: Claim without a highlight
- **WHEN** `Docker` has a claim and no highlight covers it
- **THEN** the profile shows `Docker` as having no highlight

### Requirement: Skill aliases
The user SHALL be able to merge one skill into another profile skill. The merged skill's identity SHALL become an alias of the kept skill:
- the merged skill's claim, if any, SHALL be removed after its grounds and coverage move to the kept skill's claim (a ground or coverage the kept claim already has is not duplicated); the kept claim's level SHALL stay as it was;
- link overrides naming the merged skill SHALL name the kept skill instead;
- the merged skill's marks on postings, rejected posting suggestions and the evaluation's matching SHALL be unchanged.

Afterwards, setting a level on the merged skill, or a document suggestion naming it, SHALL apply to the kept skill. An alias of a skill that is later merged into a third skill SHALL become an alias of the third. The user SHALL be able to see each skill's aliases and remove one; removing an alias SHALL NOT recreate the merged skill's claim. A skill SHALL NOT be merged into itself, and merging into a skill without a claim SHALL be refused.

#### Scenario: Merging a near-duplicate
- **WHEN** `Postgres` has a claim grounded by "price_tracker", and the user merges `Postgres` into `PostgreSQL`, whose claim is at `proficient` and grounded by "city-parking"
- **THEN** `PostgreSQL`'s claim is at `proficient`, grounded by both records, `Postgres` has no claim, and `Postgres` is listed as an alias of `PostgreSQL`

#### Scenario: Level set on an alias
- **WHEN** `Postgres` is an alias of `PostgreSQL` and the user sets `Postgres` to `expert` on a posting that marks it
- **THEN** `PostgreSQL`'s claim is at `expert`, and `Postgres` still has no claim

#### Scenario: Posting marks stay as they are
- **WHEN** two postings mark `Postgres` and the user merges `Postgres` into `PostgreSQL`
- **THEN** both postings still mark `Postgres`

### Requirement: Profile details
The profile SHALL hold details outside records, claims and highlights: the user's name, a headline, contact details, summaries and goal statements. Each detail SHALL have a kind (`name`, `headline`, `contact`, `summary` or `goal`), an optional label (such as "Email") and text. Details SHALL be shown in that order of kinds, then in the order added. Details SHALL be added, edited and deleted by the user only; document runs SHALL NOT suggest them.

#### Scenario: Headline and contact details
- **WHEN** the user adds the headline "PhD Computer Science" and the contact detail labelled "Email"
- **THEN** the profile page shows the headline after the name and the email among the contact details

### Requirement: Remembered rejections
When the user rejects a document suggestion, or deletes a record, description line, source, claim, ground, `part_of` link, highlight or coverage, the system SHALL remember it by its identity (see "Matching suggestions" in `profile-extraction`). An edit that changes a row's identity SHALL remember the old identity. Document suggestions with a remembered identity SHALL NOT be offered. The user SHALL be able to see remembered rejections and to forget one. Forgetting SHALL NOT recreate anything, but SHALL let a later suggestion with that identity be offered again. Adding something by hand SHALL forget a remembered rejection with the same identity.

#### Scenario: Deleted skill stays deleted
- **WHEN** the user removes `Chain` from the profile and a document run later suggests a claim for `Chain`
- **THEN** the suggestion is not offered

#### Scenario: Forgetting a rejection
- **WHEN** the user forgets the remembered rejection of `Chain`
- **THEN** a later or existing suggestion for `Chain` is offered again, and `Chain` has no claim until the user accepts it

#### Scenario: Adding by hand forgets
- **WHEN** `Jupyter` is remembered as rejected and the user adds `Jupyter` to the profile at `familiar`
- **THEN** `Jupyter` has a claim and is no longer listed among remembered rejections

### Requirement: Upgrading an existing profile
Upgrading a database whose profile has sections, entries, items and evidence SHALL rebuild it into the new structure without a model, keeping everything the user would lose otherwise:
- each entry SHALL become a record, its kind taken from its section (`experience` gives `role`, `education` gives `degree`, `publication` gives `publication`, `project` gives `project`, any other gives `other`), keeping its title, organisation, location, dates, ongoing flag and origin;
- an entry whose line reads "Taught" followed by terms and years (such as "Taught Fall 2026, Winter 2026") SHALL become one `course` record per term, with the entry's title and organisation, dated Winter as January to April, Summer as May to August and Fall as September to December of that year;
- items under an entry SHALL become its description lines, except items that are a single web address, which SHALL become sources; an entry without dates SHALL take its end date from its items' latest date, and its start date from their earliest date when they span more than one date;
- items in `contact` sections SHALL become contact details (the first line the name), and items in `summary` sections summaries (goal statements when the section's name says goals or objective);
- every other item not under an entry SHALL become a highlight;
- each skill with a level SHALL get a claim at that level, with the same level origin;
- evidence pointing at an entry, or at an item under an entry, SHALL become a ground on each record made from that entry, with its quote; evidence pointing at an item that became a highlight SHALL become that highlight's coverage of the claim, with its quote;
- each remembered deletion of a skill SHALL become a remembered rejection of its claim;
- link overrides SHALL keep naming the same skills.

The rebuild SHALL NOT merge duplicate records or set `part_of` links. Merge history and remembered deletions of anything other than skills SHALL NOT be kept.

#### Scenario: Course entry split into terms
- **WHEN** an `experience` entry "Sessional Instructor, COMP 1100 Programming II" at Example University has the item "Taught Summer 2017, Summer 2016", and `Teaching` has evidence pointing at that item
- **THEN** after upgrading there are two `course` records with that title and organisation, dated 2016-05 to 2016-08 and 2017-05 to 2017-08, and `Teaching`'s claim is grounded by both

#### Scenario: Claims lines become highlights
- **WHEN** a `claims` section item "8+ years experience with Python (incl. NumPy …)" is the evidence for `Python` and `NumPy`
- **THEN** after upgrading the item is a highlight covering both claims, and neither claim is grounded by it

#### Scenario: Deleted skills stay deleted
- **WHEN** the database remembers the deletion of the skills `Postgres` and `Chain`
- **THEN** after upgrading, suggestions for claims on `Postgres` or `Chain` are not offered

#### Scenario: Project lines and address
- **WHEN** a `project` entry has a tagline item, a "Technologies: Python, Flask" item and the item "https://github.com/janedoe-example/city-parking"
- **THEN** after upgrading its record has two description lines and one repository source

### Requirement: Resetting the knowledge base
A command SHALL delete every record, claim and highlight (with their lines, sources, grounds, coverage and links) from a chosen database, keeping profile details, aliases, remembered rejections, link overrides, posting data and documents. It SHALL refuse to run without an explicit confirmation flag, and SHALL report how many of each it deleted. It SHALL NOT remember the deleted rows as rejections.

#### Scenario: Resetting a copy
- **WHEN** the user runs the reset with confirmation on a copy of the database holding 30 records, 82 claims and 16 highlights
- **THEN** the copy has no records, claims or highlights, still has its details, aliases, rejections and overrides, and the command reports 30, 82 and 16

#### Scenario: No confirmation
- **WHEN** the user runs the reset without the confirmation flag
- **THEN** nothing is deleted and the command says how to confirm

### Requirement: Editing the knowledge base
The user SHALL be able to add, edit and delete records, description lines, sources, claims, grounds, highlights, coverage and profile details; set and clear a record's `part_of` link and disclosure; move a record's description lines up and down; and merge skills and remove aliases. Deleting a record SHALL also delete its lines, sources and grounds, and SHALL apply "Record context" to the records that are part of it. Changes SHALL be saved when made, without a separate save step.

#### Scenario: Deleting a record
- **WHEN** the user deletes a record that has two lines and grounds `Linux`'s claim, which another record also grounds
- **THEN** the record, its lines and that ground are gone, and `Linux` stays in the profile grounded by the other record

#### Scenario: Changing a record's kind
- **WHEN** the user changes a record from `other` to `award`
- **THEN** the record is listed among awards

### Requirement: Origin of profile data
Every record, description line, source, claim level, ground, highlight and coverage SHALL record its origin: `user` when the user made or last changed it, `suggestion` when it was copied from an accepted document suggestion, or `model` when it came from an automatic document merge before this structure existed. A user change to a row's content SHALL make the row the user's. Moving a row up or down SHALL NOT change its origin. Rows whose origin is `suggestion` or `model` SHALL be shown as model-derived until the user changes them.

#### Scenario: Editing a model-made bullet
- **WHEN** the user edits the text of a description line that came from an accepted suggestion
- **THEN** the line is shown as the user's and no longer as model-derived

#### Scenario: Reordering keeps origin
- **WHEN** the user moves a model-made description line up
- **THEN** the line is still shown as model-derived

#### Scenario: Accepted rows stay model-derived
- **WHEN** the user accepts every record suggestion of a document with "Accept all"
- **THEN** each accepted record is shown as model-derived until the user edits it

### Requirement: Profile page
The interface SHALL provide a profile page, reachable from the navigation. It SHALL show:
- the profile details;
- the records grouped by kind, in the order of "Records", each with its lines, sources, disclosure, the record it is part of and the records that are part of it, and any lost-context flag;
- a skills panel grouping claims by level, each with its grounds, the highlights covering it, its aliases, and whether it is ungrounded or has no highlight;
- the highlights, each with the claims it covers;
- counts of records by kind, claims, ungrounded claims and highlights;
- links to the suggestions page (with the number of pending suggestions) and to the remembered rejections.

Every editing action in "Editing the knowledge base" SHALL be available from this page.

#### Scenario: Viewing the profile
- **WHEN** the profile has 7 projects, 10 courses and 12 claims, 3 of them ungrounded
- **THEN** the profile page shows projects and courses as separate groups, the 12 claims grouped by level with the 3 marked ungrounded, and the counts

### Requirement: Profile data is user-authored
The profile (records, description lines, sources, claims, grounds, highlights, coverage, `part_of` links, aliases, profile details and remembered rejections) SHALL be stored as user-authored data. Importing or re-capturing postings, extracting postings and extracting documents SHALL leave it unchanged. Only the user's edits and the user's acceptance of document suggestions SHALL change it, and accepting a suggestion SHALL never change a row or a level the user has changed.

#### Scenario: Posting extraction leaves the profile alone
- **WHEN** a posting is extracted and its suggestions name `Kubernetes`, which is not in the profile
- **THEN** the profile is unchanged

#### Scenario: Document extraction leaves the profile alone
- **WHEN** a document run succeeds and suggests twelve records and forty claims
- **THEN** the profile is unchanged until the user accepts some of them
