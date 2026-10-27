## Purpose

Measures how well each model and pipeline version extracts skills, against postings the user has labelled. Prompt, model and segmentation changes can then be compared on numbers rather than impressions.

## ADDED Requirements

### Requirement: Labelled postings
The labelled set SHALL be the postings whose skill labelling the user has flagged complete. A labelled posting SHALL count as **blind** when none of its skill marks came from an accepted suggestion, and as **reviewed** otherwise.

#### Scenario: Blind and reviewed
- **WHEN** posting A is flagged complete with only selected marks, and posting B is flagged complete with one accepted suggestion
- **THEN** A is in the blind group and B is in the reviewed group

### Requirement: Evaluation command
The system SHALL provide `jobhunt eval`. It SHALL run skill extraction on the latest snapshot of every labelled posting, using either the stored settings or a model and segmentation method given as options, and print a report. The report SHALL show:
- precision and recall of suggested skills, for all skills and separately for required and preferred
- agreement on importance among matched skills that both sides mark as required or preferred
- segment recall, and the number of missed skills attributed to each step (see "Attributing missed skills to a step")
- the number of failed runs
- the mean run time

Each figure SHALL be given separately for the blind and reviewed groups. The command SHALL reuse a stored successful run for the same snapshot, model and pipeline version unless asked to run fresh, and SHALL store any new runs as normal derived data. The command SHALL accept database and Ollama address options with the same defaults as `serve`. The report SHALL be printable as JSON.

#### Scenario: Comparing two models
- **WHEN** the user runs `jobhunt eval --model gemma4:12b` and then `jobhunt eval --model phi4:latest`
- **THEN** each report states the model and pipeline version with its precision, recall and failure count, and the second run makes no requests for the first model

#### Scenario: No labelled postings
- **WHEN** no posting is flagged complete
- **THEN** the command says there are no labelled postings and how to label them, makes no model requests, and exits with a non-zero status

#### Scenario: Ollama unreachable
- **WHEN** the Ollama server is not running and some labelled postings have no stored run
- **THEN** the command reports that Ollama is unreachable and exits with a non-zero status without writing partial results

### Requirement: Matching suggestions to marks
A suggested skill SHALL match a user's mark on the same posting if their skill names are equal when compared case-insensitively with whitespace collapsed, or if their quotes overlap in the description text. Each mark and each suggestion SHALL match at most once. Precision SHALL be the share of verified suggestions that match a mark. Recall SHALL be the share of marks that some verified suggestion matches. Rejected suggestions SHALL count as unmatched suggestions.

#### Scenario: Different name, same text
- **WHEN** the user marked "experience with PyTorch" as `PyTorch`, and the model suggests `PyTorch framework` quoting "PyTorch"
- **THEN** the suggestion matches the mark

#### Scenario: Missed skill
- **WHEN** a labelled posting has five marks and the model's verified suggestions match four of them
- **THEN** recall for that posting is 4/5

### Requirement: Attributing missed skills to a step
For each successful run, the report SHALL attribute every mark that no verified suggestion matches to exactly one cause:
- **segmentation**, when the mark's quote is found in the description but overlaps no span segmented as required or preferred
- **extraction**, when the mark's quote overlaps a span segmented as required or preferred
- **not located**, when the mark's quote is not found in the latest snapshot's description

Segment recall SHALL be the share of marks whose quote is found in the description that overlap a span segmented as required or preferred, whether or not a suggestion matches them. Failed runs SHALL NOT be attributed; they count as failed runs.

#### Scenario: Line missed by the segmenter
- **WHEN** a mark quotes "Experience with Airflow" from a line the segmenter labelled other, and no suggestion matches the mark
- **THEN** the report counts one segmentation miss, and the mark is not counted as reached in segment recall

#### Scenario: Line reached but skill missed
- **WHEN** a mark quotes "MLflow" from a line segmented as required, and no suggestion matches the mark
- **THEN** the report counts one extraction miss, and the mark is counted as reached in segment recall

#### Scenario: Quote no longer in the description
- **WHEN** a mark's quote does not appear in the latest snapshot and no suggestion matches it
- **THEN** the report counts it as not located, and it is left out of segment recall
