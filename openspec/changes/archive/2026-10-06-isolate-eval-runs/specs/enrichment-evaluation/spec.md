## MODIFIED Requirements

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

### Requirement: Comparing skill extraction methods
When `jobhunt eval` is given more than one skill extraction method (the app's method and the registered candidate), it SHALL evaluate each on the same labelled postings with the same model and segmentation method, reusing stored runs per method as for a single method. The report SHALL show each method's figures side by side, and SHALL list, per posting, the selected marks that some of the methods match and others do not, naming which methods match each. Before making model requests, the command SHALL state how many new runs each method needs.

#### Scenario: Comparing stored runs
- **WHEN** every labelled posting has stored successful runs for `atomic@2` and a registered candidate `atomic@5` with the current model, and the user runs `jobhunt eval --skills atomic@2,atomic@5`
- **THEN** the command makes no model requests and shows both methods' precision, unjudged count, recall and failure count side by side

#### Scenario: Marks found by one method only
- **WHEN** `atomic@2` matches the selected mark `CI/CD` on a posting and `atomic@5` does not
- **THEN** the report lists `CI/CD` under that posting as matched by `atomic@2` only
