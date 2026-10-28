# capture-import Specification

## Purpose

Turns files that a person has put into an inbox folder into identified captures, through installed parsers. Identity always comes from the accepting parser, never from the filename.

## Requirements

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

### Requirement: Re-import is idempotent
The system SHALL recognize a file whose bytes are identical to an already-stored capture and SHALL skip it without changing any stored data.

#### Scenario: Same file imported twice
- **WHEN** a file is imported, then copied back into the inbox and imported again
- **THEN** the second import reports it as an already-imported duplicate and the stored data is unchanged

### Requirement: Processed files leave the inbox
After processing, the system SHALL move each file out of the inbox, together with its companions: those named by the parser that accepted it, or for a rejected file those named by any installed parser, and its download-metadata file if present. Discardable companions SHALL move like any other. Imported, updated, unchanged and duplicate files SHALL go to a processed folder. Rejected files SHALL go to a rejected folder. The import SHALL NOT delete any file; only the prune removes files, and only discardable companions. If the destination already has a file with the same name, the system SHALL choose a non-conflicting name for the file and its companions rather than overwrite.

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

### Requirement: A single file can be imported directly
The import command SHALL also accept explicit file paths. It SHALL process those files with the same validation, identity, storage and report rules, and SHALL NOT move them.

#### Scenario: Importing a file outside the inbox
- **WHEN** the user runs the import on `copy.html` in the repository root
- **THEN** the file is validated and imported as usual and stays where it is

### Requirement: Parsers can mark companions as discardable
A parser that names companions SHALL be able to name, for a file, which of those companions are discardable: files kept only so they move with the file, and not needed once it has been filed away. A path SHALL count as discardable only when the same parser also names it as a companion of that file. A file's download metadata (named after it, followed by `:Zone.Identifier`) and the file itself SHALL never count as discardable. A parser that names no discardable companions, or raises an error when asked, SHALL mark nothing. Marking a companion discardable SHALL NOT change how the import discovers, processes or moves files.

#### Scenario: A parser marks its asset folder
- **WHEN** an installed parser names `page_files/` and `page.meta` as companions of `page.html` and marks `page_files/` as discardable
- **THEN** `page_files/` is discardable and `page.meta` is kept

#### Scenario: A path that isn't the parser's companion
- **WHEN** a parser marks `other.html` as discardable for `page.html` but doesn't name it as a companion of `page.html`
- **THEN** `other.html` is not discardable

#### Scenario: Download metadata is never discardable
- **WHEN** a parser names and marks `page.html:Zone.Identifier` as a discardable companion of `page.html`
- **THEN** the download metadata is kept

#### Scenario: Import still moves discardable companions
- **WHEN** `page.html` with a discardable `page_files/` is imported from the inbox
- **THEN** both are moved to the processed folder, and nothing is deleted

### Requirement: The prune removes discardable companions
The system SHALL provide a prune that removes discardable companions from the inbox's processed and rejected folders and removes nothing else. For each file directly inside those folders, it SHALL ask every parser installed at the time of the prune, and SHALL remove each existing companion that any of them marks as discardable for that file. It SHALL remove only paths directly inside the folder holding the file; a companion that is a symbolic link SHALL be removed as a link, without touching what it points to. It SHALL NOT touch files directly in the inbox, the files themselves, their download metadata, or any companion no installed parser marks, including companions of a parser that is no longer installed. A path that disappears while the prune runs SHALL count as already removed. A path the prune cannot remove SHALL be reported with its reason and SHALL NOT stop the prune. The prune SHALL report how many companions it removed and their total size in bytes.

#### Scenario: Asset folders are removed, pages kept
- **WHEN** the processed folder holds `a.html` with a discardable `a_files/`, and the rejected folder holds `b.html` with a discardable `b_files/` and `b.html`'s download metadata
- **THEN** the prune removes `a_files/` and `b_files/`, keeps `a.html`, `b.html` and the download metadata, and reports 2 companions removed with their total size

#### Scenario: Renamed after a name clash
- **WHEN** the processed folder holds `a (2).html` and `a (2)_files/`, moved there under new names after a clash, and a parser marks `<stem>_files/` discardable
- **THEN** the prune removes `a (2)_files/`

#### Scenario: The inbox itself is untouched
- **WHEN** the inbox holds `c.html` and its discardable `c_files/`, not yet imported
- **THEN** the prune leaves both in place

#### Scenario: Parser no longer installed
- **WHEN** the processed folder holds a file whose companions only an uninstalled parser named
- **THEN** the prune removes none of them

#### Scenario: A link to elsewhere
- **WHEN** a discardable companion in the processed folder is a symbolic link to a folder outside the inbox
- **THEN** the prune removes the link, and the folder it pointed to and its contents are unchanged

#### Scenario: A companion that can't be removed
- **WHEN** one discardable companion can't be removed (for example, for lack of permission) and another can
- **THEN** the prune removes the other, and reports the first with its reason

### Requirement: The server prunes daily
While the web server runs, the system SHALL prune its inbox at start-up when no prune of that inbox has been recorded in the last 24 hours, and again each time 24 hours have passed since the latest prune of that inbox. Pruning SHALL NOT delay starting the server or block requests or model jobs. The server SHALL print one line for each prune, with the number of companions and bytes removed and the number of problems. Stopping the server SHALL stop the schedule, and a prune in progress SHALL stop after the companion it is removing.

#### Scenario: First start after upgrading
- **WHEN** the server starts and no prune of its inbox has ever been recorded
- **THEN** it prunes at once, prints the result, and records the prune

#### Scenario: Restarted within a day
- **WHEN** the server starts 3 hours after the latest recorded prune of its inbox
- **THEN** it doesn't prune at start-up, and prunes 21 hours later if it is still running

#### Scenario: Running for days
- **WHEN** the server keeps running for 3 days after a prune at start-up
- **THEN** it prunes three more times, about 24 hours apart

#### Scenario: Missing inbox
- **WHEN** the server's inbox folder doesn't exist when a prune is due
- **THEN** nothing is removed, and the prune is recorded with 0 removed

### Requirement: The prune can be run from the command line
The system SHALL provide a `jobhunt inbox prune` command that prunes the configured inbox once, with the same inbox and database options and defaults as the import command, prints each removed companion with its size, then the totals and any problems, and records the prune. With `--dry-run`, it SHALL list what would be removed with its size and the totals, remove nothing and record nothing. It SHALL exit with status 0 when every discardable companion was removed (or would be, in a dry run), 1 when any could not be removed, and 2 when the inbox folder doesn't exist.

#### Scenario: Dry run
- **WHEN** the user runs `jobhunt inbox prune --dry-run` with two discardable companions in the processed folder
- **THEN** both are listed with their sizes and total, both are still there afterwards, and no prune is recorded

#### Scenario: Pruning by hand resets the schedule
- **WHEN** the user runs `jobhunt inbox prune` and starts the server an hour later
- **THEN** the prune is recorded, and the server doesn't prune at start-up

### Requirement: Prunes are recorded
The system SHALL record each prune other than a dry run, whether run by the server or the command, and whether or not it removed anything: when it started and finished, the inbox it pruned, how many companions and bytes it removed, and the problems it met. Records SHALL be kept, not overwritten. Prune records SHALL be operational data: no other import, user-authored or derived data SHALL change when a prune is recorded. The web interface's Import page SHALL show the latest prune of its inbox (when it finished, how many companions and how much space it removed, and how many problems), or that the inbox has not been pruned.

#### Scenario: The Import page shows the latest prune
- **WHEN** the latest prune of the server's inbox removed 3 companions totalling 120 MB with no problems
- **THEN** the Import page states when it finished, and that it removed 3 companions (120 MB)

#### Scenario: Never pruned
- **WHEN** no prune of the server's inbox has been recorded
- **THEN** the Import page says the inbox has not been pruned
