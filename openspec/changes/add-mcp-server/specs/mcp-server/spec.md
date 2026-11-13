## Purpose

A read-only Model Context Protocol (MCP) server that lets a client program on the user's machine read stored postings, the skill profile and the match figures through a few tools. Covers how the server starts, what the user must name before anything is shared, which tools each scope offers and what they return, what is never returned, and that the server writes nothing and contacts nothing.

## ADDED Requirements

### Requirement: MCP server command
The system SHALL provide a command, `jobhunt mcp`, that runs an MCP server over standard input and output for the program that started it, until that program closes the connection. The command SHALL accept the database with `--db`, defaulting as the other commands do. Standard output SHALL carry protocol messages only; everything else the command prints, including errors, SHALL go to standard error. The server SHALL need the packages of the optional `mcp` extra; when they aren't installed, the command SHALL print how to install the extra and exit with status 2. No other command or feature SHALL need those packages. The server SHALL offer tools only: no resources and no prompts.

#### Scenario: A client starts the server
- **WHEN** an MCP client starts `jobhunt mcp --db sqlite:////srv/jobhunt/demo/jobhunt.db --share postings` and asks for the tools
- **THEN** the server answers over standard output with the tools of the `postings` scope, and standard output holds nothing but protocol messages

#### Scenario: Extra not installed
- **WHEN** the `mcp` extra isn't installed and the user runs `jobhunt mcp --share postings`
- **THEN** the command prints on standard error that the MCP server needs the `mcp` extra and how to install it, and exits with status 2

#### Scenario: Other commands without the extra
- **WHEN** the `mcp` extra isn't installed
- **THEN** `jobhunt import`, `serve`, `eval` and `demo` work as before, and every test other than the MCP protocol tests passes

### Requirement: Sharing is named at start-up
The server SHALL share nothing unless the user names what to share when starting it, with `--share` followed by one or more scope names separated by commas. The scopes SHALL be `postings` and `profile`. Without `--share`, or with a scope that doesn't exist, the command SHALL exit with status 2 before opening the database, and its message SHALL say that tool results go to the program that starts the server, that this program may send them to a model outside this machine, what each scope shares, and where the documentation describes a set-up that keeps results on this machine. `jobhunt mcp --help` SHALL say the same. There SHALL be no default scope, no scope or value meaning every scope, and no environment variable that names scopes. The scopes SHALL be fixed when the command starts: no tool, protocol message, setting or web request SHALL change them. At start-up the server SHALL write to standard error which scopes it shares and from which database.

#### Scenario: No scope named
- **WHEN** a client starts `jobhunt mcp --db sqlite:////srv/jobhunt/demo/jobhunt.db`
- **THEN** the command exits with status 2 without opening the database, and its message explains that results may be sent to a model outside this machine, lists the scopes, and names the section of `docs/mcp.md` that sets up a client with a local model

#### Scenario: Unknown scope
- **WHEN** the user runs `jobhunt mcp --share postings,everything`
- **THEN** the command exits with status 2, naming `everything` as unknown and listing the scopes

#### Scenario: Environment doesn't opt in
- **WHEN** the environment holds `JOBHUNT_MCP_SHARE=postings,profile` and the user runs `jobhunt mcp` without `--share`
- **THEN** the command exits with status 2, as with no scope named

#### Scenario: Start-up statement
- **WHEN** the user runs `jobhunt mcp --share postings,profile`
- **THEN** standard error names `postings` and `profile` as shared, and the database

### Requirement: A fully local set-up is documented
The MCP server's documentation (`docs/mcp.md`) SHALL include a worked example of a set-up in which tool results stay on this machine: an MCP client running on this machine that starts `jobhunt mcp` over standard input and output and whose model is served by a local Ollama server at a loopback address, with no cloud model, account or fallback involved. The example SHALL give the client's configuration in full (with an absolute `--db`, the demo database's), name the client and model versions it was checked with, say which of the client's own settings could send data elsewhere (cloud providers, telemetry, sync) and how they are turned off, and say how to confirm that the client's model address is a loopback one. It SHALL be the first way of connecting a client that the page describes, ahead of any client that may use a cloud model, and those clients SHALL be introduced with the reminder that their model may receive whatever the named scopes share. The example SHALL have been run against the demo database as written, and any example result it shows SHALL come from the demo's fictional data.

#### Scenario: Reading how to connect a client
- **WHEN** the user opens `docs/mcp.md` to connect a client
- **THEN** the first set-up described uses a local Ollama model through a client on this machine, with a configuration that can be copied as written, and cloud-backed clients come after it

#### Scenario: Following a pointer from the command
- **WHEN** the command refuses to start without `--share`, or the user reads `jobhunt mcp --help`
- **THEN** the text names the section of `docs/mcp.md` with the local set-up, and that section exists

### Requirement: Scopes decide which tools are offered
The `postings` scope SHALL offer the tools `search_postings` and `get_posting`. The `profile` scope SHALL offer `posting_fit`, `profile_skills` and `recommendations`. A tool outside the named scopes SHALL NOT be listed to the client and SHALL NOT be callable. Each offered tool SHALL be listed with a description, a schema of its arguments and a schema of its result.

#### Scenario: Postings only
- **WHEN** the server runs with `--share postings` and a client lists the tools
- **THEN** it sees `search_postings` and `get_posting` and no other tool

#### Scenario: Calling a tool that isn't shared
- **WHEN** the server runs with `--share postings` and a client calls `profile_skills`
- **THEN** the call fails as a call to an unknown tool, and no profile data is returned

#### Scenario: Both scopes
- **WHEN** the server runs with `--share postings,profile`
- **THEN** all five tools are listed, each with its argument and result schemas

### Requirement: The server writes nothing
The server SHALL NOT change the database, the documents folder or the inbox: it SHALL add, change or delete no row and no file, queue no job, and record nothing about the calls it answers. It SHALL open the database so that the database itself refuses a write, on SQLite and on Postgres. It SHALL NOT create or upgrade a database: when the database's schema isn't the current one, or an SQLite database file doesn't exist, the command SHALL exit with status 2, leaving the database unchanged and creating no file or folder, and its message SHALL say how to upgrade the database with another command. The server SHALL offer no tool that writes.

#### Scenario: Tools leave the database unchanged
- **WHEN** a client calls every tool, with and without filters
- **THEN** every table holds the same rows as before, and no file under the documents folder or the inbox has changed

#### Scenario: Database from an older release
- **WHEN** the database is at an earlier schema revision and the user runs `jobhunt mcp --share postings`
- **THEN** the command exits with status 2 saying to run `jobhunt import` or `jobhunt serve` once to upgrade it, and the database's revision is unchanged

#### Scenario: Missing database file
- **WHEN** `--db` names an SQLite file that doesn't exist
- **THEN** the command exits with status 2 and the file still doesn't exist

#### Scenario: A write is refused by the database
- **WHEN** code running under the server's database connection attempts an insert
- **THEN** the database refuses it, on SQLite and on Postgres

### Requirement: The server contacts nothing
The server SHALL NOT call a model, contact the Ollama address, or start or run queued model work. It SHALL NOT listen on a network port, and SHALL NOT contact any address other than the configured trace endpoint while tracing is on (see `model-tracing`). Every result SHALL be computed from what is stored, with the same figures the web interface shows for the same database.

#### Scenario: Ollama stopped
- **WHEN** no Ollama server is running and a client calls each tool
- **THEN** every call answers, and no connection to the Ollama address is attempted

#### Scenario: Queue untouched
- **WHEN** model jobs are queued and the MCP server runs
- **THEN** the jobs stay queued and unchanged until `serve` runs them

### Requirement: Data that is never returned
Whatever scopes are named, no tool result SHALL contain: profile details (name, headline, contact details, summaries, goals); a record's title, organisation, dates, lines or sources, or a ground's quote; a highlight; a document, its name or its label; a posting's notes, dismissal reasons or skill-mark quotes; application events, notes, contacts or company data; saved CVs; captured files, earlier versions of a posting or its volatile details; model suggestions that failed verification; settings, queue jobs, evaluation data or trace ids. Results SHALL be built from named fields, so a field added to stored data later is not returned unless a tool's result is defined to include it.

#### Scenario: Identity stays out
- **WHEN** the profile holds the name "Jane Doe" and the contact detail `jane@example.com`, and a client calls every tool under `--share postings,profile`
- **THEN** no result contains "Jane Doe" or `jane@example.com`

#### Scenario: Notes stay out
- **WHEN** a posting has the note "Ask about the on-call rota" and a client calls `get_posting` for it
- **THEN** the result doesn't contain the note

#### Scenario: Shared fields are returned
- **WHEN** a posting titled "Data Engineer" at "Example Labs" is tagged `shortlist` and a client calls `search_postings`
- **THEN** the result contains the title, the company and the tag

### Requirement: Private records are never returned
No tool result SHALL contain anything of a record whose effective disclosure is private (the record itself, or any record it is part of, is private): not its title, organisation, dates, lines, source addresses or a quote from it, and not a count or identifier that refers to it. A tool that returns records or highlights SHALL leave such records out before choosing or counting anything, and SHALL leave out a highlight that mentions one. A profile skill SHALL be returned with its level whatever records ground it, since a skill's level is the user's own statement and not part of a record.

#### Scenario: A private record
- **WHEN** the profile has a private record titled "Fraud Scoring Rebuild" at "Example Bank" that grounds the skill "Python", and a client calls every tool under `--share postings,profile`
- **THEN** no result contains "Fraud Scoring Rebuild" or "Example Bank", and `profile_skills` still lists "Python" with its level

#### Scenario: Private through its context
- **WHEN** a public record "Model Monitoring" is part of a private record "Example Insurance Engagement"
- **THEN** no result contains "Model Monitoring" or "Example Insurance Engagement"

### Requirement: Postings in results carry their id and original URL
A posting SHALL be identified to clients by its integer posting id, the same number the web interface uses in a posting's address, and that id SHALL be the only identifier a tool takes. Every posting that appears in any tool's result SHALL carry its id, title, company and original URL. Each result SHALL be one JSON object that matches the tool's listed result schema; dates SHALL be ISO 8601 and times UTC; a field with no value SHALL be left out.

#### Scenario: URL in a ranking
- **WHEN** a client calls `recommendations` and posting 12, "Data Engineer" at "Example Labs", is ranked
- **THEN** its entry has `job_id` 12, the title, the company and `https://example.com/jobs/9000000001` as its `url`

#### Scenario: Unrated posting
- **WHEN** a posting has no interest rating and a client calls `get_posting` for it
- **THEN** the result has no `interest` field

### Requirement: Searching postings
`search_postings` SHALL return stored postings from their latest version, filtered and sorted as the postings list is: by text (in the title, company or description, or an exact external id), tag, minimum interest, unrated only, workplace type, application status (including any and none), dismissed postings (hidden by default, included, or only), and sorted by last seen (the default), first seen, posted date or interest. It SHALL return at most `limit` postings (20 by default, 50 at most) starting at `offset`, with the total number of matches and, when more remain, the offset of the next page. Each posting SHALL carry, besides its id, title, company and URL: location, workplace type, posted date, first and last seen, and the user's interest, fit, tags, whether it is dismissed and its application's status. The same filters and sort SHALL give the same postings in the same order as the postings list.

#### Scenario: Filtered search
- **WHEN** 3 stored postings mention "Airflow", one of them dismissed, and a client calls `search_postings` with `q` "Airflow"
- **THEN** the result has `total` 2 and the two undismissed postings, most recently seen first

#### Scenario: Paging
- **WHEN** 45 postings match and a client calls `search_postings` with `limit` 20 and `offset` 40
- **THEN** the result has `total` 45, 5 postings and no next offset

#### Scenario: Same order as the list
- **WHEN** a client calls `search_postings` with `sort` `interest` and `workplace` `Remote`
- **THEN** the postings and their order are those the postings list shows for the same filter and sort

### Requirement: Reading one posting
`get_posting` SHALL take a posting id and return the posting's latest version: the fields `search_postings` returns for it, its source, employment type, the precision of its posted date, how many versions are stored, its compared details, and its description as plain text. A description longer than 20,000 characters SHALL be cut at that length; the result SHALL always give the description's full length and SHALL say when it was cut.

#### Scenario: A posting
- **WHEN** a client calls `get_posting` with `job_id` 12
- **THEN** the result holds posting 12's title, company, original URL, details and description text, and no HTML markup

#### Scenario: A very long description
- **WHEN** a posting's description is 26,000 characters long
- **THEN** the result's description is its first 20,000 characters, with the full length 26000 and a flag that it was cut

### Requirement: A posting's fit
`posting_fit` SHALL take a posting id and return the posting's match score, how many skills it asks for and how many have no link, and its Have and Don't have lists, with the same score, entries and order as the skill summary on the posting page. A Have entry SHALL carry the skill's name, importance, whether it is the user's mark or a model suggestion, its credit, the profile skill the credit comes from with its level and relation, and whether the link is the user's, the same skill or the model's. A Don't have entry SHALL carry the skill's name, importance, origin and the reason (`missing`, `not-judged` or `no-link`), with the linked profile skill when the reason is `missing`. A posting without skills SHALL have no score and empty lists.

#### Scenario: Have and Don't have
- **WHEN** posting 12 requires "Python" (in the profile at `proficient`) and "Kubernetes" (no link), and a client calls `posting_fit` with `job_id` 12
- **THEN** the result has "Python" under Have with level `proficient`, relation `same` and its credit, "Kubernetes" under Don't have with reason `no-link`, and the score the posting page shows

#### Scenario: Posting without skills
- **WHEN** a posting has no marks and no extraction
- **THEN** `posting_fit` returns no score, 0 skills and empty Have and Don't have lists

### Requirement: Profile skills
`profile_skills` SHALL return every skill in the profile with its name, its level, whether the level was set by the user or came from a model, and its aliases, ordered from the highest level to the lowest and then by name, with the number of skills.

#### Scenario: Levels and aliases
- **WHEN** the profile has "Python" at `expert` with the alias "Python 3", and "Rust" at `learning`
- **THEN** `profile_skills` returns 2 skills, "Python" first with its level, level origin and the alias, then "Rust"

#### Scenario: Empty profile
- **WHEN** the profile has no skills
- **THEN** `profile_skills` returns a count of 0 and an empty list

### Requirement: Recommendations
`recommendations` SHALL return the two lists the Insights page shows, with the same members, order and figures: the recommended postings (each with its score, its score weighted by interest, and its largest gaps) and the skills to gain (each with its gain, how many postings it would improve, the other names pooled with it, and the postings it improves most), together with how many postings were considered and how many were left out for having no skills. It SHALL accept a list of workplace types that narrows the postings both lists consider, as the page's workplace filter does; an empty list or all three types SHALL mean no filter, and the result SHALL state the filter applied.

#### Scenario: Same ranking as Insights
- **WHEN** a client calls `recommendations` with no arguments
- **THEN** the postings and skills are those the Insights page lists, in the same order with the same scores and gains

#### Scenario: Workplace filter
- **WHEN** a client calls `recommendations` with `workplace` `["Remote", "Hybrid"]`
- **THEN** only postings whose latest version is Remote or Hybrid are considered in both lists, and the result names those two types as the filter

### Requirement: Tool errors
A call that names a posting id that doesn't exist SHALL fail with an error saying no posting has that id. A call with an argument outside the tool's listed schema (an unknown value, a number out of range, a missing or unknown argument) SHALL fail with an error naming the argument, and the tool SHALL NOT run; no argument SHALL be silently replaced by a default. A failed call SHALL return no data, and an error's text SHALL NOT quote stored text or the message of an unexpected failure.

#### Scenario: Unknown posting
- **WHEN** a client calls `get_posting` with `job_id` 999 and no such posting exists
- **THEN** the call fails with "No posting with id 999." and returns no data

#### Scenario: Unknown sort
- **WHEN** a client calls `search_postings` with `sort` `salary`
- **THEN** the call fails naming `sort`, and no postings are returned

#### Scenario: Limit out of range
- **WHEN** a client calls `search_postings` with `limit` 500
- **THEN** the call fails naming `limit`, instead of returning 50 or 500 postings
