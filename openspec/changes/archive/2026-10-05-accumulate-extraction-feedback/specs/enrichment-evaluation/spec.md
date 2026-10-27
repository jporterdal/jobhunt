## MODIFIED Requirements

### Requirement: Evaluation command
The system SHALL provide `jobhunt eval`. It SHALL run skill extraction on the latest snapshot of every labelled posting, using either the stored settings or a model, segmentation method and one or more skill extraction methods given as options, and print a report. The report SHALL show:
- precision of suggested skills, for all skills and separately for required and preferred, together with the number of unjudged suggestions in each
- the number of wrong suggestions for each rejection reason: not a skill, not for me, and no reason given
- recall of selected marks, for all marks and separately for required and preferred
- agreement on importance among matched skills whose mark is selected and marked as required or preferred
- segment recall, and the number of missed skills attributed to each step (see "Attributing missed skills to a step")
- the number of failed runs
- the mean run time
- the number of selected marks created after their posting already had a successful run, as a warning that suggestions may have prompted them. These marks SHALL still be scored as selected.

The command SHALL reuse a stored successful run for the same snapshot, model and pipeline version unless asked to run fresh, and SHALL store any new runs as normal derived data. The command SHALL accept database and Ollama address options with the same defaults as `serve`. The report SHALL be printable as JSON. The JSON report SHALL list, for each posting and method, the missed selected marks, the wrong suggestions with their rejection reason, and the unjudged suggestions, each by skill name and quote.

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

## ADDED Requirements

### Requirement: Comparing skill extraction methods
When `jobhunt eval` is given more than one skill extraction method, it SHALL evaluate each on the same labelled postings with the same model and segmentation method, reusing stored runs per method as for a single method. The report SHALL show each method's figures side by side, and SHALL list, per posting, the selected marks that some of the methods match and others do not, naming which methods match each. Before making model requests, the command SHALL state how many new runs each method needs.

#### Scenario: Comparing stored runs
- **WHEN** every labelled posting has stored successful runs for `atomic@2` and `atomic@4` with the current model, and the user runs `jobhunt eval --skills atomic@2,atomic@4`
- **THEN** the command makes no model requests and shows both methods' precision, unjudged count, recall and failure count side by side

#### Scenario: Marks found by one method only
- **WHEN** `atomic@2` matches the selected mark `CI/CD` on a posting and `atomic@4` does not
- **THEN** the report lists `CI/CD` under that posting as matched by `atomic@2` only

### Requirement: Development and held-out postings
The user SHALL be able to start a held-out set from the settings page, recording the time it starts. The start SHALL be stored as user-authored data and survive restarts, and the user SHALL be able to see and clear it. Once a held-out set is started, a labelled posting SHALL be **held-out** when its labelling was first flagged complete after the start, and **development** otherwise. Clearing and setting the complete flag again SHALL NOT change when a posting was first flagged complete. The report SHALL show its figures for development postings, for held-out postings, and for both together, with the number of postings in each. With no start recorded, the report SHALL show one set, as before. The settings page SHALL show how many labelled postings are in each set.

#### Scenario: Labelled after the start
- **WHEN** the user started the held-out set on 2026-10-06, 9 postings were flagged complete before it and 4 after it
- **THEN** the report shows figures for 9 development postings, 4 held-out postings and 13 together

#### Scenario: No held-out set
- **WHEN** the user has never started a held-out set
- **THEN** the report shows one set of figures for every labelled posting, as before

#### Scenario: Re-flagging keeps a posting in development
- **WHEN** the user clears the complete flag on a development posting after the start, edits its marks, and flags it complete again
- **THEN** the posting is still reported as development
