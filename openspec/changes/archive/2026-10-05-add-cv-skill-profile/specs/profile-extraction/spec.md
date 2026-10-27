## Purpose

Reading the user's documents into their main profile with a local model: finding sections, entries, dates and skills, checking them against the document text, merging them automatically, and keeping every merge undoable.

## ADDED Requirements

### Requirement: Adding a document to the profile
Uploading a document of kind `cv` whose text was extracted SHALL queue its extraction into the profile without a further request. Every other document with extracted text SHALL offer an action to add it to the profile. A document without extracted text SHALL NOT offer the action. The action SHALL be disabled while the model server is unreachable. Extraction SHALL use the selected model and context size.

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
Extraction SHALL split the document into sections at heading lines: short lines whose letters before any tab are all capitals. Lines before the first heading SHALL form a `contact` section. A section's kind SHALL come from words in its heading: summary, goals, objective or profile give `summary`; skills gives `claims`; experience, employment, work or teaching give `experience`; education gives `education`; publication gives `publication`; project gives `project`. The words SHALL be checked in that order, and any other heading SHALL give `other`. Contact details SHALL be recognised without a model and SHALL NOT be sent to the model. A `summary` section SHALL be kept as prose and SHALL NOT produce skills.

#### Scenario: Heading with a tabbed note
- **WHEN** a line reads "SELECTED PUBLICATIONS", then tabs, then "*(full citations available on my website)"
- **THEN** it starts a `publication` section

#### Scenario: Combined heading
- **WHEN** a heading reads "SKILLS & EXPERIENCE"
- **THEN** its section's kind is `claims`

#### Scenario: Contact block
- **WHEN** the lines before the first heading contain a name, an email address, a phone number and two web addresses
- **THEN** the `contact` section holds them as labelled items, and no model request includes them

### Requirement: Entries, items and dates
Within each section other than `contact` and `summary`, the model SHALL label each line as the start of an entry, an item, a line continuing the previous entry, or prose. For an entry it SHALL give the title, organisation, location and dates as quotes from the line. Text on an entry's line beyond those fields SHALL become the entry's first item. A date SHALL be kept only when its quote is in the line and it reads as a year, a year and month, or "present". A date after a tab at the end of a line SHALL be treated as that line's date.

#### Scenario: Degree with a tab-aligned year
- **WHEN** a line in an `education` section reads "PhD Computer Science, Example University", then a tab, then "2022"
- **THEN** an entry is created with the title "PhD Computer Science", the organisation "Example University" and the end date 2022

#### Scenario: Continuation lines
- **WHEN** an `experience` entry's line is followed by plain lines listing courses, each line ending in a tab and a year
- **THEN** each course line becomes an item of that entry, dated with its year

#### Scenario: Unverified date
- **WHEN** the model gives a date quote "2019" for a line that does not contain "2019"
- **THEN** the entry or item gets no date from it

### Requirement: Skills from documents
For each `claims`, `experience`, `education`, `publication` and `project` section, the model SHALL list the skills each line shows the person has, one per entry, each with a name, a kind (`technical`, `soft` or `qualification`), a quote, the years claimed if the line states them, and a suggested level of `familiar`, `proficient` or `expert`. Degrees and certifications SHALL be `qualification`. Research methods and areas of expertise named in the document SHALL count as skills. The suggested level SHALL follow the line's wording and stated years. Claimed years SHALL be kept only when that number appears in the line.

#### Scenario: Claim with libraries and years
- **WHEN** a claims line reads "8+ years experience with Python (incl. NumPy, matplotlib, scikit-learn)"
- **THEN** the skills include `Python` with claimed years 8, and `NumPy`, `matplotlib` and `scikit-learn`, each pointing at that line

#### Scenario: Wording sets the level
- **WHEN** a line reads "Familiar with serverless CI/CD"
- **THEN** `CI/CD` is suggested at `familiar`

#### Scenario: Unverified years
- **WHEN** the model gives 10 claimed years for a line that states "5+ years"
- **THEN** the skill is kept without claimed years

### Requirement: Checks against the document text
Every quote extraction returns (entry fields, dates and skills) SHALL be checked against the document's text, comparing case-insensitively with whitespace collapsed, in the line the model cited first and then anywhere in the text. Items whose quotes are not found SHALL be kept in the run's record but SHALL NOT reach the profile. Each piece of evidence that reaches the profile SHALL point at the entry or item holding its line.

#### Scenario: Invented skill quote
- **WHEN** the model returns `Kubernetes` with a quote that does not occur in the document
- **THEN** `Kubernetes` is recorded in the run as unverified and is not added to the profile

### Requirement: Document runs are stored
Each extraction of a document SHALL be stored as derived data, with the document, a fingerprint of its text, the model, the pipeline version, its status, any error, its times, and each step's output. Runs SHALL NOT be edited or overwritten. Extracting a document again SHALL add a new run. A failed run SHALL change nothing in the profile.

#### Scenario: Extracting twice
- **WHEN** the same document is extracted twice
- **THEN** two runs exist for it, and the first is unchanged

#### Scenario: Failed run
- **WHEN** a document's extraction fails at the skills step
- **THEN** the run is stored as failed with its error, and the profile is unchanged

### Requirement: Automatic merge into the profile
When a document run succeeds, its verified results SHALL be merged into the profile without a further request, marked as model-derived.
- **Matching.**
  - A section SHALL match an existing section with the same kind and name.
  - An entry SHALL match an entry in the same section with the same title and organisation.
  - An item SHALL match an item with the same parent and the same text.
  - A skill SHALL match by its identity.
  - Names and text SHALL be compared trimmed, case-insensitively, with whitespace collapsed.
- **Matched content.** It SHALL NOT be added twice. Empty fields of a matched model-made entry SHALL be filled in. Unmatched content SHALL be added after the existing content of its parent.
- **Skills.** A matched skill SHALL gain the new evidence. Its level SHALL be raised to the suggested level when the model set its current level and the suggestion is higher. A new skill SHALL get the suggested level, marked as set by the model.
- **The user's content.** A merge SHALL NOT change, move or remove any row the user has changed, SHALL NOT change a level the user set, and SHALL NOT add content the user deleted (see "Remembered deletions").

#### Scenario: First CV
- **WHEN** a CV run succeeds on an empty profile
- **THEN** the profile has the run's sections, entries, items and skills, all shown as model-derived

#### Scenario: Second document overlaps the first
- **WHEN** a second document repeats an education entry already in the profile and adds a new skill `Rust`
- **THEN** the education entry is not duplicated, and `Rust` is added with its evidence

#### Scenario: User level kept
- **WHEN** the user set `Python` to `proficient` and a merge suggests `expert`
- **THEN** `Python` stays at `proficient` and gains the new evidence

#### Scenario: Model level raised
- **WHEN** the model set `SQL` to `familiar` and a later merge suggests `proficient`
- **THEN** `SQL` is at `proficient`, still marked as set by the model

#### Scenario: User edit survives a merge
- **WHEN** the user edited a model-made entry's title and the same document is merged again
- **THEN** the edited title is unchanged and no duplicate entry is added under the old title

### Requirement: Merge history and rollback
Every merge SHALL be recorded with its document, run, time and what it added or filled in. A history page SHALL list merges and remembered deletions. The user SHALL be able to roll back a merge: content it added SHALL be removed, and fields it filled in SHALL be emptied again. Rollback SHALL NOT affect rows the user has changed since the merge, and SHALL list them. A rolled-back merge SHALL stay in the history, marked as rolled back, with an action to merge its run again.

#### Scenario: Rolling back a merge
- **WHEN** the user rolls back a merge that added two entries and the skill `Rust`, and has since edited one of the two entries
- **THEN** the unedited entry and `Rust` are removed, the edited entry stays, and the result lists the edited entry as kept

#### Scenario: Merging again
- **WHEN** the user merges a rolled-back run again
- **THEN** its content is added back, except content the user has since deleted
