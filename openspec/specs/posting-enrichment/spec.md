# posting-enrichment Specification

## Purpose

Uses a local model to suggest each posting's salary ranges and its required and preferred skills. Every suggestion is checked against the posting text, stored as derived data, and becomes the user's own data only when the user accepts it.

## Requirements

### Requirement: Step-wise extraction with replaceable steps
Extraction SHALL run as separate steps:
- **Segmentation:** labels spans of the description as required, preferred or other. A span describing the hire's work, whether a duty bullet or prose about the role, SHALL count as required, unless it states that something is a plus or preferred. Spans about the company, team, product, benefits, pay or legal matters, and headings, SHALL count as other.
- **Skill extraction:** runs on the required and preferred spans.
- **Salary extraction:** runs on lines that mention pay.
- **Validation:** checks the results.

A span SHALL be identified by its start and end position in the snapshot's description text, never by rewritten text. Each step SHALL have a name and a version. A run SHALL record the model and every step's name and version. Replacing one step's method SHALL NOT require changes to the other steps or to stored results of earlier runs. The system SHALL provide at least two segmentation methods: one based on rules that needs no model, and one that uses the model to classify lines. The rule-based method SHALL treat a heading that introduces duties (for example "Responsibilities" or "What you'll do") as starting a required section.

Skill extraction methods SHALL be identified by name and version. The app SHALL use one skill extraction method, named by the code: `atomic@2` (see "Required and preferred skills"). It SHALL NOT offer a choice between skill extraction methods. Besides the app's method, the system SHALL register at most one other version, a candidate under measurement. Only `jobhunt eval` SHALL use a candidate. A queued extraction whose pipeline names a step version the system no longer provides SHALL fail with an error that names the pipeline, and SHALL store no run.

#### Scenario: Run identifies its steps
- **WHEN** a posting is extracted with model `gemma4:12b` and the line-classifier segmenter
- **THEN** the stored run names the model and the name and version of the segmenter, skill extractor, salary extractor and validator

#### Scenario: Switching segmenter
- **WHEN** the user switches the segmentation method to rule-based and extracts a posting extracted earlier with the line classifier
- **THEN** a new run is stored next to the earlier one, and both remain viewable

#### Scenario: Two versions of a skill extractor side by side
- **WHEN** the system registers `atomic@2` and a candidate `atomic@5`, and a posting has an app run with `skills=atomic@2` and an eval run with `skills=atomic@5`
- **THEN** both runs stay stored, the app uses the `atomic@2` run, `jobhunt eval --skills atomic@2,atomic@5` can score both, and nothing in the web interface offers `atomic@5`

#### Scenario: Queued job naming a removed version
- **WHEN** a queued extraction's pipeline id contains `skills=atomic@4`, which the system no longer provides
- **THEN** the job fails with an error naming that pipeline, no run is stored, and later jobs still run

#### Scenario: Duty line is required
- **WHEN** a line under "Key Responsibilities" reads "Lead the supervised fine-tuning work, including building task-specific datasets"
- **THEN** the line is segmented as required, and skill extraction runs on it

#### Scenario: Company description is other
- **WHEN** a line reads "Example Labs maintains one of the largest collections of anonymised retail transactions in the region"
- **THEN** the line is segmented as other

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
Skill extraction SHALL return atomic skills that a span asks for or that the work it describes uses. A skill SHALL be one of:
- a technology, tool, platform, language or method
- a soft skill that names a capability, such as communication or stakeholder management
- a call for an advanced degree

Skill extraction SHALL NOT return personality traits (such as adaptability or comfort with ambiguity), industries or subject domains, fields of study, or fragments that name no skill on their own. A listed series SHALL be split into separate skills. An advanced degree SHALL be named by its level: `PhD`, `Master's degree`, or `Advanced degree` when no level is stated. When several levels qualify, the lowest SHALL be used. The field of study SHALL be left in the quote only. Each skill SHALL have:
- a short name
- importance: required or preferred, taken from the span it came from
- kind: technical, soft or qualification
- a verbatim quote from the description

When a run's verified skills include more than one skill with the same name (compared case-insensitively, with whitespace collapsed), only one SHALL be kept among the run's suggestions, at the highest importance found: required over preferred. Among items of that importance, the first in the posting SHALL be kept. Unverified items SHALL NOT take part in this merge.

When a span group (required or preferred) has at least one span but the extractor returns no skills for it, the step SHALL be retried once. If it is still empty, the run SHALL be marked failed and SHALL NOT be stored as finding no skills.

#### Scenario: Splitting a list
- **WHEN** a required line reads "Expert-level Python, with experience in MLflow and Spark"
- **THEN** separate required skills are suggested for Python, MLflow and Spark, each quoting text from that line

#### Scenario: Skill from a duty
- **WHEN** a required duty line reads "Integrate AI agents into the SDLC workflow via AWS Bedrock"
- **THEN** a required skill is suggested for AWS Bedrock, quoting "AWS Bedrock"

#### Scenario: Traits, industries and fragments are left out
- **WHEN** required lines read "Comfort with ambiguity", "Experience in fintech or insurance" and "Stay up to date on fraud trends and systems"
- **THEN** no skill is suggested for comfort with ambiguity, fintech, insurance, trends or systems

#### Scenario: Advanced degree named by level
- **WHEN** a preferred line reads "Master's or PhD in statistics or a related field"
- **THEN** one preferred skill `Master's degree` of kind qualification is suggested, and no skill is suggested for statistics as a field of study

#### Scenario: Higher importance wins
- **WHEN** a run verifies `AWS Bedrock` as required from a duty line and as preferred from a "nice to have" line
- **THEN** the run's suggestions include `AWS Bedrock` once, as required

#### Scenario: Same-importance duplicate
- **WHEN** a run verifies `Optimization` twice, both required
- **THEN** the run's suggestions include `Optimization` once, with the quote of the first

#### Scenario: Empty result is a failure
- **WHEN** segmentation finds four required lines and skill extraction returns no skills twice
- **THEN** the run is marked failed with an error saying no skills were extracted from the required lines

### Requirement: Validation against the text
Every suggested skill and salary range SHALL be checked against the snapshot's description. The check compares case-insensitively, with whitespace collapsed. A quote SHALL count as verified only if it occurs in the description text. A salary range SHALL count as verified only if its quote is verified and each of its amounts occurs in the quote, allowing written forms such as `175,000`, `175000` and `175k`. Unverified items SHALL be stored and flagged. They SHALL be hidden from default views, kept apart from verified items, and SHALL NOT be accepted until the user shows them.

A verified quote SHALL be stored at one occurrence in the description. When the model names the line an item came from, that line SHALL be searched first, then the whole description. Within each search, the first whole-word occurrence SHALL be used, and the first occurrence of any kind only when there is no whole-word one. An occurrence SHALL count as whole-word when it has no letter or digit directly before it if the quote starts with a letter or digit, and none directly after it if the quote ends with a letter or digit. Where a quote is stored SHALL NOT affect whether it counts as verified.

#### Scenario: Invented quote
- **WHEN** the model suggests skill `Kubernetes` with a quote that does not occur in the description
- **THEN** the suggestion is stored as unverified and is not shown among the posting's suggested skills by default

#### Scenario: Wrong amount
- **WHEN** a salary range has maximum 210000 but its quote says "$175,000 - $200,000"
- **THEN** the range is stored as unverified

#### Scenario: Short quote inside a longer word
- **WHEN** the model suggests `CI` quoting "CI" from the line "Specific tooling: Git, CI, containers"
- **THEN** the suggestion is verified and stored at "CI", not inside "Specific"

#### Scenario: Quote next to punctuation
- **WHEN** the model suggests `C#` quoting "C#" from the line "Strong C#/.NET skills"
- **THEN** the suggestion is verified and stored at "C#"

#### Scenario: Partial-word quote still verifies
- **WHEN** the model quotes "Kubernete" and the description says "Kubernetes" but never "Kubernete" as a whole word
- **THEN** the suggestion is verified and stored at the start of "Kubernetes"

#### Scenario: Source line comes first
- **WHEN** the model quotes "Python" from the second line, and "Python" occurs as a whole word on both the first and second lines
- **THEN** the suggestion is stored at the occurrence on the second line

### Requirement: Derived data is stored separately and never edited
Each run SHALL be stored as derived data, keyed by posting, snapshot, model and pipeline version, with its creation time, its status (succeeded or failed), any error, and each step's output. Each run SHALL also record what made it: an **app run** is made by the job queue, and an **eval run** by `jobhunt eval`. Runs SHALL NOT be edited or overwritten, and an eval run SHALL NOT become an app run. Extracting again SHALL add a new run. Re-capturing a posting SHALL NOT change or delete runs. Extraction SHALL NOT write captured data or user-authored data.

Runs stored before runs recorded what made them SHALL be app runs when a posting extraction job stored them, and eval runs otherwise.

The web interface SHALL use app runs only: for a posting's skills, the "Model says" panel, accepting suggestions, the salary in the posting list and the bulk-extraction count. Only `jobhunt eval` SHALL read eval runs.

#### Scenario: Re-extraction keeps history
- **WHEN** a posting is extracted twice with different models
- **THEN** both runs are stored, and the earlier run's results are unchanged

#### Scenario: Re-capture after extraction
- **WHEN** an extracted posting is re-captured with a changed description
- **THEN** the earlier run is kept and is labelled as made on an older snapshot

#### Scenario: Eval run stays out of the app
- **WHEN** a posting has an app run with `atomic@2`, and `jobhunt eval --skills atomic@5` later stores a newer successful run on the same snapshot
- **THEN** the posting's skills, its "Model says" panel and its salary in the posting list still come from the `atomic@2` app run

#### Scenario: Classifying runs stored before
- **WHEN** the database is upgraded with 78 stored runs, 33 of which a posting extraction job points at
- **THEN** those 33 are app runs and the other 45 are eval runs

### Requirement: Requesting extraction
The posting detail page SHALL offer an action to queue extraction of the posting's latest snapshot with the selected model and segmentation method and the app's skill extraction method. The posting list SHALL offer an action to queue extraction for every listed, non-dismissed posting that has no successful app run for its latest snapshot with the current model and pipeline. An eval run SHALL NOT count as an extraction for this. Before the user confirms, the action SHALL state how many postings it will queue. Queuing a posting that already has a queued or running job SHALL NOT add a second job.

#### Scenario: Bulk extraction
- **WHEN** the list shows 28 postings, 3 dismissed and 5 already extracted with the current settings, and the user starts bulk extraction
- **THEN** the action says it will queue 20 postings and, once confirmed, queues 20 jobs

#### Scenario: Double request
- **WHEN** the user clicks extract twice on a posting whose job is still queued
- **THEN** only one job is queued for that posting

#### Scenario: Extraction with the chosen skill method
- **WHEN** a candidate `atomic@5` is registered and the user extracts a posting
- **THEN** the stored run's pipeline id contains `skills=atomic@2`, the method the code names for the app

#### Scenario: Eval run doesn't count as extracted
- **WHEN** a listed posting's only successful run on its latest snapshot is an eval run with the current model and pipeline
- **THEN** bulk extraction counts the posting and queues it

### Requirement: Model output on the posting page
The posting detail page SHALL show the "Model says" panel when the posting has at least one app run. The panel SHALL be styled as model-derived data, distinct from captured and user-authored data. It SHALL show the latest app run, and the user SHALL be able to switch to any earlier app run of the posting. Eval runs SHALL NOT be shown or selectable. For the shown run it SHALL display:
- model, pipeline version and time
- verified salary ranges
- verified required skills and verified preferred skills, each with its quote
- a control to show unverified items
- when the run is for an older snapshot, a label saying so and an action to extract the current snapshot
- for a failed run, the error

Model output SHALL be shown as plain text and never interpreted as markup.

#### Scenario: Viewing suggestions
- **WHEN** the user opens a posting with a successful app run on its latest snapshot
- **THEN** the panel shows the model name, salary ranges, and required and preferred skills with their quotes

#### Scenario: Only eval runs
- **WHEN** a posting's only runs are eval runs
- **THEN** the posting page shows no "Model says" panel, and still offers to extract the posting

#### Scenario: Markup in model output
- **WHEN** a suggested skill name is `<b>Go</b>`
- **THEN** the page shows the text `<b>Go</b>` literally

### Requirement: Accepting and rejecting suggestions
For an app run on the posting's latest snapshot, the user SHALL be able to accept a verified skill suggestion. Accepting SHALL create a skill mark with the suggestion's skill name, quote and importance, and an origin showing it came from a suggestion. Skill names SHALL be matched to existing skills case-insensitively. The user SHALL be able to accept all verified suggestions in one group (required or preferred) with one action. A suggestion whose skill the posting already marks SHALL be shown as already marked and SHALL NOT be accepted again.

The user SHALL be able to reject a suggestion, giving one of two reasons:
- **not a skill:** the suggestion is not a skill by the user's definition
- **not for me:** it is a skill, but not one the user wants marked

A rejected skill SHALL be hidden for that posting in every run, including later ones, until the user undoes the rejection. Shown rejected suggestions SHALL display their reason, or say that none was given for rejections made before reasons existed. The user SHALL be able to set or change the reason of a rejected suggestion without undoing it. The reason SHALL be stored with the rejection as user-authored data. Suggestions from runs on older snapshots, and suggestions from eval runs, SHALL NOT be acceptable. Marks accepted from any run, and rejections, SHALL be kept when the run they came from is no longer used by the app.

#### Scenario: Accepting a required skill
- **WHEN** the user accepts the required suggestion `MLflow` quoting "MLflow for experiment tracking"
- **THEN** the posting has a skill mark for `MLflow` with that quote, importance required and origin suggestion, and the suggestion shows as already marked

#### Scenario: Rejection survives re-extraction
- **WHEN** the user rejects suggestion `Communication` on a posting and later extracts the posting again
- **THEN** the new run's `Communication` suggestion is hidden as rejected, and the user can show and undo it

#### Scenario: Rejecting with a reason
- **WHEN** the user rejects `Refactoring` as not a skill and `Cursor` as not for me
- **THEN** both are hidden as rejected, and when shown, `Refactoring` says "not a skill" and `Cursor` says "not for me"

#### Scenario: Reason added to an earlier rejection
- **WHEN** a suggestion `Ray` was rejected before reasons existed, and the user shows rejected suggestions and sets its reason to not for me
- **THEN** `Ray` stays rejected, and its reason is now not for me

#### Scenario: Eval run not acceptable
- **WHEN** an accept request names a suggestion from an eval run on the posting's latest snapshot
- **THEN** no mark is created and the response says the run is not one the app uses

#### Scenario: Marks from a run the app no longer uses
- **WHEN** a posting has 15 marks accepted from an `atomic@4` run, which became an eval run on upgrade
- **THEN** the 15 marks are still the posting's marks, with origin suggestion

### Requirement: Salary in the posting list
The posting list SHALL show, for each posting, a short summary of the first verified salary range from the latest successful app run on the posting's latest snapshot. The summary SHALL be styled as model-derived data, and SHALL say how many more ranges exist when there are several. Postings without such a run SHALL show no salary.

#### Scenario: Salary column
- **WHEN** a posting's latest app run has verified ranges 175000–200000 USD per year and 110000–130000 CAD per year
- **THEN** its list row shows "$175k–200k/yr" marked as model output, with "+1 more"

#### Scenario: Salary from an eval run
- **WHEN** a posting's only successful run on its latest snapshot is an eval run with a verified range
- **THEN** its list row shows no salary
