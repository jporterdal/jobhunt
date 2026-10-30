## ADDED Requirements

### Requirement: Eval windows
`jobhunt eval` SHALL accept two optional windows on skill extraction:
- `--posted-within AGE` keeps the labelled postings whose posted date is on or after the day AGE before now. A posting's posted date SHALL be its latest snapshot's posted date, or the day it was first seen when that snapshot has none.
- `--labelled-within AGE` keeps the labelled postings whose labelling was last flagged complete at or after the moment AGE before now. The latest flagging SHALL be used, not the first.

AGE SHALL be a positive whole number followed by a unit: `d` (days), `w` (weeks), `m` (calendar months) or `y` (calendar years). Any other AGE SHALL be refused before any model request, saying what an age looks like. When both windows are given, a posting SHALL be inside the window only when it passes both.

A window SHALL NOT change which postings are run or scored, which set a posting is in, or any stored data. With a window, the report SHALL show each set's figures (see "Dev and holdout sets") for all labelled postings and, beside them, for the labelled postings inside the window, with the number of postings in each and the number the window left out. The figures for all postings SHALL be the same as without a window. A window that keeps no posting SHALL still be reported, its ratios shown as not available. The report SHALL state the window as the options given and the earliest date or time each keeps, and SHALL state that decisions to adopt or delete a method use the figures for all postings, and the windowed figures are for diagnosis.

The JSON report SHALL keep its existing fields and values, and with a window SHALL add the window, the windowed figures for together and for each set, and, for each posting, whether it is inside the window. The comparison of several methods SHALL show each method's windowed figures the same way.

`--links` SHALL NOT take a window: given with `--links`, a window option SHALL be refused before any model request.

#### Scenario: Recent postings beside all postings
- **WHEN** 13 postings are labelled, 5 of them posted in the last 12 months, and the user runs `jobhunt eval --posted-within 12m`
- **THEN** the report shows each set's figures for the 13 postings and, beside them, for the 5, says 8 postings were left out, and the figures for the 13 are the ones `jobhunt eval` shows without a window

#### Scenario: Posting with no posted date
- **WHEN** a labelled posting's latest snapshot has no posted date and the posting was first seen 20 days ago, and the user runs `jobhunt eval --posted-within 1m`
- **THEN** the posting is inside the window

#### Scenario: Latest labelling counts
- **WHEN** a posting was first flagged complete 10 months ago, unflagged, and flagged complete again 2 months ago, and the user runs `jobhunt eval --labelled-within 6m`
- **THEN** the posting is inside the window

#### Scenario: Both windows
- **WHEN** the user runs `jobhunt eval --posted-within 12m --labelled-within 6m`
- **THEN** only labelled postings posted in the last 12 months and last flagged complete in the last 6 months are inside the window

#### Scenario: Window and sets
- **WHEN** a holdout posting is outside the window
- **THEN** it is still counted as holdout in the figures for all postings, it is not in the windowed holdout figures, and its set is unchanged

#### Scenario: Empty window
- **WHEN** no labelled posting was flagged complete in the last 7 days and the user runs `jobhunt eval --labelled-within 7d`
- **THEN** the report shows the figures for all postings, says the window keeps 0 postings, and exits with status 0

#### Scenario: Which figures decide
- **WHEN** the user runs `jobhunt eval` with a window
- **THEN** the report says that decisions to adopt or delete a method use the figures for all postings, and the windowed figures are for diagnosis

#### Scenario: Malformed age
- **WHEN** the user runs `jobhunt eval --posted-within 12months` or `jobhunt eval --labelled-within 0d`
- **THEN** the command says an age is a positive whole number followed by d, w, m or y, makes no model requests and exits with a non-zero status

#### Scenario: JSON with a window
- **WHEN** the user runs `jobhunt eval --labelled-within 6m --json`
- **THEN** the top-level figures and `sets` are those for all postings, and the JSON adds the window, the windowed figures and each posting's place inside or outside it

#### Scenario: Comparing methods with a window
- **WHEN** the user runs `jobhunt eval --skills atomic@2,atomic@5 --posted-within 12m`
- **THEN** the report shows both methods' figures for all postings and for the postings inside the window

#### Scenario: Not with link measurement
- **WHEN** the user runs `jobhunt eval --links --posted-within 12m`
- **THEN** the command says the window options don't apply to `--links`, makes no model requests and exits with a non-zero status
