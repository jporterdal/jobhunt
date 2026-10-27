## ADDED Requirements

### Requirement: Parsers are installed plug-ins
The system SHALL read postings only through parsers. A parser is registered by an installed package under the `jobhunt.parsers` entry-point group, and the system's own parsers SHALL be registered the same way. Each parser SHALL have a name and a version. Given a file's bytes, name and capture time, a parser SHALL return one of three results: a parsed posting (with optional warnings), a rejection with a reason (the file comes from the parser's origin but can't be used), or "not recognised". A parser SHALL recognise files by their contents, not by their file type, so several parsers can read the same file type. A parser that raises an error SHALL count as a rejection of that file by that parser, giving the error, and SHALL NOT stop the batch.

#### Scenario: A parser from another package
- **WHEN** a package that registers a parser under `jobhunt.parsers` is installed beside the app
- **THEN** the next import tries that parser on every file, with no change to the app

#### Scenario: Two parsers for HTML files
- **WHEN** two installed parsers both read HTML files, and an HTML file comes from the origin of only one of them
- **THEN** that parser accepts the file, the other reports it as not recognised, and the file is imported

#### Scenario: A parser fails
- **WHEN** a parser raises an error on a file while another file in the batch is accepted by a different parser
- **THEN** the failing file is rejected with the parser's name and the error, and the other file is imported

### Requirement: Exactly one parser must accept a file
The system SHALL try every installed parser on every file it processes. It SHALL import a file only when exactly one parser accepts it, and SHALL store nothing from any other file. The rejection reason SHALL say why:
- when no parser accepts the file but one or more reject it, it SHALL give each rejecting parser's name and reason
- when no parser recognises the file, it SHALL say so and name the installed parsers with their versions
- when more than one parser accepts the file, it SHALL name the accepting parsers

#### Scenario: Accepted by one parser
- **WHEN** one installed parser accepts a file and every other parser does not recognise it
- **THEN** the file is imported as that parser's posting

#### Scenario: Recognised but unusable
- **WHEN** the only parser that recognises a file rejects it because its description is empty
- **THEN** the file is rejected with that parser's name and reason

#### Scenario: Nothing recognises the file
- **WHEN** no installed parser recognises a file
- **THEN** the file is rejected with a reason naming each installed parser and its version

#### Scenario: Two parsers accept the same file
- **WHEN** two installed parsers both accept a file
- **THEN** the file is rejected with a reason naming both parsers, and nothing is stored

### Requirement: Identity comes from the accepting parser
The system SHALL identify an accepted file's posting by the source and external ID that the accepting parser reports. A source SHALL be a lowercase name of letters, digits, dots and hyphens. By convention, for a posting from a website, the source is the website's host without a leading `www.`. The system SHALL NOT use the filename to determine identity.

#### Scenario: Re-capture under another filename
- **WHEN** a file for source `jobs.example.com` and external ID `A-1042` is imported, and a later file with a different name reports the same source and external ID
- **THEN** both captures belong to the same posting

#### Scenario: Same external ID, different sources
- **WHEN** files report external ID `1042` for source `jobs.example.com` and for source `careers.example.org`
- **THEN** they are stored as two postings

### Requirement: Built-in posting file format
The system SHALL include a parser for posting files: one JSON object per file, with `"format": "jobhunt-posting"` and `"version": 1`. The object SHALL have a `source`, an `external_id`, a `url` (an `http` or `https` address), a `title`, a `company` and a `description_html`, each non-empty. It MAY have:
- `location`, `workplace_type` (`On-site`, `Hybrid` or `Remote`) and `employment_type`
- `posted_on`: an ISO date, with an optional `posted_precision` (`minute`, `hour`, `day`, `week`, `month` or `year`; default `day`)
- `captured_at`: an ISO date-time with a time zone, used as the capture time instead of the file's modification time
- `details` and `volatile_details`: objects mapping a name to text, a number, true or false, a list of text, or null

The parser SHALL NOT recognise a file that isn't a JSON object with that `format`. It SHALL reject a posting file with an unsupported version, a missing or empty required field, a value of the wrong type, an unknown workplace type or precision, or an unknown top-level field, and the reason SHALL name the field.

#### Scenario: A complete posting file
- **WHEN** the inbox holds a posting file with every required field, a workplace type of `Remote` and a posted date
- **THEN** it is imported with those values

#### Scenario: Missing field
- **WHEN** a posting file has no `company`
- **THEN** it is rejected with a reason naming `company`

#### Scenario: Other JSON is not recognised
- **WHEN** the inbox holds a JSON file without `"format": "jobhunt-posting"`
- **THEN** the posting-file parser reports it as not recognised

#### Scenario: Unsupported version
- **WHEN** a posting file has `"version": 2`
- **THEN** it is rejected with a reason naming the unsupported version

### Requirement: Descriptions are sanitized at import
The system SHALL sanitize every accepted posting's description HTML, whichever parser produced it. Only paragraphs, line breaks, lists, list items, headings, bold, italic, underline and links SHALL be kept. Other tags SHALL be unwrapped, keeping their text. Scripts, styles, buttons and comments SHALL be removed, along with every attribute except a link's address, and a link's address SHALL be kept only for `http`, `https` and `mailto` addresses. Sanitizing already sanitized HTML SHALL leave it unchanged. When the parser gives no plain-text form, the system SHALL derive it from the sanitized HTML, with each paragraph, line break and list item on its own line and list items starting with `- `. Characters such as emoji and accented letters SHALL be kept unchanged.

#### Scenario: Unsafe markup
- **WHEN** a posting file's description contains a `<script>`, an `onclick` attribute and a link to `javascript:alert(1)`
- **THEN** the stored description has no script, no event attribute and no `javascript:` address, and the link's text remains

#### Scenario: Plain text from a list
- **WHEN** a posting file's description is a list of three items with emoji
- **THEN** the stored plain text has three lines starting with `- `, with the emoji kept

#### Scenario: Parser-supplied text
- **WHEN** a parser supplies its own plain-text form with the description
- **THEN** that text is stored, and the HTML is still sanitized

## MODIFIED Requirements

### Requirement: Import scans an inbox folder
The system SHALL provide an import command that processes every file directly inside a configured inbox folder. It SHALL ignore subfolders. A file that an installed parser names as a companion of another file in the inbox, or that is the download metadata the operating system keeps beside another inbox file (named after it, followed by `:Zone.Identifier`), SHALL NOT be processed on its own; it SHALL move with that file. Files SHALL be processed oldest first, by modification time. The inbox location SHALL be configurable, with a documented default.

#### Scenario: Inbox files are discovered
- **WHEN** the inbox contains `a.json`, the download-metadata file for `a.json`, `b.html` and a folder `c/`
- **THEN** the import processes exactly `a.json` and `b.html`, and the download-metadata file moves with `a.json`

#### Scenario: Companion named by a parser
- **WHEN** an installed parser names `page.txt` and `page.meta` as companions of `page.html` in the inbox
- **THEN** neither companion is processed on its own, and both move with `page.html`

#### Scenario: Empty inbox
- **WHEN** the inbox contains no files
- **THEN** the import reports that there was nothing to import and makes no changes

### Requirement: Processed files leave the inbox
After processing, the system SHALL move each file out of the inbox, together with its companions: those named by the parser that accepted it, or for a rejected file those named by any installed parser, and its download-metadata file if present. Imported, updated, unchanged and duplicate files SHALL go to a processed folder. Rejected files SHALL go to a rejected folder. The system SHALL NOT delete any file. If the destination already has a file with the same name, the system SHALL choose a non-conflicting name for the file and its companions rather than overwrite.

#### Scenario: Accepted file is moved with its companions
- **WHEN** `a.json` and its download-metadata file are imported
- **THEN** both are in the processed folder and neither remains in the inbox

#### Scenario: Rejected file is set aside
- **WHEN** a file is rejected
- **THEN** it and its companions are in the rejected folder and nothing from it is stored

#### Scenario: Name collision in the destination
- **WHEN** the processed folder already contains a file named `a.json` and another `a.json` is processed
- **THEN** both files are kept, and the new one gets a distinct name

### Requirement: Import produces a report
The system SHALL print one line per processed file. The line SHALL give the filename, the outcome (`new`, `updated`, `unchanged`, `duplicate` or `rejected`), and, when known, the posting's source and external ID, title, company and URL, followed by any warnings or the rejection reason. The system SHALL end with a count per outcome.

#### Scenario: Mixed batch
- **WHEN** the inbox holds one new posting, one re-capture with changed content, and one file no parser recognises
- **THEN** the report has one `new`, one `updated` and one `rejected` line with its reason, followed by totals of 1 new, 1 updated, 1 rejected

## REMOVED Requirements

### Requirement: Captures are validated before import
**Reason**: Validation was written for the one parser that existed. Each parser now decides what it accepts, and the importer's rule is that exactly one parser must accept a file.
**Migration**: See "Exactly one parser must accept a file" and "Built-in posting file format". Its validation rules move to the private parser package's own specs.

### Requirement: Identity comes from page content
**Reason**: Identity is now the source and external ID that the accepting parser reports, not a marker in one site's pages.
**Migration**: See "Identity comes from the accepting parser". How the private parser finds its external ID is specified in its own package.

### Requirement: Filename mismatches are reported
**Reason**: The filename pattern it checked is specific to that parser's files.
**Migration**: The private parser reports a mismatch as a warning on the posting it returns, and the import report shows parser warnings as before.
