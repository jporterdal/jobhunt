## MODIFIED Requirements

### Requirement: Step-wise extraction with replaceable steps
Extraction SHALL run as separate steps:
- **Segmentation:** labels spans of the description as required, preferred or other. A span describing the hire's work, whether a duty bullet or prose about the role, SHALL count as required, unless it states that something is a plus or preferred. Spans about the company, team, product, benefits, pay or legal matters, and headings, SHALL count as other.
- **Skill extraction:** runs on the required and preferred spans.
- **Salary extraction:** runs on lines that mention pay.
- **Validation:** checks the results.

A span SHALL be identified by its start and end position in the snapshot's description text, never by rewritten text. Each step SHALL have a name and a version. A run SHALL record the model and every step's name and version. Replacing one step's method SHALL NOT require changes to the other steps or to stored results of earlier runs. The system SHALL provide at least two segmentation methods: one based on rules that needs no model, and one that uses the model to classify lines. The rule-based method SHALL treat a heading that introduces duties (for example "Responsibilities" or "What you'll do") as starting a required section.

The system SHALL provide at least two skill extraction methods, identified by name and version: `atomic@2` (the default, see "Required and preferred skills") and `atomic@4` (see "Stricter skill extraction"). Two versions of one method SHALL be able to exist side by side, so that a run made with either keeps its pipeline id and can be reused and compared later.
#### Scenario: Run identifies its steps
- **WHEN** a posting is extracted with model `gemma4:12b` and the line-classifier segmenter
- **THEN** the stored run names the model and the name and version of the segmenter, skill extractor, salary extractor and validator

#### Scenario: Switching segmenter
- **WHEN** the user switches the segmentation method to rule-based and extracts a posting extracted earlier with the line classifier
- **THEN** a new run is stored next to the earlier one, and both remain viewable

#### Scenario: Two versions of a skill extractor side by side
- **WHEN** a posting has stored runs with `skills=atomic@2` and `skills=atomic@4` in their pipeline ids, and a queued job names either pipeline id
- **THEN** both runs remain viewable, the job runs with the method its pipeline id names, and new extractions requested from the posting page use `atomic@2`

#### Scenario: Duty line is required
- **WHEN** a line under "Key Responsibilities" reads "Lead the supervised fine-tuning work, including building task-specific datasets"
- **THEN** the line is segmented as required, and skill extraction runs on it

#### Scenario: Company description is other
- **WHEN** a line reads "Example Labs maintains one of the largest collections of anonymised retail transactions in the region"
- **THEN** the line is segmented as other

## ADDED Requirements

### Requirement: Stricter skill extraction
The `atomic@4` skill extraction method SHALL work like the default method (the same groups, importance from the span, splitting of lists, degree levels, output fields, merge of duplicates, and the retry and failure on an empty group), except for what it asks the model to list. It SHALL ask for only skills a span names, and SHALL NOT ask the model to work out skills from what a span says the job involves. Its request SHALL define a skill as expertise a hiring team would screen for, and SHALL state:
- that a specialised practice or discipline the span names counts even when the span words it as work
- that a soft skill counts only when the span asks for it as an ability
- the default method's exclusions, with fields of study narrowed to those named as part of a degree
- these further exclusions: everyday activities that any engineer in the role does, basics that any software engineer has or can learn quickly, team practices a new hire adopts, vague terms that name no particular expertise, kinds of data or records, kinds of past job, and the label that opens a line before a colon
- that an excluded item leaves out only its own words, not other skills named in the same span

Its retry request SHALL NOT tell the model that the lines describe work that uses a skill. Examples in its request SHALL NOT name a skill the user has marked.

Whether the model follows these instructions is measured by `jobhunt eval`, not guaranteed by this requirement.

#### Scenario: Stricter request
- **WHEN** a posting is extracted with `atomic@4`
- **THEN** each skill request states the screening bar, the further exclusions and the leave-out-only-the-excluded-words rule, and does not offer stakeholder management as an example

#### Scenario: Default request unchanged
- **WHEN** a posting is extracted with the default method
- **THEN** the skill request is the `atomic@2` request, and the run's pipeline id contains `skills=atomic@2`
