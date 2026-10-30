# enrichment-evaluation Specification

## Purpose

Measures how well each model and pipeline version extracts skills, against postings the user has labelled. Prompt, model and segmentation changes can then be compared on numbers rather than impressions.

## Requirements

### Requirement: Labelled postings
The labelled set SHALL be the postings whose skill labelling the user has flagged complete. Each skill mark on a labelled posting SHALL count as **selected** when the user marked it from the text, and as **accepted** when it came from an accepted suggestion. Selected marks SHALL be the reference for recall. Accepted marks and rejected suggestions SHALL be the user's judgments of suggestions, used for precision only. Accepting a suggestion SHALL NOT remove a posting from the labelled set or change how its selected marks are scored.

#### Scenario: Blind and reviewed
- **WHEN** posting A is flagged complete with only selected marks, and posting B is flagged complete with one accepted suggestion
- **THEN** both are in the labelled set and scored together; the report has no separate blind or reviewed group

#### Scenario: Selected and accepted marks on one posting
- **WHEN** a posting is flagged complete with eight selected marks and two accepted suggestions
- **THEN** the posting is in the labelled set, recall is measured against its eight selected marks, and the two accepted marks count only toward precision

### Requirement: Evaluation command
The system SHALL provide `jobhunt eval`. Without the `--links` option (see `link-evaluation`), it SHALL run skill extraction on the latest snapshot of every labelled posting, using either the stored settings with the app's skill extraction method, or a model, segmentation method and one or more skill extraction methods given as options, and print a report. The skill extraction methods it accepts SHALL be the app's method and the registered candidate, if any. The report SHALL show:
- precision of suggested skills, for all skills and separately for required and preferred, together with the number of unjudged suggestions in each
- the number of wrong suggestions for each rejection reason: not a skill, not for me, and no reason given
- recall of selected marks, for all marks and separately for required and preferred
- agreement on importance among matched skills whose mark is selected and marked as required or preferred
- segment recall, and the number of missed skills attributed to each step (see "Attributing missed skills to a step")
- the number of failed runs
- the mean run time
- the number of selected marks created after their posting already had a successful run (an app run or an eval run), as a warning that suggestions may have prompted them. These marks SHALL still be scored as selected.

The command SHALL reuse a stored successful run, app or eval, for the same snapshot, model and pipeline version unless asked to run fresh. It SHALL store any new runs as eval runs (see "Derived data is stored separately and never edited" in `posting-enrichment`), which the app never uses, so evaluating never changes a posting's skills, links or suggestions in the app. The command SHALL accept database and Ollama address options with the same defaults as `serve`. The report SHALL be printable as JSON. The JSON report SHALL list, for each posting and method, the missed selected marks, the wrong suggestions with their rejection reason, and the unjudged suggestions, each by skill name and quote.

An unknown skill extraction method SHALL be refused before any model request, naming the available methods.

#### Scenario: Comparing two models
- **WHEN** the user runs `jobhunt eval --model gemma4:12b` and then `jobhunt eval --model phi4:latest`
- **THEN** each report states the model and pipeline version with its precision, unjudged count, recall and failure count, and the second run makes no requests for the first model

#### Scenario: No labelled postings
- **WHEN** no posting is flagged complete
- **THEN** the command says there are no labelled postings and how to label them, makes no model requests, and exits with a non-zero status

#### Scenario: Ollama unreachable
- **WHEN** the Ollama server is not running and some labelled postings have no stored run
- **THEN** the command reports that Ollama is unreachable and exits with a non-zero status without writing partial results

#### Scenario: Wrong suggestions by reason
- **WHEN** a run's wrong suggestions are two rejected as not a skill, one rejected as not for me and one rejected before reasons existed
- **THEN** the report shows 4 wrong, broken down as 2 not a skill, 1 not for me and 1 with no reason, and precision is computed from all 4

#### Scenario: Mark selected after a run
- **WHEN** a labelled posting's first successful run was stored on 2026-10-01 and the user selected a mark on it on 2026-10-03
- **THEN** the report counts one mark selected after a run, and the mark still counts toward recall

#### Scenario: Unknown skill method
- **WHEN** the user runs `jobhunt eval --skills atomic@3`
- **THEN** the command names the available methods, makes no model requests and exits with a non-zero status

#### Scenario: Removed method
- **WHEN** the user runs `jobhunt eval --skills atomic@4` after `atomic@4` was deleted, although stored `atomic@4` runs exist
- **THEN** the command names the available methods, makes no model requests and exits with a non-zero status

#### Scenario: Evaluating a candidate leaves the app alone
- **WHEN** the user runs `jobhunt eval --skills atomic@5` with a registered candidate `atomic@5`, and it stores new runs for the labelled postings
- **THEN** the new runs are eval runs, and each labelled posting's skills, "Model says" panel and links in the app are what they were before the command

#### Scenario: Reusing an app run
- **WHEN** a labelled posting has a successful app run on its latest snapshot with the model and pipeline being evaluated
- **THEN** the command scores that run and makes no request for the posting

#### Scenario: Link measurement instead
- **WHEN** the user runs `jobhunt eval --links`
- **THEN** the command measures links as `link-evaluation` describes, and does not run or score skill extraction

### Requirement: Matching suggestions to marks
A mark's quote SHALL be placed in the description at every whole-word occurrence, compared case-insensitively with whitespace collapsed. An occurrence SHALL be whole-word when it has no letter or digit directly before it if the quote starts with a letter or digit, and none directly after it if the quote ends with a letter or digit. When the quote has no whole-word occurrence, every occurrence SHALL be used.

A suggested skill SHALL match a mark on the same posting if their skill names are equal when compared case-insensitively with whitespace collapsed, or if the suggestion's quote overlaps any placement of the mark's quote. Matching by name SHALL be tried before matching by overlap. A suggestion SHALL be paired with a selected mark before an accepted one. Each mark and each suggestion SHALL match at most once. Rejected suggestions SHALL NOT match.

Among verified suggestions:
- a suggestion that matches a mark, selected or accepted, SHALL count as right
- a rejected suggestion SHALL count as wrong
- any other suggestion SHALL count as unjudged

Precision SHALL be the share of right suggestions among right and wrong ones, leaving unjudged suggestions out. Recall SHALL be the share of selected marks that some verified suggestion matches.

#### Scenario: Different name, same text
- **WHEN** the user marked "experience with PyTorch" as `PyTorch`, and the model suggests `PyTorch framework` quoting "PyTorch"
- **THEN** the suggestion matches the mark

#### Scenario: Missed skill
- **WHEN** a labelled posting has five selected marks and the model's verified suggestions match four of them
- **THEN** recall for that posting is 4/5

#### Scenario: Quote inside a longer word
- **WHEN** a mark quotes "Git", the description says "digital" in its first paragraph and "Git" in its requirements, and the model suggests `Version control` quoting "Git" in the requirements
- **THEN** the mark is placed only at the requirements occurrence, and the suggestion matches it

#### Scenario: Accepted suggestion
- **WHEN** the user accepted the suggestion `FastAPI` on a labelled posting and the evaluated run suggests `FastAPI`
- **THEN** the suggestion counts as right for precision, and recall is unchanged

#### Scenario: Rejected and unjudged suggestions
- **WHEN** a run's verified suggestions are three that match marks, one the user rejected, and two the user neither accepted nor rejected that match no mark
- **THEN** precision is 3/4 and the report shows two unjudged suggestions

### Requirement: Attributing missed skills to a step
For each successful run, the report SHALL attribute every selected mark that no verified suggestion matches to exactly one cause:
- **segmentation**, when the mark's quote is found in the description but no placement of it overlaps a span segmented as required or preferred
- **extraction**, when some placement of the mark's quote overlaps a span segmented as required or preferred
- **not located**, when the mark's quote is not found in the latest snapshot's description

Placements SHALL be as defined in "Matching suggestions to marks". Segment recall SHALL be the share of selected marks whose quote is found in the description that have a placement overlapping a span segmented as required or preferred, whether or not a suggestion matches them. Accepted marks SHALL NOT be attributed or counted in segment recall. Failed runs SHALL NOT be attributed; they count as failed runs.

#### Scenario: Line missed by the segmenter
- **WHEN** a mark quotes "Experience with Airflow" from a line the segmenter labelled other, and no suggestion matches the mark
- **THEN** the report counts one segmentation miss, and the mark is not counted as reached in segment recall

#### Scenario: Line reached but skill missed
- **WHEN** a mark quotes "MLflow" from a line segmented as required, and no suggestion matches the mark
- **THEN** the report counts one extraction miss, and the mark is counted as reached in segment recall

#### Scenario: Reached at a later occurrence
- **WHEN** a mark quotes "Python", which appears first in the title line (segmented other) and again in a line segmented as required, and no suggestion matches the mark
- **THEN** the report counts one extraction miss, not a segmentation miss

#### Scenario: Quote no longer in the description
- **WHEN** a mark's quote does not appear in the latest snapshot and no suggestion matches it
- **THEN** the report counts it as not located, and it is left out of segment recall

### Requirement: Comparing skill extraction methods
When `jobhunt eval` is given more than one skill extraction method (the app's method and the registered candidate), it SHALL evaluate each on the same labelled postings with the same model and segmentation method, reusing stored runs per method as for a single method. The report SHALL show each method's figures side by side, and SHALL list, per posting, the selected marks that some of the methods match and others do not, naming which methods match each. Before making model requests, the command SHALL state how many new runs each method needs.

#### Scenario: Comparing stored runs
- **WHEN** every labelled posting has stored successful runs for `atomic@2` and a registered candidate `atomic@5` with the current model, and the user runs `jobhunt eval --skills atomic@2,atomic@5`
- **THEN** the command makes no model requests and shows both methods' precision, unjudged count, recall and failure count side by side

#### Scenario: Marks found by one method only
- **WHEN** `atomic@2` matches the selected mark `CI/CD` on a posting and `atomic@5` does not
- **THEN** the report lists `CI/CD` under that posting as matched by `atomic@2` only

### Requirement: Dev and holdout sets
Every labelled posting SHALL belong to one of two sets, **dev** or **holdout**. A posting's set SHALL be decided when its labelling is first flagged complete, either by a draw (see "Drawing a posting's set") or by the user's choice (see "Choosing a posting's set by hand"), and SHALL be stored as user-authored data with how it was decided: drawn, chosen, moved to dev, or allocated before random allocation. Clearing the complete flag and setting it again SHALL keep the posting's set and SHALL NOT draw again. Only the user's move to dev SHALL change a posting's set afterwards.

The report SHALL show its figures for dev postings, for holdout postings, and for both together, with the number of postings in each, whether or not either set is empty. When some holdout postings were not drawn, the report SHALL also show the figures for the drawn holdout postings alone, with their number. The JSON report SHALL give each posting's set and how it was decided. The comparison of several methods SHALL show the same sets, and SHALL name each posting's set in its list of mark differences.

Postings whose labelling was flagged complete before this rule existed, whether or not the flag is still set, SHALL keep the set the held-out start gave them: postings first flagged complete after a recorded held-out start SHALL be holdout, and every other such posting SHALL be dev, each marked as allocated before random allocation.

#### Scenario: Both sets reported
- **WHEN** 7 labelled postings are dev and 6 are holdout, all drawn
- **THEN** the report shows figures for 7 dev postings, 6 holdout postings and 13 together, and no separate drawn-only figures

#### Scenario: Re-flagging keeps the set
- **WHEN** the user clears the complete flag on a holdout posting, edits its marks, and flags it complete again
- **THEN** the posting is still holdout, and no draw is made

#### Scenario: Drawn holdout postings alone
- **WHEN** the holdout set has 6 postings, 5 drawn and 1 chosen by hand
- **THEN** the report shows figures for the 6 holdout postings and, beside them, for the 5 drawn holdout postings

#### Scenario: Upgrading with no held-out start
- **WHEN** the database is upgraded with 9 labelled postings and no held-out start recorded
- **THEN** the 9 postings are dev, marked as allocated before random allocation, and the holdout set is empty

#### Scenario: Upgrading with a held-out start
- **WHEN** the database is upgraded with a held-out start recorded, 9 postings first flagged complete before it and 2 after it
- **THEN** the 9 are dev and the 2 are holdout, all marked as allocated before random allocation

### Requirement: Drawing a posting's set
When the user flags a posting's labelling complete for the first time and leaves its set to be drawn, the system SHALL put it in the holdout set with probability P and in the dev set otherwise, where, with r the holdout share (see "Holdout share setting"), N the number of labelled postings already in a set and H the number of those in holdout, the shortfall is d = r·N − H and

P = 1 / (1 + ((1 − r) / r) · e^(−d))

So P SHALL equal r when the holdout set holds exactly its share, and the odds of holdout SHALL multiply by e for each posting holdout falls short of its share, and divide by e for each posting it is ahead. Balance SHALL count labelled postings, whatever their number of marks, and SHALL count postings whose set was chosen by hand, moved or allocated before random allocation like drawn ones. Each draw SHALL be independent of the posting's content and of earlier draws apart from these counts.

#### Scenario: Balanced sets
- **WHEN** the holdout share is 0.5 and 10 labelled postings are split 5 dev and 5 holdout
- **THEN** the next posting flagged complete is drawn into holdout with probability 0.5

#### Scenario: Holdout behind its share
- **WHEN** the holdout share is 0.5 and the 9 labelled postings are all dev
- **THEN** the next posting is drawn into holdout with probability 0.989

#### Scenario: Another share
- **WHEN** the holdout share is 0.3 and 10 labelled postings include 2 holdout postings
- **THEN** the next posting is drawn into holdout with probability 0.538

### Requirement: Choosing a posting's set by hand
When flagging a posting's labelling complete for the first time, the user SHALL be able to choose Auto (the default: draw the set), Dev or Holdout. A posting already in a set SHALL NOT offer the choice. The user SHALL be able to move a holdout posting to dev at any time, whether or not its labelling is currently flagged complete. The system SHALL refuse to move a dev posting to holdout, saying that prompts may have been tuned on it.

#### Scenario: Choosing holdout
- **WHEN** the user picks Holdout and flags a posting's labelling complete for the first time
- **THEN** the posting is holdout, marked as chosen, and no draw is made

#### Scenario: Moving to dev
- **WHEN** the user moves a holdout posting to dev
- **THEN** the posting is dev, marked as moved, and the next report counts it as dev

#### Scenario: Dev to holdout refused
- **WHEN** a request asks to move a dev posting to holdout
- **THEN** the posting stays dev and the user is told that prompts may have been tuned on it

### Requirement: Holdout share setting
The settings page SHALL let the user set the holdout share r, the share of labelled postings the draw aims for in holdout, from 0.1 to 0.9, defaulting to 0.5. It SHALL be stored as user-authored data and survive restarts. Values outside the range SHALL be refused. Changing the share SHALL NOT move any posting: it affects only later draws. The settings page SHALL show the number of labelled postings in each set, and SHALL explain beside the share when to change it:
- raise it when new dev postings fail in ways already seen, so more labels go where decisions are made;
- lower it for a while when starting a round of prompt work with fewer than about 8 dev postings;
- raise it when method comparisons keep coming out within noise, since holdout is then too small to tell methods apart;
- changing it moves no posting, and later draws move towards the new share.

#### Scenario: Default share
- **WHEN** the user has never set the holdout share
- **THEN** the settings page shows 0.5, the help text, and the number of dev and holdout postings

#### Scenario: Changing the share
- **WHEN** 9 postings are dev and 0 holdout and the user sets the share to 0.3
- **THEN** no posting changes set, and the next draw uses the share 0.3

#### Scenario: Out of range
- **WHEN** a request sets the holdout share to 0.95
- **THEN** the share is unchanged and the page says it must be from 0.1 to 0.9

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
