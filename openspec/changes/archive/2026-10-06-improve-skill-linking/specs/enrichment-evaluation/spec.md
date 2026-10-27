## MODIFIED Requirements

### Requirement: Evaluation command
The system SHALL provide `jobhunt eval`. Without the `--links` option (see `link-evaluation`), it SHALL run skill extraction on the latest snapshot of every labelled posting, using either the stored settings or a model, segmentation method and one or more skill extraction methods given as options, and print a report. The report SHALL show:
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

#### Scenario: Link measurement instead
- **WHEN** the user runs `jobhunt eval --links`
- **THEN** the command measures links as `link-evaluation` describes, and does not run or score skill extraction
