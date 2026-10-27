# tailored-cv Specification

## Purpose

Puts together a CV for a target posting from the profile's knowledge base. It chooses the highlights, records and details most relevant to the posting's skills, never prints private records, keeps each saved CV as a frozen copy of what was produced, and exports it as an editable OpenDocument Text file.

## Requirements

### Requirement: Tailoring a CV for a posting
A posting's detail page SHALL offer "Tailor a CV", which opens a proposed CV for that posting. The proposal SHALL be computed from stored data each time it is shown. Showing it SHALL make no model requests and SHALL write nothing. The proposal SHALL show the posting's match score (see "Posting match score" in `recommendations`), the choices described in this capability, a list of gaps and a preview of the CV.

#### Scenario: Opening a proposal
- **WHEN** the user follows "Tailor a CV" on a posting's page
- **THEN** a proposal for that posting is shown, and no row in any table is added or changed

#### Scenario: Posting without skills
- **WHEN** the posting has no marks and no app run with suggestions
- **THEN** the proposal says the posting has no skills to tailor to, ticks no highlight, and still proposes details and records by their kinds' rules

### Requirement: Choosing highlights
The proposal SHALL choose highlights from the profile's highlights, up to a budget (default 9), as follows:
- Each posting skill SHALL have a weight: 2 when required, 1 otherwise. Each of its link options (as in "Skill credit" in `recommendations`) to a profile skill with a claim SHALL have a value: the posting skill's weight × the relation's weight × the claim's level weight.
- A highlight SHALL show a posting skill at the best value among the link options to the claims it covers.
- A highlight's gain SHALL be the sum, over posting skills, of how much it raises the best value already shown by the highlights chosen so far, minus 0.1 for each claim it covers that no posting skill has a link option to.
- Highlights SHALL be chosen one at a time, the highest gain first, until the budget is reached or no highlight has a gain above 0. Ties SHALL go to the highlight covering fewer claims, then to the older highlight.
- Chosen highlights SHALL be printed in the order they were chosen.

#### Scenario: A posting skill counts once
- **WHEN** a posting requires `Python` and prefers `Flask`, both linked `same` to claims at `proficient`, highlight A covers Python, and highlight B covers Python and Flask
- **THEN** B is chosen first (gain 2.55), and A is then not chosen, since it adds nothing (gain 0)

#### Scenario: Covering what the posting doesn't ask for
- **WHEN** a posting requires only `Python` (linked `same` at `proficient`), highlight A covers Python, and highlight C covers Python, Java and C++
- **THEN** A's gain is 1.7, C's is 1.5, and A is chosen first

#### Scenario: Budget
- **WHEN** twelve highlights have a gain above 0 and the budget is 9
- **THEN** nine are chosen

#### Scenario: Missing skills show nothing
- **WHEN** a highlight covers only claims at `missing`
- **THEN** its gain is not above 0, and it is not chosen

### Requirement: Choosing records
The proposal SHALL choose records by their kind:
- **Always printed:** `role`, `course`, `degree` and `award` records.
- **Ranked:** `publication` and `project` records, up to a count (default 3 publications and 0 projects), and `event`, `task` and `other` records (default count 0). A record's relevance SHALL be the sum, over posting skills, of the best value among the link options to the claims the record grounds. Records SHALL be taken by relevance, highest first, with ties going to the kind's usual order (ongoing first, then newest first), so a count larger than the number of relevant records is filled with the newest.
- Chosen records SHALL be printed in their kind's usual order, not by relevance.

#### Scenario: A relevant publication comes first
- **WHEN** the count for publications is 1, the newest publication grounds no claim the posting links to, and an older publication grounds `Evolution strategies`, which the posting requires
- **THEN** the older publication is chosen

#### Scenario: Filling with the newest
- **WHEN** the count for publications is 3 and only one publication is relevant
- **THEN** that publication and the two newest of the others are chosen, and all three print newest first

#### Scenario: Projects by default
- **WHEN** a proposal is opened without changing the counts
- **THEN** no project is chosen, and every public role, course, degree and award record is

### Requirement: Profile details on a CV
The proposal SHALL include the profile's `name`, `headline`, `contact` and `goal` details, and SHALL leave out its `summary` details unless the user ticks them.

#### Scenario: Default details
- **WHEN** the profile has a name, two contact details, a goal and two summaries
- **THEN** the proposal ticks the name, both contact details and the goal, and leaves both summaries unticked

### Requirement: Never printing private records
A record whose effective disclosure is private (see "Disclosure" in `skill-profile`) SHALL NOT be offered, chosen, printed or saved. Nothing of it SHALL appear on a CV: not its title, organisation, location, dates, lines or sources. A highlight whose text contains, ignoring case, the title, the organisation or a source address of a private record SHALL be flagged on the proposal with that record named, and SHALL NOT be ticked unless the user ticks it.

#### Scenario: Private record left out
- **WHEN** a private project grounds `Django`, which the posting requires, and the count for projects is 3
- **THEN** the project is neither listed nor chosen, and no part of it appears in the preview

#### Scenario: Private through its context
- **WHEN** a public record is part of a private record
- **THEN** it is neither listed nor chosen

#### Scenario: Highlight naming a private record
- **WHEN** a highlight with the highest gain mentions the organisation of a private record
- **THEN** it is flagged, naming that record, and is not ticked

### Requirement: Records with their context
When a chosen record is part of another record (`part_of`) that is also chosen, the CV SHALL print it under that record, once, and not in its own kind's section. When its context record is not chosen, the CV SHALL print it in its own kind's section with a line saying what it is part of.

#### Scenario: Thesis under its degree
- **WHEN** a thesis publication is part of the PhD degree and both are chosen
- **THEN** the thesis is printed under the PhD in the degrees section, and not among publications

#### Scenario: Context not chosen
- **WHEN** the project tidyplots is part of the EXCONF 2024 paper, tidyplots is chosen and the paper is not
- **THEN** tidyplots is printed among projects with a line naming the EXCONF 2024 paper as its context

### Requirement: Gaps
The proposal SHALL list as gaps the posting skills that have a credit above 0 (see "Skill credit" in `recommendations`) but that no chosen highlight shows and no chosen record grounds a claim for, through any of their link options. Each gap SHALL show the posting skill's name and importance, the profile skill it links to, and whether some highlight in the profile covers that skill without being chosen. Gaps SHALL be ordered required first, then by name. Posting skills with no credit SHALL NOT be listed as gaps.

#### Scenario: A skill no highlight shows
- **WHEN** the posting requires `PostgreSQL`, the profile has it at `familiar`, no highlight covers it and no chosen record grounds it
- **THEN** `PostgreSQL` is listed as a required gap, with "no highlight covers it"

#### Scenario: Shown by a record
- **WHEN** no chosen highlight covers `Django`, but a chosen project grounds its claim
- **THEN** `Django` is not a gap

#### Scenario: Skill the user lacks
- **WHEN** a posting skill has no link, or links only to a claim at `missing`
- **THEN** it is not listed as a gap

### Requirement: Adjusting a proposal
On the proposal, the user SHALL be able to change the highlight budget and the count for each ranked kind, and to tick or untick any non-private highlight, record or detail. Changing a budget or count SHALL choose again. Ticks and unticks the user sets SHALL be kept when the proposal is shown again with them. An unticked highlight or record SHALL NOT be chosen, and the budget or count SHALL go to the next best. A ticked highlight SHALL be printed after the chosen ones, and a ticked record in its kind's usual order, even beyond the budget or count. The preview and the gaps SHALL follow the current choice. Adjusting SHALL write nothing.

#### Scenario: Ticking a project
- **WHEN** the user ticks a project that was not chosen
- **THEN** the preview shows it among projects, and gaps that its grounds cover disappear

#### Scenario: Raising a count
- **WHEN** the user changes the count for projects from 0 to 2
- **THEN** the two most relevant projects are chosen

#### Scenario: Unticking the top highlight
- **WHEN** the user unticks the highlight with the highest gain and the budget is 9
- **THEN** it is not chosen, and nine others with a gain above 0 are, if there are that many

### Requirement: Saving a CV
Saving a proposal SHALL store a CV for the posting: the chosen details, highlights and records, by section and in print order, each with its content copied at that moment (texts, titles, organisations, locations, dates, lines and public source addresses, and for a record printed under another, under it). It SHALL also store the posting's match score at that moment, the ranking method's name and version (`cv-rank@1`), and when it was produced. A saved CV SHALL NOT change when the profile changes afterwards. A posting MAY have any number of saved CVs.

#### Scenario: Profile edited after saving
- **WHEN** the user saves a CV, then edits a chosen highlight's text and deletes a chosen record
- **THEN** the saved CV still shows the old text and the deleted record

#### Scenario: Two CVs for one posting
- **WHEN** the user saves two proposals for the same posting
- **THEN** both are kept, each with its own items

### Requirement: Editing and deleting a saved CV
On a saved CV's page, the user SHALL be able to move an item up or down within its section, remove an item (a record printed under another moves and is removed with it) and delete the whole CV. These changes SHALL affect only that CV. The page SHALL mark an item whose highlight or record has since been deleted from the profile, and an item whose record has since become private, without changing the item.

#### Scenario: Moving a highlight
- **WHEN** the user moves the third highlight of a saved CV up
- **THEN** it prints second, and the profile's highlights are unchanged

#### Scenario: Deleting a CV
- **WHEN** the user deletes a saved CV
- **THEN** it and its items are gone, and other CVs and the profile are unchanged

#### Scenario: Record made private after saving
- **WHEN** a record printed on a saved CV is later made private
- **THEN** the saved CV's page marks that item as private now, and still contains it until the user removes it

### Requirement: Listing saved CVs
A posting's detail page SHALL list the posting's saved CVs, newest first, each with when it was produced, its match score at the time and a link to it, beside the "Tailor a CV" action. An application linked to a posting SHALL list the same CVs on its page.

#### Scenario: Application page
- **WHEN** a posting with two saved CVs has an application
- **THEN** the application's page lists both CVs, newest first

### Requirement: CV layout
A CV SHALL be laid out the same way in the preview and in the export:
- A header with the name, the headline, the month and year the CV was produced (for a saved CV, the month it was saved), and the contact details.
- Then sections in this order, each with a heading, leaving out empty ones: goal statements, summaries, highlights, then records by kind in the order `role`, `course`, `degree`, `publication`, `project`, `award`, `event`, `task`, `other`.
- A record SHALL print its title, its organisation and location, its dates, its description lines in order, and the addresses of its public sources (repository, site or DOI; uploaded-document sources are not printed).
- Dates SHALL print as the year for a year-only date and as month and year for a year-month date. A record with a start and end SHALL print both, and an ongoing record SHALL print its start and "present".
- Course records with the same title and organisation SHALL print as one entry, with the years of the first and last term as its dates and a line listing every term, oldest first. A term SHALL be named Winter (January to April), Summer (May to August) or Fall (September to December) when the record starts and ends within that window of one year; otherwise its dates print as dates.

#### Scenario: Condensed course
- **WHEN** four course records for "COMP 1000 Introduction to Programming" at Example Polytechnic run Winter 2024, Winter 2025, Winter 2026 and Fall 2026
- **THEN** the CV prints one entry dated 2024 – 2026 with the line "Winter 2024, Winter 2025, Winter 2026, Fall 2026"

#### Scenario: Produced month
- **WHEN** a CV is saved on 2026-10-16
- **THEN** its header shows "October 2026", also when it is exported later

#### Scenario: Empty section
- **WHEN** no project is chosen
- **THEN** the CV has no projects heading

### Requirement: Exporting a saved CV
A saved CV SHALL be downloadable as an OpenDocument Text (`.odt`) file. The file SHALL be a valid ODF package that opens in LibreOffice, and its text, read paragraph by paragraph, SHALL be the CV's text in layout order. The file name SHALL name the posting's company and title, with characters unsafe in file names removed. Only a saved CV SHALL be exportable, so every exported file corresponds to a stored CV.

#### Scenario: Export reads back
- **WHEN** a saved CV is exported and its text is extracted again
- **THEN** the lines are the header, headings, highlights and records of the CV, in the order the preview shows them

#### Scenario: Unsaved proposal
- **WHEN** the user is on a proposal that has not been saved
- **THEN** no export is offered, only saving

### Requirement: Saved CVs are user-authored
Saved CVs and their items SHALL be stored as user-authored data, written only through the user's own actions (saving, moving, removing, deleting). Importing or re-importing postings, running models, accepting or rejecting suggestions, and editing the profile SHALL leave them unchanged.

#### Scenario: Re-capture after saving
- **WHEN** a posting with a saved CV is re-captured with a changed description
- **THEN** the saved CV is unchanged
