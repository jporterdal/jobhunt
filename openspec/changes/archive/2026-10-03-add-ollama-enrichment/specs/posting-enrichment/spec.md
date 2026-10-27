## Purpose

Uses a local model to suggest each posting's salary ranges and its required and preferred skills. Every suggestion is checked against the posting text, stored as derived data, and becomes the user's own data only when the user accepts it.

## ADDED Requirements

### Requirement: Step-wise extraction with replaceable steps
Extraction SHALL run as separate steps:
- **Segmentation:** labels spans of the description as required, preferred or other.
- **Skill extraction:** runs on the required and preferred spans.
- **Salary extraction:** runs on lines that mention pay.
- **Validation:** checks the results.

A span SHALL be identified by its start and end position in the snapshot's description text, never by rewritten text. Each step SHALL have a name and a version. A run SHALL record the model and every step's name and version. Replacing one step's method SHALL NOT require changes to the other steps or to stored results of earlier runs. The system SHALL provide at least two segmentation methods: one based on rules that needs no model, and one that uses the model to classify lines.

#### Scenario: Run identifies its steps
- **WHEN** a posting is extracted with model `gemma4:12b` and the line-classifier segmenter
- **THEN** the stored run names the model and the name and version of the segmenter, skill extractor, salary extractor and validator

#### Scenario: Switching segmenter
- **WHEN** the user switches the segmentation method to rule-based and extracts a posting extracted earlier with the line classifier
- **THEN** a new run is stored next to the earlier one, and both remain viewable

### Requirement: Salary ranges
Salary extraction SHALL run only on lines that mention money or pay. A posting with no such lines SHALL get an empty salary result without a model request. The result SHALL be a list of ranges. Each range SHALL have:
- a minimum and maximum amount (either may be absent)
- currency
- period (for example year or hour)
- location, when the text ties the range to one
- basis: base, on-target earnings, or unclear
- the verbatim quote it came from

#### Scenario: Two ranges in two currencies
- **WHEN** a description says "base salary in the range of $175,000 - $200,000 USD (Example Metro, EX), $110,000 - $130,000 CAD (Example City, EX)"
- **THEN** two ranges are stored: 175000–200000 USD per year for Example Metro, and 110000–130000 CAD per year for Example City

#### Scenario: No pay mentioned
- **WHEN** no line of the description mentions money or pay
- **THEN** the run stores no salary ranges and makes no salary model request

### Requirement: Required and preferred skills
Skill extraction SHALL return atomic skills, one technology, tool, method, domain or competency each. A listed series SHALL be split into separate skills. Each skill SHALL have:
- a short name
- importance: required or preferred, taken from the span it came from
- kind: technical, domain or soft
- a verbatim quote from the description

When a span group (required or preferred) has at least one span but the extractor returns no skills for it, the step SHALL be retried once. If it is still empty, the run SHALL be marked failed and SHALL NOT be stored as finding no skills.

#### Scenario: Splitting a list
- **WHEN** a required line reads "Expert-level Python, with experience in MLflow and Spark"
- **THEN** separate required skills are suggested for Python, MLflow and Spark, each quoting text from that line

#### Scenario: Empty result is a failure
- **WHEN** segmentation finds four required lines and skill extraction returns no skills twice
- **THEN** the run is marked failed with an error saying no skills were extracted from the required lines

### Requirement: Validation against the text
Every suggested skill and salary range SHALL be checked against the snapshot's description. The check compares case-insensitively, with whitespace collapsed. A quote SHALL count as verified only if it occurs in the description text. A salary range SHALL count as verified only if its quote is verified and each of its amounts occurs in the quote, allowing written forms such as `175,000`, `175000` and `175k`. Unverified items SHALL be stored and flagged. They SHALL be hidden from default views, kept apart from verified items, and SHALL NOT be accepted until the user shows them.

#### Scenario: Invented quote
- **WHEN** the model suggests skill `Kubernetes` with a quote that does not occur in the description
- **THEN** the suggestion is stored as unverified and is not shown among the posting's suggested skills by default

#### Scenario: Wrong amount
- **WHEN** a salary range has maximum 210000 but its quote says "$175,000 - $200,000"
- **THEN** the range is stored as unverified

### Requirement: Derived data is stored separately and never edited
Each run SHALL be stored as derived data, keyed by posting, snapshot, model and pipeline version, with its creation time, its status (succeeded or failed), any error, and each step's output. Runs SHALL NOT be edited or overwritten. Extracting again SHALL add a new run. Re-capturing a posting SHALL NOT change or delete runs. Extraction SHALL NOT write scraped data or user-authored data.

#### Scenario: Re-extraction keeps history
- **WHEN** a posting is extracted twice with different models
- **THEN** both runs are stored, and the earlier run's results are unchanged

#### Scenario: Re-capture after extraction
- **WHEN** an extracted posting is re-captured with a changed description
- **THEN** the earlier run is kept and is labelled as made on an older snapshot

### Requirement: Requesting extraction
The posting detail page SHALL offer an action to queue extraction of the posting's latest snapshot with the selected model and segmentation method. The posting list SHALL offer an action to queue extraction for every listed, non-dismissed posting that has no successful run for its latest snapshot with the current model and pipeline. Before the user confirms, the action SHALL state how many postings it will queue. Queuing a posting that already has a queued or running job SHALL NOT add a second job.

#### Scenario: Bulk extraction
- **WHEN** the list shows 28 postings, 3 dismissed and 5 already extracted with the current settings, and the user starts bulk extraction
- **THEN** the action says it will queue 20 postings and, once confirmed, queues 20 jobs

#### Scenario: Double request
- **WHEN** the user clicks extract twice on a posting whose job is still queued
- **THEN** only one job is queued for that posting

### Requirement: Model output on the posting page
The posting detail page SHALL show the "Model says" panel when the posting has at least one run. The panel SHALL be styled as model-derived data, distinct from scraped and user-authored data. It SHALL show the latest run, and the user SHALL be able to switch to any earlier run of the posting. For the shown run it SHALL display:
- model, pipeline version and time
- verified salary ranges
- verified required skills and verified preferred skills, each with its quote
- a control to show unverified items
- when the run is for an older snapshot, a label saying so and an action to extract the current snapshot
- for a failed run, the error

Model output SHALL be shown as plain text and never interpreted as markup.

#### Scenario: Viewing suggestions
- **WHEN** the user opens a posting with a successful run on its latest snapshot
- **THEN** the panel shows the model name, salary ranges, and required and preferred skills with their quotes

#### Scenario: Markup in model output
- **WHEN** a suggested skill name is `<b>Go</b>`
- **THEN** the page shows the text `<b>Go</b>` literally

### Requirement: Accepting and rejecting suggestions
For a run on the posting's latest snapshot, the user SHALL be able to accept a verified skill suggestion. Accepting SHALL create a skill mark with the suggestion's skill name, quote and importance, and an origin showing it came from a suggestion. Skill names SHALL be matched to existing skills case-insensitively. The user SHALL be able to accept all verified suggestions in one group (required or preferred) with one action. A suggestion whose skill the posting already marks SHALL be shown as already marked and SHALL NOT be accepted again. The user SHALL be able to reject a suggestion. A rejected skill SHALL be hidden for that posting in every run, including later ones, until the user undoes the rejection. Suggestions from runs on older snapshots SHALL NOT be acceptable.

#### Scenario: Accepting a required skill
- **WHEN** the user accepts the required suggestion `MLflow` quoting "MLflow for experiment tracking"
- **THEN** the posting has a skill mark for `MLflow` with that quote, importance required and origin suggestion, and the suggestion shows as already marked

#### Scenario: Rejection survives re-extraction
- **WHEN** the user rejects suggestion `Communication` on a posting and later extracts the posting again
- **THEN** the new run's `Communication` suggestion is hidden as rejected, and the user can show and undo it

### Requirement: Salary in the posting list
The posting list SHALL show, for each posting, a short summary of the first verified salary range from the latest successful run on the posting's latest snapshot. The summary SHALL be styled as model-derived data, and SHALL say how many more ranges exist when there are several. Postings without such a run SHALL show no salary.

#### Scenario: Salary column
- **WHEN** a posting's latest run has verified ranges 175000–200000 USD per year and 110000–130000 CAD per year
- **THEN** its list row shows "$175k–200k/yr" marked as model output, with "+1 more"
