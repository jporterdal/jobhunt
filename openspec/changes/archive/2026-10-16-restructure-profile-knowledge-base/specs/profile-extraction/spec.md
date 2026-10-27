## ADDED Requirements

### Requirement: Records, lines and dates from documents
Within each section other than `contact` and `summary`, the model SHALL label each line as the start of an entry, an item, a line continuing the previous entry, or prose. Each entry SHALL be suggested as a record:
- its kind SHALL come from its section's kind: `experience` gives `role`, `education` gives `degree`, `publication` gives `publication`, `project` gives `project`, and any other gives `other`;
- its title, organisation, location and dates SHALL be given by the model as quotes from the line;
- text on the entry's line beyond those fields SHALL become its first description line;
- the items that follow it SHALL become its description lines, except an item that is a single web address, which SHALL become a source;
- a record without dates of its own SHALL take its end date from its lines' latest date, and its start date from their earliest date when they span more than one date.

A line reading "Taught" followed by terms and years (such as "Taught Fall 2026, Winter 2026") SHALL replace its entry's record with one `course` record per term, with the entry's title and organisation, dated Winter as January to April, Summer as May to August and Fall as September to December of that year. This SHALL be done by rule, without a model. Items in `claims` sections, and prose and items not under an entry in any other section, SHALL be suggested as highlights.

A date SHALL be kept only when its quote is in the line and it reads as a year, a year and month, or "present". A date after a tab at the end of a line SHALL be treated as that line's date.

#### Scenario: Degree with a tab-aligned year
- **WHEN** a line in an `education` section reads "PhD Computer Science, Example University", then a tab, then "2022"
- **THEN** a `degree` record is suggested with the title "PhD Computer Science", the organisation "Example University" and the end date 2022

#### Scenario: Terms split by rule
- **WHEN** an `experience` entry "Sessional Instructor, COMP 1000 Introduction to Programming" at Example Polytechnic is followed by the line "Taught Fall 2026, Winter 2026, Winter 2025, Winter 2024"
- **THEN** four `course` records with that title and organisation are suggested, dated by term, and no `role` record is suggested for the entry

#### Scenario: Project address becomes a source
- **WHEN** a `project` entry is followed by the items "Technologies: Python, Flask" and "https://github.com/janedoe-example/city-parking"
- **THEN** its suggested record has the description line "Technologies: Python, Flask" and the source "https://github.com/janedoe-example/city-parking"

#### Scenario: Claims lines become highlights
- **WHEN** a `claims` section has the line "Familiar with serverless CI/CD"
- **THEN** a highlight with that text is suggested, and no record is

#### Scenario: Unverified date
- **WHEN** the model gives a date quote "2019" for a line that does not contain "2019"
- **THEN** the record gets no date from it

### Requirement: Claims from documents
For each `claims`, `experience`, `education`, `publication` and `project` section, the model SHALL list the skills each line shows the person has, one per entry, each with a name, a quote and a suggested level of `familiar`, `proficient` or `expert`. Degrees and certifications, and research methods and areas of expertise named in the document, SHALL count as skills. The suggested level SHALL follow the line's wording and stated years. Each skill SHALL be suggested as a claim:
- a skill found on a record's line, or on a line that became one of its description lines, SHALL be suggested with a ground on that record, with its quote (on each term's record, for a line split into terms);
- a skill found on a line that became a highlight SHALL be suggested with that highlight's coverage, with its quote.

When one run finds the same skill more than once, its suggestion SHALL carry every ground and coverage found, and the highest level found.

#### Scenario: Claim with libraries
- **WHEN** a claims line reads "8+ years experience with Python (incl. NumPy, matplotlib, scikit-learn)"
- **THEN** claims for `Python`, `NumPy`, `matplotlib` and `scikit-learn` are suggested, each covered by that line's highlight and none grounded by it

#### Scenario: Skill on a project line
- **WHEN** the project "city-parking" has the line "Technologies: Python, Flask, PostgreSQL, Leaflet"
- **THEN** the claim suggested for `Flask` has a ground on "city-parking" with the quote "Flask"

#### Scenario: Wording sets the level
- **WHEN** a line reads "Familiar with serverless CI/CD"
- **THEN** `CI/CD` is suggested at `familiar`

### Requirement: Context links from documents
After a run's records are found, the model SHALL be asked, for each record, whether it is part of another record of the same run. The request SHALL include the user's guideline from "Record context" in `skill-profile`, word for word. A suggested link SHALL be kept only when both records are among the run's records, the record isn't linked to itself, and the run's links form no cycle. A record SHALL get at most one suggested link.

#### Scenario: Thesis and degree
- **WHEN** a run has the records "PhD thesis: Adaptive penalty methods for constrained search …" and "PhD Computer Science", and the model says the thesis is part of the degree
- **THEN** a `part_of` link from the thesis to the degree is suggested

#### Scenario: Cycle dropped
- **WHEN** the model says record A is part of record B and record B is part of record A
- **THEN** at most one of the two links is suggested

### Requirement: Matching suggestions
Suggestions SHALL be matched with the profile, with each other and with remembered rejections by identity:
- a record by its kind, title, organisation, start date and end date;
- a description line by its record and its text; a source by its record and its address or document;
- a claim by its skill's identity, where a skill that is an alias counts as the skill it is an alias of;
- a ground by its claim and its record; a `part_of` link by its two records;
- a highlight by its text; a coverage by its highlight and its claim;
- a level by its claim and the level.

Names and text SHALL be compared trimmed, case-insensitively, with whitespace collapsed. A suggestion with the same identity in runs of two documents SHALL be offered once.

#### Scenario: Same record in two documents
- **WHEN** the CV and the portfolio both describe the `degree` "PhD Computer Science" at Example University ending 2022
- **THEN** one record suggestion is offered for it

#### Scenario: Suggestion naming an alias
- **WHEN** `Postgres` is an alias of `PostgreSQL`, which has a claim, and a run suggests `Postgres` with a ground on a record `PostgreSQL`'s claim lacks
- **THEN** the suggestion is offered as adding that ground to `PostgreSQL`'s claim

### Requirement: Offered suggestions
The suggestions offered SHALL be those of each document's latest successful run, matched against the current profile:
- **Records.** A record suggestion SHALL be offered as new when no record has its identity. When one does, it SHALL be offered as additions to that record when it has lines or sources the record lacks, and not offered otherwise.
- **Claims.** A claim suggestion SHALL be offered as new when its skill has no claim, and otherwise as additions: grounds the claim lacks, and its level when the claim's level came from the model and the suggested level is higher. A ground on a record that doesn't exist yet SHALL wait until the record exists; a ground on a record whose suggestion was rejected SHALL NOT be offered. A claim with no ground available yet SHALL still be offered.
- **Context links.** A `part_of` link SHALL be offered once both records exist and the dependent record has no link.
- **Highlights.** A highlight suggestion SHALL be offered as new when no highlight has its text, and otherwise as additions: coverage the highlight lacks. Coverage of a claim that doesn't exist yet SHALL wait until it exists.

A suggestion, or an addition, whose identity is remembered as rejected SHALL NOT be offered. A suggestion with nothing left to offer SHALL NOT be shown.

#### Scenario: Ground waits for its record
- **WHEN** a run suggests the record "city-parking" and a claim for `Flask` grounded by it, and the user accepts the claim before the record
- **THEN** `Flask`'s claim exists without grounds, and once the user accepts "city-parking", `Flask` is offered again with the ground on it

#### Scenario: Ground on a rejected record
- **WHEN** the user rejects the record "ml_basics"
- **THEN** grounds on "ml_basics" are not offered with any claim suggestion

#### Scenario: User level kept
- **WHEN** the user set `Python` to `proficient` and a run suggests `Python` at `expert` with no new grounds
- **THEN** no suggestion for `Python` is offered

#### Scenario: Model level raised
- **WHEN** `SQL`'s claim is at `familiar` from an earlier suggestion and a run suggests `SQL` at `proficient`
- **THEN** `SQL` is offered as raising its level to `proficient`

#### Scenario: Re-running a document
- **WHEN** the user accepted every suggestion of a document and the document is extracted again with the same result
- **THEN** no suggestion is offered for it

### Requirement: Accepting and rejecting suggestions
The user SHALL be able to accept or reject each offered suggestion. Accepting SHALL copy it into the profile with origin `suggestion`:
- a record with its lines and sources, or the additions offered for an existing record;
- a claim with its level (as set by the model) and the grounds offered, or the additions offered for an existing claim; a skill that doesn't exist yet SHALL be created;
- a `part_of` link, refused as in "Record context" in `skill-profile` if it would make a cycle;
- a highlight with the coverage offered, or the additions offered for an existing highlight.

Rejecting SHALL remember the identity of the suggestion, or of each addition offered, as in "Remembered rejections" in `skill-profile`. Accepting or rejecting SHALL change nothing else: no row or level the user has changed.

#### Scenario: Accepting a claim
- **WHEN** the user accepts the claim suggestion `Flask` at `proficient` with a ground on the existing record "city-parking"
- **THEN** `Flask` has a claim at `proficient` set by the model, grounded by "city-parking", both shown as model-derived

#### Scenario: Rejecting a non-skill
- **WHEN** the user rejects the claim suggestion `(1+1)-ES`
- **THEN** `(1+1)-ES` has no claim, and no run's suggestion of it is offered again

### Requirement: Accept all
For each of the four kinds of suggestion (records, claims, context links, highlights), the interface SHALL offer an action that accepts every offered suggestion of that kind, from every document, as "Accepting and rejecting suggestions" accepts each one. It SHALL report how many it accepted. Suggestions that become available as a result (such as grounds waiting for an accepted record) SHALL be offered afterwards, not accepted by the same action.

#### Scenario: Accepting all records
- **WHEN** 30 record suggestions are offered from two documents and the user uses "Accept all" for records
- **THEN** 30 records are added, the action reports 30, and claim suggestions offered afterwards include the grounds on those records

### Requirement: Suggestions page
The interface SHALL provide a suggestions page, reachable from the profile page. It SHALL list the offered suggestions grouped by kind, in the order records, claims, context links, highlights, each group with its "Accept all" action and its count. Each suggestion SHALL show its document and whether it is new or adds to something existing, with:
- for a record: its kind, title, organisation, dates, lines and sources;
- for a claim: the skill, the level, and each ground with its record and quote, plus the number of grounds waiting for records;
- for a context link: both records, with the guideline from "Record context";
- for a highlight: its text and the claims it covers, plus the number of coverages waiting for claims.

Each suggestion SHALL offer accept and reject. When nothing is offered, the page SHALL say so.

#### Scenario: Nothing to review
- **WHEN** every suggestion has been accepted or rejected
- **THEN** the suggestions page says there is nothing to review

## MODIFIED Requirements

### Requirement: Adding a document to the profile
Uploading a document of kind `cv` whose text was extracted SHALL queue its extraction without a further request. Every other document with extracted text SHALL offer an action to add it to the profile, which queues its extraction. A document without extracted text SHALL NOT offer the action. The action SHALL be disabled while the model server is unreachable. Extraction SHALL use the selected model and context size. Its results SHALL be offered as suggestions (see "Offered suggestions"); extraction SHALL NOT change the profile.

#### Scenario: Uploading a CV
- **WHEN** the user uploads `cv.odt` as kind `cv` and its text is extracted
- **THEN** an extraction job for that document is queued

#### Scenario: Adding another document
- **WHEN** the user uses "Add to profile" on a document of kind `other` that has text
- **THEN** an extraction job for that document is queued

#### Scenario: Document without text
- **WHEN** a document's text could not be extracted
- **THEN** it offers no "Add to profile" action and uploading it queues nothing

### Requirement: Sections from headings
Extraction SHALL split the document into sections at heading lines: short lines whose letters before any tab are all capitals. Lines before the first heading SHALL form a `contact` section. A section's kind SHALL come from words in its heading: summary, goals, objective or profile give `summary`; skills gives `claims`; experience, employment, work or teaching give `experience`; education gives `education`; publication gives `publication`; project gives `project`. The words SHALL be checked in that order, and any other heading SHALL give `other`. Contact details SHALL be recognised without a model and SHALL NOT be sent to the model. `contact` and `summary` sections SHALL produce no suggestions; profile details are entered by the user.

#### Scenario: Heading with a tabbed note
- **WHEN** a line reads "SELECTED PUBLICATIONS", then tabs, then "*(full citations available on my website)"
- **THEN** it starts a `publication` section

#### Scenario: Combined heading
- **WHEN** a heading reads "SKILLS & EXPERIENCE"
- **THEN** its section's kind is `claims`

#### Scenario: Contact block
- **WHEN** the lines before the first heading contain a name, an email address, a phone number and two web addresses
- **THEN** they form a `contact` section, no model request includes them, and no suggestion is made from them

### Requirement: Checks against the document text
Every quote extraction returns (record fields, dates, skills and context links' records) SHALL be checked against the document's text, comparing case-insensitively with whitespace collapsed, in the line the model cited first and then anywhere in the text. Items whose quotes are not found SHALL be kept in the run's record but SHALL NOT be suggested. Each ground and coverage suggested SHALL point at the record or highlight holding its line.

#### Scenario: Invented skill quote
- **WHEN** the model returns `Kubernetes` with a quote that does not occur in the document
- **THEN** `Kubernetes` is recorded in the run as unverified and is not suggested

### Requirement: Document runs are stored
Each extraction of a document SHALL be stored as derived data, with the document, a fingerprint of its text, the model, the pipeline version, its status, any error, its times, each step's output, and its verified suggestions. Runs and their suggestions SHALL NOT be edited or overwritten. Extracting a document again SHALL add a new run, whose suggestions replace the earlier run's on the suggestions page. A failed run SHALL store no suggestions and change nothing that is offered. Runs from before suggestions existed SHALL offer nothing.

#### Scenario: Extracting twice
- **WHEN** the same document is extracted twice
- **THEN** two runs exist for it, the first is unchanged, and only the second's suggestions are offered

#### Scenario: Failed run
- **WHEN** a document's extraction fails at the skills step
- **THEN** the run is stored as failed with its error, the earlier run's suggestions are still the ones offered, and the profile is unchanged

## REMOVED Requirements

### Requirement: Entries, items and dates
**Reason**: Entries and items are replaced by records, description lines and sources.
**Migration**: See "Records, lines and dates from documents".

### Requirement: Skills from documents
**Reason**: Skills from documents are now suggested as claims with grounds and highlight coverage; claimed years and skill kinds are no longer stored.
**Migration**: See "Claims from documents".

### Requirement: Automatic merge into the profile
**Reason**: The user wants the final say over the knowledge base that CVs are generated from; every automatically merged row had to be checked by hand.
**Migration**: Document runs store suggestions that the user accepts or rejects (see "Offered suggestions", "Accepting and rejecting suggestions", "Accept all"). Existing merged content is rebuilt by the upgrade (see "Upgrading an existing profile" in `skill-profile`).

### Requirement: Merge history and rollback
**Reason**: With nothing merged automatically there is nothing to roll back; the history only described the old tables.
**Migration**: Accepted rows record their origin; the user deletes or edits them one by one. Merge history is dropped by the upgrade.
