## MODIFIED Requirements

### Requirement: Labelled postings
The labelled set SHALL be the postings whose skill labelling the user has flagged complete. Each skill mark on a labelled posting SHALL count as **selected** when the user marked it from the text, and as **accepted** when it came from an accepted suggestion. Selected marks SHALL be the reference for recall. Accepted marks and rejected suggestions SHALL be the user's judgments of suggestions, used for precision only. Accepting a suggestion SHALL NOT remove a posting from the labelled set or change how its selected marks are scored.

#### Scenario: Blind and reviewed
- **WHEN** posting A is flagged complete with only selected marks, and posting B is flagged complete with one accepted suggestion
- **THEN** both are in the labelled set and scored together; the report has no separate blind or reviewed group

#### Scenario: Selected and accepted marks on one posting
- **WHEN** a posting is flagged complete with eight selected marks and two accepted suggestions
- **THEN** the posting is in the labelled set, recall is measured against its eight selected marks, and the two accepted marks count only toward precision

### Requirement: Evaluation command
The system SHALL provide `jobhunt eval`. It SHALL run skill extraction on the latest snapshot of every labelled posting, using either the stored settings or a model and segmentation method given as options, and print a report. The report SHALL show:
- precision of suggested skills, for all skills and separately for required and preferred, together with the number of unjudged suggestions in each
- recall of selected marks, for all marks and separately for required and preferred
- agreement on importance among matched skills whose mark is selected and marked as required or preferred
- segment recall, and the number of missed skills attributed to each step (see "Attributing missed skills to a step")
- the number of failed runs
- the mean run time

The command SHALL reuse a stored successful run for the same snapshot, model and pipeline version unless asked to run fresh, and SHALL store any new runs as normal derived data. The command SHALL accept database and Ollama address options with the same defaults as `serve`. The report SHALL be printable as JSON.

#### Scenario: Comparing two models
- **WHEN** the user runs `jobhunt eval --model gemma4:12b` and then `jobhunt eval --model phi4:latest`
- **THEN** each report states the model and pipeline version with its precision, unjudged count, recall and failure count, and the second run makes no requests for the first model

#### Scenario: No labelled postings
- **WHEN** no posting is flagged complete
- **THEN** the command says there are no labelled postings and how to label them, makes no model requests, and exits with a non-zero status

#### Scenario: Ollama unreachable
- **WHEN** the Ollama server is not running and some labelled postings have no stored run
- **THEN** the command reports that Ollama is unreachable and exits with a non-zero status without writing partial results

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
