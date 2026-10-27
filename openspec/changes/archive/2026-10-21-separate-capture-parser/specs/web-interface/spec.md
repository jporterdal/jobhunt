## MODIFIED Requirements

### Requirement: Postings always link to their original page
Wherever a posting appears (lists, detail page, application board, company page, Insights, CV pages, import report), the system SHALL show the posting's stored URL as a link labelled "Original posting" that opens in a new tab. The label SHALL NOT name a site.

#### Scenario: Posting list row
- **WHEN** the posting list shows a posting whose URL is `https://jobs.example.com/a-1042`
- **THEN** the row has an "Original posting" link to `https://jobs.example.com/a-1042` that opens in a new tab

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

Scraped data, user-authored data and model-derived data SHALL be visually distinct. Each retained capture of the posting SHALL be downloadable as its original file bytes.

#### Scenario: Viewing a posting
- **WHEN** the user opens a stored posting
- **THEN** the page shows its source, external ID, title, company, location, description, details, first and last seen, and an "Original posting" link

#### Scenario: Unknown job ID
- **WHEN** the user opens a detail URL whose key is not a stored posting's key, or is not a number
- **THEN** a 404 page is shown

#### Scenario: Downloading a capture
- **WHEN** the user downloads one of the posting's captures
- **THEN** the downloaded bytes are identical to the original file

### Requirement: Import from the browser
The interface SHALL provide an action that imports every file in the configured inbox, exactly as the inbox import command does. The action SHALL only run when the user triggers it. Afterwards it SHALL show the same per-file outcomes, warnings and rejection reasons as the command's report, with links to the imported postings.

#### Scenario: Importing two pages
- **WHEN** the inbox holds one new posting file and one file that no parser recognises, and the user clicks import
- **THEN** the report shows one `new` posting (with links to its detail page and to its original posting) and one `rejected` file with its reason, and both files have been moved out of the inbox

#### Scenario: Missing inbox
- **WHEN** the configured inbox folder does not exist and the user clicks import
- **THEN** an error naming the missing folder is shown and nothing is imported
