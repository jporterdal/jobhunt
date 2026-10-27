# release-privacy Specification

## Purpose
Keeps the user's personal information out of a public repository: it finds the user's own values (taken from their local database and a private term list) and personal-looking patterns in tracked files, staged changes and git history, and forbidden kinds of file left untracked, and fails until each finding is removed or explicitly allowed.

## Requirements

### Requirement: Personal values come from the local database
The privacy check SHALL build its list of personal values from the configured database without changing it. The list SHALL include every profile detail, record title, record organisation, record line, record source address, highlight, document filename and label, posting external ID, posting title, posting company name, company name and address, contact name and profile address, application note, posting note and tag. It SHALL add each line of an optional private term file. Values shorter than 4 characters SHALL be dropped. Values SHALL be compared case-insensitively with runs of whitespace treated as one space. The list SHALL never be written anywhere except the terminal.

#### Scenario: A CV fact in a test is found
- **WHEN** the database has a record with organisation "Northgate University" and a tracked test file contains `"Northgate University"`
- **THEN** the check reports that file and line under the category `record organisation` and exits non-zero

#### Scenario: Case and spacing don't hide a value
- **WHEN** a contact's name is "Ada Quill" and a tracked spec contains "ada  QUILL"
- **THEN** the check reports it

#### Scenario: Private terms are added
- **WHEN** the private term file lists an old employer's name that the database doesn't hold, and a tracked comment mentions it
- **THEN** the check reports it under the category `private term`

#### Scenario: A private component's name is found
- **WHEN** the private term file lists the name of the job site a private component handles, and a tracked doc, an archived change or a commit message mentions it in any case
- **THEN** the check reports each mention under the category `private term` (commit messages with `--history`)

#### Scenario: No database is available
- **WHEN** the check runs with `--patterns-only`, or the database doesn't exist
- **THEN** it runs only the pattern checks and says that personal values and private terms were not checked

### Requirement: Personal-looking patterns are found without a database
The privacy check SHALL report, whether or not a database is available: numbers of 9 or 10 digits that look like posting IDs, except the reserved synthetic range starting `9000000`; email addresses, except at `example.com`, `example.org`, `example.net`, any `.example` or `.invalid` domain, and GitHub noreply addresses; phone numbers, except North American `555-01xx` numbers; and home-directory paths that name a user (`/home/<name>/`, `/Users/<name>/`, `C:\Users\<name>\`).

#### Scenario: A real job ID in a spec is found
- **WHEN** a tracked spec contains a posting address whose ID is ten digits outside the synthetic range
- **THEN** the check reports it under the category `job id`

#### Scenario: Synthetic values pass
- **WHEN** tracked files contain `9000000001`, `jane@example.com`, `+1 555 555 0100` and `jane@acme.example`
- **THEN** none of them is reported

#### Scenario: A home path is found
- **WHEN** a tracked settings file contains an absolute path into a named user's home directory
- **THEN** the check reports it under the category `home path`

### Requirement: Forbidden file kinds are refused
The privacy check SHALL report every tracked or staged file that is a database (`.db`, `.sqlite`, `.sqlite3`), an office or PDF document (`.odt`, `.docx`, `.doc`, `.pdf`), a saved web page (`.htm`, `.html`) outside `tests/fixtures/synthetic/` and the web templates, a `*:Zone.Identifier` file, or any file under `data/`, `inbox/` or `tests/fixtures/private/`. It SHALL also report every untracked file of these kinds, and every untracked folder holding one, that the ignore rules don't cover, since a later `git add -A` would commit it.

#### Scenario: An unignored backup is found
- **WHEN** the working tree has an untracked, unignored folder `data.bak-2026-10-15/` that holds `cv.odt` and `jobhunt.db`
- **THEN** the check reports the folder under the category `unignored personal file` and exits non-zero

#### Scenario: Synthetic fixtures pass
- **WHEN** `tests/fixtures/synthetic/two_jobs.html` is tracked
- **THEN** it is not reported as a forbidden file kind (its content is still scanned)

### Requirement: Scopes cover files, staged changes and history
By default the privacy check SHALL scan every file git tracks, as it is in the working tree. With `--staged` it SHALL scan the staged version of each staged file. With `--history` it SHALL also scan, for every commit reachable from any ref, each file's content at that commit, the commit message, and the author and committer names and emails. With `--history`, the author and committer fields SHALL also be checked against the private term file.

#### Scenario: A value removed from the tree is still in history
- **WHEN** a value was removed from a file in the latest commit but an earlier commit still has it
- **THEN** the default scan passes and the `--history` scan reports it with the commit id

#### Scenario: A personal author email is found
- **WHEN** a commit was authored with an email the private term file lists
- **THEN** `--history` reports that commit under the category `commit identity`

### Requirement: Findings never print the value by default
Each finding SHALL state the path (and the commit for history findings), line, column, category and a masked value (its first character and its length). The full value SHALL be printed only with `--show`. The check SHALL exit 0 when nothing is found and 1 otherwise, and SHALL end with a count per category.

#### Scenario: CI logs stay clean
- **WHEN** the check finds a personal email in CI without `--show`
- **THEN** the log shows the path, line, column, `email` and a masked value such as `j… (19 chars)`, and not the address

### Requirement: Findings can be allowed explicitly
A private allow file (ignored by git) SHALL suppress a database value or private term, either everywhere or only under a given path prefix. Its entries are values themselves, so it SHALL never be tracked; the check SHALL report the allow file if it is tracked or staged. A pattern finding (not a database value) SHALL be suppressed by the marker `privacy: allow` on the same line, and each suppression SHALL be counted in the summary.

#### Scenario: A generic posting title is allowed
- **WHEN** a posting title "Data Scientist" is in the database, a tracked spec uses "Data Scientist" as an example, and the allow file lists "Data Scientist"
- **THEN** it is not reported

#### Scenario: The public handle is allowed as the commit identity
- **WHEN** the private term file lists the user's GitHub handle, the public repository's commits are made under that handle, and the allow file lists the handle under the path `<commit author or committer>`
- **THEN** the commits' author and committer fields are not reported, and the handle is still reported in any file

#### Scenario: An inline marker cannot hide a database value
- **WHEN** a line holding a record's organisation ends with `privacy: allow`
- **THEN** the finding is still reported

### Requirement: The public repository enforces the check
The public repository SHALL run the pattern-only check on every push and pull request in CI and fail the build on any finding. A local pre-commit hook SHALL run the full check with `--staged` against the user's database. No release tag SHALL be made unless a full `--history` check against the user's database passes on the public repository.

#### Scenario: A pull request adds a real job ID
- **WHEN** a pull request adds a file containing a ten-digit job ID outside the synthetic range
- **THEN** the CI privacy job fails
