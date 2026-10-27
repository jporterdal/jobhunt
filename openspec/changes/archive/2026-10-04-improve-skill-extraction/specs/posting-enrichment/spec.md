## MODIFIED Requirements

### Requirement: Step-wise extraction with replaceable steps
Extraction SHALL run as separate steps:
- **Segmentation:** labels spans of the description as required, preferred or other. A span describing the hire's work, whether a duty bullet or prose about the role, SHALL count as required, unless it states that something is a plus or preferred. Spans about the company, team, product, benefits, pay or legal matters, and headings, SHALL count as other.
- **Skill extraction:** runs on the required and preferred spans.
- **Salary extraction:** runs on lines that mention pay.
- **Validation:** checks the results.

A span SHALL be identified by its start and end position in the snapshot's description text, never by rewritten text. Each step SHALL have a name and a version. A run SHALL record the model and every step's name and version. Replacing one step's method SHALL NOT require changes to the other steps or to stored results of earlier runs. The system SHALL provide at least two segmentation methods: one based on rules that needs no model, and one that uses the model to classify lines. The rule-based method SHALL treat a heading that introduces duties (for example "Responsibilities" or "What you'll do") as starting a required section.

#### Scenario: Run identifies its steps
- **WHEN** a posting is extracted with model `gemma4:12b` and the line-classifier segmenter
- **THEN** the stored run names the model and the name and version of the segmenter, skill extractor, salary extractor and validator

#### Scenario: Switching segmenter
- **WHEN** the user switches the segmentation method to rule-based and extracts a posting extracted earlier with the line classifier
- **THEN** a new run is stored next to the earlier one, and both remain viewable

#### Scenario: Duty line is required
- **WHEN** a line under "Key Responsibilities" reads "Lead the supervised fine-tuning work, including building task-specific datasets"
- **THEN** the line is segmented as required, and skill extraction runs on it

#### Scenario: Company description is other
- **WHEN** a line reads "Example Labs maintains one of the largest collections of anonymised retail transactions in the region"
- **THEN** the line is segmented as other

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
