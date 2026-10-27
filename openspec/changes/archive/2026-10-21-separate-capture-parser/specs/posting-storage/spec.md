## ADDED Requirements

### Requirement: Existing postings are renumbered on upgrade
Upgrading a database to the source-neutral schema SHALL keep every stored posting and everything that refers to it. The upgrade SHALL:
- give each posting an integer key, numbered from 1 in order of first-seen time and then of its old ID
- set its external ID to its old ID, and its source to the host of its stored URL, lowercased and without a leading `www.`
- replace the old ID with the new key in every record that refers to the posting: user-authored, derived and operational
- move each snapshot's source-specific fields into its details (the fields that change on every visit into its volatile details), leaving out empty values
- recompute each snapshot's fingerprint by the new rule, so that a later re-capture with the same values is `unchanged`

A capture stored before the upgrade SHALL record no parser. A snapshot stored before it SHALL keep its recorded parser version.

#### Scenario: User data follows the new key
- **WHEN** a database holds a posting with ratings, tags, skill marks, an application, a saved CV, model runs and a queued job, and it is upgraded
- **THEN** the posting has an integer key, its old ID is its external ID, and every one of those records refers to the new key

#### Scenario: Source from the stored URL
- **WHEN** a posting stored with URL `https://www.jobs.example.com/view/1042/` is upgraded
- **THEN** its source is `jobs.example.com` and its external ID is `1042`

#### Scenario: Unchanged re-capture after the upgrade
- **WHEN** a posting is re-captured after the upgrade, and the parser reports the same core fields and details as before
- **THEN** the import reports `unchanged` and no snapshot is added

## MODIFIED Requirements

### Requirement: One posting record per source and external ID
The system SHALL keep exactly one posting record per source and external ID. Each posting SHALL have an integer key. The key is assigned when the posting is first stored and never changes, and every other record and the interface refer to the posting by it. Each record SHALL hold the URL reported by the parser that first stored the posting. Postings with different external IDs, or with the same external ID from different sources, SHALL be stored as separate postings, even when their title, company and location are identical.

#### Scenario: First capture of a job
- **WHEN** external ID `A-1042` from source `jobs.example.com` is imported for the first time
- **THEN** a posting record exists with a new integer key, that source and external ID, and the URL the parser reported

#### Scenario: Look-alike postings
- **WHEN** two postings from the same source, with different external IDs but the same title and location, are both imported
- **THEN** two separate posting records exist

#### Scenario: Same external ID from two sources
- **WHEN** external ID `1042` is imported from source `jobs.example.com` and from source `careers.example.org`
- **THEN** two separate posting records exist, with different keys

### Requirement: First-seen and last-seen times are tracked
Each posting SHALL record when it was first and last seen, using the capture time of its captures. Capture time SHALL be the time the accepting parser reports for the file, or else the file's modification time. Importing an older capture SHALL NOT move last-seen backwards or first-seen forwards.

#### Scenario: Re-capture later
- **WHEN** a posting first captured on 2026-09-20 is captured again on 2026-10-01
- **THEN** first-seen is 2026-09-20 and last-seen is 2026-10-01

#### Scenario: Importing an older capture after a newer one
- **WHEN** a capture from 2026-09-15 is imported after one from 2026-10-01
- **THEN** first-seen becomes 2026-09-15 and last-seen stays 2026-10-01

#### Scenario: Capture time given by the file
- **WHEN** a posting file with `captured_at` of 2026-09-01T09:00:00Z is imported, though the file was modified on 2026-10-10
- **THEN** the capture time, first-seen and last-seen are 2026-09-01T09:00:00Z

### Requirement: Snapshot history is preserved
The system SHALL store each accepted file's posting as a snapshot linked to its capture. A snapshot SHALL hold the core fields (title, company, location, workplace type, employment type, posted date and its precision, and the description as sanitized HTML and as plain text), plus the parser's details and volatile details. A re-capture SHALL add a new snapshot only if its compared content differs from the posting's latest snapshot; otherwise it SHALL only update last-seen. Compared content is every core field except the posted date and its precision, plus the details. Volatile details and the posted date SHALL be stored but not compared. Details SHALL be compared by name and value regardless of order, and a detail whose value is null, empty text or an empty list SHALL count as absent. Existing snapshots SHALL never be modified or deleted by an import. Each snapshot SHALL record the name and version of the parser that produced it.

#### Scenario: Unchanged re-capture
- **WHEN** a posting is re-captured and only its volatile details differ
- **THEN** no new snapshot is created, last-seen is updated, and the import reports `unchanged`

#### Scenario: Changed description
- **WHEN** a posting is re-captured with an edited description
- **THEN** a second snapshot is created, the first is unchanged, and the import reports `updated`

#### Scenario: Changed detail
- **WHEN** a posting is re-captured with the same core fields and one compared detail changed
- **THEN** a second snapshot is created and the import reports `updated`

### Requirement: Original captures are retained
For every accepted file, the system SHALL store the original file bytes, compressed. It SHALL also store their content hash, original filename, capture time, import time, the posting, and the name and version of the parser that accepted the file, so that captures can be re-parsed later without the source file. Captures SHALL be stored only in the local database and never sent anywhere.

#### Scenario: Retained capture matches the source
- **WHEN** a capture is imported and later read back from storage
- **THEN** the decompressed bytes are identical to the original file and their hash matches the stored hash

### Requirement: Scraped data is separate from user data
Posting, snapshot and capture records SHALL hold only data derived from imported files. User-authored data (triage data, applications and everything linked to them) SHALL be stored in separate records that refer to postings by their key. No import or re-import SHALL create, modify or delete user-authored data. The web interface SHALL write only user-authored data, except through the import action, which follows the import rules.

#### Scenario: Import touches only scraped tables
- **WHEN** an import runs
- **THEN** it writes only to the capture, posting and snapshot records

#### Scenario: User data survives re-import
- **WHEN** a posting with ratings, tags and an application is re-imported from a changed capture
- **THEN** all of its user-authored data is identical before and after the import

### Requirement: Storage runs on Postgres and SQLite
The system SHALL connect to a database given by a connection URL. The URL SHALL be configurable, and the default SHALL be a local SQLite file. Every storage behavior in this capability SHALL work the same on Postgres and SQLite. The schema SHALL be versioned, starting from a baseline version. Whenever the import or serve command opens a database, it SHALL create the schema in an empty database, or upgrade a database at the baseline version or later to the current version, without losing existing data. A database at a version older than the baseline, or one with tables but no version, SHALL be refused with a message saying it must first be upgraded by a release from before the baseline, and SHALL be left unchanged.

#### Scenario: Default SQLite database
- **WHEN** no database URL is configured and the import runs
- **THEN** a SQLite database is created at the documented default location and the postings are stored there

#### Scenario: Postgres database
- **WHEN** the database URL points to a Postgres database and the same captures are imported
- **THEN** the stored postings, snapshots and outcomes are the same as with SQLite

#### Scenario: Pre-versioning database
- **WHEN** a database with tables but no schema version is opened
- **THEN** the command stops with a message that the database predates the baseline, and the database is unchanged

#### Scenario: Database older than the baseline
- **WHEN** a database at a schema version older than the baseline is opened
- **THEN** the command stops with the same message, and the database is unchanged
