# web-interface Specification

## Purpose

A local web interface for browsing stored postings, starting imports and recording the user's own data. It runs only on the user's machine and shows each posting's original URL as a link wherever the posting appears.

## Requirements

### Requirement: Serve command starts a local web app
The system SHALL provide a `serve` command that starts the web interface against the configured database. The database URL and inbox folder SHALL default the same way as the import command (environment variables, then the documented defaults). The host and port SHALL be configurable. Before accepting requests, the command SHALL bring the database schema up to date.

#### Scenario: Default start
- **WHEN** the user runs `jobhunt serve` with no options
- **THEN** the web interface is served on `127.0.0.1` at the documented default port, using the default database, and the address is printed

#### Scenario: Fresh database
- **WHEN** `serve` starts against a database file that does not exist yet
- **THEN** the database is created with the full schema and the posting list shows that there are no postings yet

### Requirement: Local-only by default
The web interface SHALL bind to the loopback address unless the user passes a different host. When a non-loopback host is given, the command SHALL print a warning that the interface has no authentication.

#### Scenario: Non-loopback host
- **WHEN** the user runs `jobhunt serve --host 0.0.0.0`
- **THEN** the server starts and prints a warning that anyone who can reach the address can read and change the data

### Requirement: Requests that change data must come from the interface itself
The system SHALL reject a data-changing request when its `Origin` header (or its `Referer` header, if `Origin` is absent) does not match the address the interface is served on. It SHALL also reject any request whose `Host` header does not match the configured host. Read-only requests SHALL NOT change data.

#### Scenario: Cross-site form post
- **WHEN** a page from another site submits a form to the interface's tagging URL
- **THEN** the request is rejected with status 403 and no data changes

#### Scenario: Rebound hostname
- **WHEN** a request arrives with `Host: attacker.example:8000`
- **THEN** it is rejected with status 403

### Requirement: Postings always link to their original page
Wherever a posting appears (lists, detail page, application board, company page, Insights, CV pages, import report), the system SHALL show the posting's stored URL as a link labelled "Original posting" that opens in a new tab. The label SHALL NOT name a site.

#### Scenario: Posting list row
- **WHEN** the posting list shows a posting whose URL is `https://jobs.example.com/a-1042`
- **THEN** the row has an "Original posting" link to `https://jobs.example.com/a-1042` that opens in a new tab

### Requirement: Posting list
The system SHALL list postings using each posting's latest snapshot. Each row SHALL show the title, company, location, workplace type, estimated posted date, last-seen date, the user's interest rating and tags, and the application status if there is one. By default the list SHALL be sorted by last-seen time, newest first, and SHALL hide dismissed postings.

#### Scenario: Default list
- **WHEN** the user opens the posting list and one of three postings is dismissed
- **THEN** two postings are shown, the most recently seen first

### Requirement: Posting search and filters
The posting list SHALL support:
- a case-insensitive text search across title, company and description text, which also lists any posting whose external ID equals the search text exactly
- filters for tag, minimum interest, unrated postings, workplace type, application status, and dismissed postings (hidden, included, or only)
- sorting by last seen, first seen, estimated posted date, or interest

The active search, filters and sort SHALL be encoded in the page URL, so that reloading or bookmarking the URL reproduces the same list. Search and filters SHALL behave the same on Postgres and SQLite.

#### Scenario: Search and filter combined
- **WHEN** the user searches for `pytorch` with the filter "interest at least 3"
- **THEN** only postings whose title, company or description contains "pytorch" (any case) and whose interest is 3 or more are listed

#### Scenario: Bookmarked filter
- **WHEN** the user reloads a list URL that carries a search and filters
- **THEN** the same postings are shown in the same order

#### Scenario: Searching by external ID
- **WHEN** the user searches for `A-1042`, the external ID of a posting whose text doesn't contain it
- **THEN** that posting is listed

### Requirement: Posting detail page
The system SHALL show a detail page for each posting at a URL carrying the posting's integer key, with:
- the posting's source and external ID
- the latest snapshot's core fields and its sanitized description, rendered with only the stored allowlisted markup
- the latest snapshot's details and volatile details, each as a name and a value
- the first-seen and last-seen times, and the number of captures
- the user's triage data and any linked application

Captured data, user-authored data and model-derived data SHALL be visually distinct. Each retained capture of the posting SHALL be downloadable as its original file bytes.

#### Scenario: Viewing a posting
- **WHEN** the user opens a stored posting
- **THEN** the page shows its source, external ID, title, company, location, description, details, first and last seen, and an "Original posting" link

#### Scenario: Unknown posting key
- **WHEN** the user opens a detail URL whose key is not a stored posting's key, or is not a number
- **THEN** a 404 page is shown

#### Scenario: Downloading a capture
- **WHEN** the user downloads one of the posting's captures
- **THEN** the downloaded bytes are identical to the original file

### Requirement: Snapshot history and diff
When a posting has more than one snapshot, the detail page SHALL list the snapshots with their capture dates. It SHALL be able to show the differences between any two of them, covering changed captured fields and a line-level diff of the description text.

#### Scenario: Edited description
- **WHEN** a posting has two snapshots whose descriptions differ by one paragraph
- **THEN** the diff view marks that paragraph as removed and/or added and shows the unchanged text as context

#### Scenario: Single snapshot
- **WHEN** a posting has only one snapshot
- **THEN** no diff action is offered

### Requirement: Import from the browser
The interface SHALL provide an action that imports every file in the configured inbox, exactly as the inbox import command does. The action SHALL only run when the user triggers it. Afterwards it SHALL show the same per-file outcomes, warnings and rejection reasons as the command's report, with links to the imported postings.

#### Scenario: Importing two pages
- **WHEN** the inbox holds one new posting file and one file that no parser recognises, and the user clicks import
- **THEN** the report shows one `new` posting (with links to its detail page and to its original posting) and one `rejected` file with its reason, and both files have been moved out of the inbox

#### Scenario: Missing inbox
- **WHEN** the configured inbox folder does not exist and the user clicks import
- **THEN** an error naming the missing folder is shown and nothing is imported

### Requirement: Insights page
The navigation SHALL include an Insights section. It SHALL show the posting recommendations and the skill recommendations (see the `recommendations` capability). When there is nothing to recommend, because no posting has skills or the profile has no skills, the page SHALL say which of the two is missing and how to fix it.

#### Scenario: Recommendations shown
- **WHEN** postings have skills and the profile has skills, and the user opens Insights
- **THEN** the page shows the recommended postings and the recommended skills

#### Scenario: Empty profile
- **WHEN** postings have skills but no skill has a level, and the user opens Insights
- **THEN** the page says the profile has no skills yet and links to the profile page
