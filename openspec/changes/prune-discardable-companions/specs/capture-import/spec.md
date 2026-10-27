## ADDED Requirements

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

## MODIFIED Requirements

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
