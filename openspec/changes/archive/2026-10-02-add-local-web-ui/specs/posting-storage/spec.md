## MODIFIED Requirements

### Requirement: Scraped data is separate from user data
Posting, snapshot and capture records SHALL hold only data derived from captured pages. User-authored data (triage data, applications and everything linked to them) SHALL be stored in separate records that reference postings by job ID. No import or re-import SHALL create, modify or delete user-authored data. The web interface SHALL write only user-authored data, except through the import action, which follows the import rules.

#### Scenario: Import touches only scraped tables
- **WHEN** an import runs
- **THEN** it writes only to the capture, posting and snapshot records

#### Scenario: User data survives re-import
- **WHEN** a posting with ratings, tags and an application is re-imported from a changed capture
- **THEN** all of its user-authored data is identical before and after the import

### Requirement: Storage runs on Postgres and SQLite
The system SHALL connect to a database given by a connection URL. The URL SHALL be configurable, and the default SHALL be a local SQLite file. Every storage behavior in this capability SHALL work the same on Postgres and SQLite. The schema SHALL be versioned. Whenever the import or serve command opens a database, it SHALL create the schema in an empty database or upgrade an older one to the current version, without losing existing data. A database created before schema versioning existed SHALL be adopted as the baseline version and then upgraded.

#### Scenario: Default SQLite database
- **WHEN** no database URL is configured and the import runs
- **THEN** a SQLite database is created at the documented default location and the postings are stored there

#### Scenario: Postgres database
- **WHEN** the database URL points to a Postgres database and the same captures are imported
- **THEN** the stored postings, snapshots and outcomes are the same as with SQLite

#### Scenario: Pre-versioning database
- **WHEN** a database created by the first release (scraped tables only, no schema version) is opened by the new version
- **THEN** it is marked as the baseline version, the user-data tables are added, and every existing posting, snapshot and capture is unchanged
