# Fictional data

Every person, organisation, posting and address in this repository is invented. Tests, specs, the design record, the
documentation and the demo (`jobhunt demo`) all draw on one cast, so they agree with each other. Use it for new
examples too, and keep to its reserved values: the privacy check (`jobhunt privacy-check`) passes them and reports
real-looking ones.

## The cast

| Kind | Values |
|---|---|
| Person | Jane Doe, `jane@example.com`, `+1 555 555 0100` |
| Other people | Any name with an `example` address (`@example.com`, `@example.org`, `@example.net`, or a `.example` domain) |
| Organisations | Example University, Example Polytechnic, Example Institute, Example Bank, Example Advisory, Example Province, Example Labs, Example Systems, Example Insurance, Example Payments |
| Conference | EXCONF 2024 (its track: Applied Optimization Track) |
| Place | Example City, EX |
| Course codes | `COMP 1000`, `COMP 1100`, … |
| Paper DOIs | the `10.5555/` example prefix, e.g. `https://doi.org/10.5555/3600000.3600001` |
| Repositories | `https://github.com/janedoe-example/…` |
| Other web addresses | `example.com`, `example.org`, `repository.example.edu` |
| Posting IDs | `9000000001` and up (the privacy check reserves every number starting `9000000`) |
| Posting sources | `example.com`, `example.org` |
| Phone numbers | North American `555-01xx` numbers only |

## Conventions

- Names with "Example" can't collide with a real person or employer. A real employer's name is never used, even
  with invented details.
- Posting titles may be ordinary job titles ("Data Engineer"). Descriptions and the lines quoted from them are
  written fresh, not adapted from a real posting.
- Profile examples (records, degrees, courses, highlights) belong to Jane Doe, not to anyone real.
- Real-looking values that a test needs (to check that the privacy check finds them) are built at runtime, so no
  tracked file holds one.
