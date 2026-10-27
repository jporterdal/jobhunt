# Security

jobhunt is a single-user tool that runs on your own machine. Its data (postings, notes, your profile and
uploaded documents) stays in a local database and folder, and model requests go only to the Ollama server you
configure.

## The web interface

- `jobhunt serve` listens on `127.0.0.1` by default. It has **no authentication**: anyone who can reach the
  address can read and change your data. A non-loopback `--host` prints a warning; only use one on a network you
  trust.
- Every request must carry a `Host` header naming the interface itself, which defeats DNS rebinding.
- Every request that can change data must come from a page of the interface: its `Origin` (or, without one, its
  `Referer`) must match, and requests with neither are refused. GET requests never change data.
- Posting descriptions are sanitized to an allowlist of HTML when they are imported; notes are rendered as
  Markdown with raw HTML disabled; links are limited to `http`, `https` and `mailto`.
- `--debug` turns on the Flask debugger, which can run code. Use it only for development, on loopback.

## Your data

- Imported files, the database and documents live under `inbox/` and `data/`, which are ignored by git. Back up
  `data/` yourself.
- `jobhunt privacy-check` scans a repository for values from your own database and for personal-looking patterns.
  Install the pre-commit hook (see `.pre-commit-config.yaml`) if you work on the code with your own data nearby.

## Reporting a vulnerability

Please report security problems privately through GitHub's private vulnerability reporting ("Report a
vulnerability" on the repository's Security tab), not in a public issue. Include the version or commit, what you
did, and what happened.
