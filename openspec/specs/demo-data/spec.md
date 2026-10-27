# demo-data Specification

## Purpose
Lets anyone try the app, and lets every screenshot be taken, with a fictional person's job search instead of real data: a single command builds a complete, self-contained demo database without a model server.

## Requirements

### Requirement: Demo command creates a separate database
The system SHALL provide `jobhunt demo --db URL --documents DIR` that creates a demo database and its documents. It SHALL refuse, changing nothing, when the target database already holds any posting, profile row or document, or when the documents folder isn't empty, so demo data is never mixed with real data. With no `--db` it SHALL default to `sqlite:///demo/jobhunt.db` and `demo/documents`, never to the real defaults. When it finishes, it SHALL print the `jobhunt serve` command that opens it.

#### Scenario: Demo into a new database
- **WHEN** `jobhunt demo` runs and `demo/` doesn't exist
- **THEN** it creates `demo/jobhunt.db` and `demo/documents/`, and prints `jobhunt serve --db sqlite:///demo/jobhunt.db --documents demo/documents`

#### Scenario: Real data is refused
- **WHEN** `jobhunt demo --db sqlite:///data/jobhunt.db` runs against a database holding postings
- **THEN** it exits non-zero, says the database isn't empty, and changes nothing

### Requirement: Demo content is fictional and complete
The demo SHALL use only invented values: one fictional person, invented companies, invented postings, synthetic posting IDs in the reserved `9000000` range, and addresses only on reserved example domains. It SHALL hold enough data for every page to show content: at least 8 postings brought in through the app's public import (with at least one posting imported twice with a changed snapshot), triage (ratings, tags, notes, a dismissal), skill marks, at least one application with events, a document, companies and a contact, a profile (details, records of several kinds including one private record, claims at several levels with grounds, highlights, aliases), model suggestions on postings, skill links, and one saved tailored CV.

#### Scenario: Every page has content
- **WHEN** `jobhunt serve` runs against a fresh demo database
- **THEN** the postings list, a posting page (with "Model says" suggestions and the Have / Don't have summary), Insights (scores and skill recommendations), the board, Profile, Profile links, a tailored CV proposal and the saved CV each show demo data, and the saved CV downloads as ODT

#### Scenario: Demo data passes the pattern check
- **WHEN** the privacy check runs in pattern-only mode over the demo package data
- **THEN** it reports nothing

### Requirement: Demo needs no model server
The demo SHALL be built without contacting Ollama or any network address. Model output SHALL come from the real pipeline steps run against scripted answers shipped with the demo, so stored runs, suggestions, validation and link judgments are made the way the app makes them. The model and embedding model SHALL be recorded under names that say they are scripted (`demo-scripted`, `demo-trigram`). With Ollama unreachable, every demo page SHALL still show its demo content.

#### Scenario: Built offline
- **WHEN** `jobhunt demo` runs with no Ollama server and no network
- **THEN** it succeeds, and the posting pages show the demo suggestions as model output from `demo-scripted`

### Requirement: Demo output is reproducible
Running the demo twice into empty targets SHALL produce the same content: the same rows with the same ids, texts, ratings and links. Dates SHALL be fixed relative to a constant demo date, so screenshots don't change from one build to the next.

#### Scenario: Two builds match
- **WHEN** the demo is built into two empty databases
- **THEN** every user-authored and derived table holds the same rows in both, apart from creation timestamps

### Requirement: Demo databases are labelled
A demo database SHALL be marked as one when created, and every page served from it SHALL show a "Demo data" label in the header.

#### Scenario: Banner shows
- **WHEN** any page is served from a demo database
- **THEN** the header shows "Demo data"

#### Scenario: No banner on real data
- **WHEN** a page is served from a database not created by `jobhunt demo`
- **THEN** no demo label is shown
