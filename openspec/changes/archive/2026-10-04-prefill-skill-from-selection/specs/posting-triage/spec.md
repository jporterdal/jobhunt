## MODIFIED Requirements

### Requirement: Skills marked from description text
On a posting's detail page, the user SHALL be able to select text in the description and assign it to a skill, either an existing one or a new one. The system SHALL record that the posting asks for that skill, together with the selected text. When the user selects text, the skill name SHALL be pre-filled with the selected text, with surrounding whitespace trimmed and inner runs of whitespace collapsed to single spaces but otherwise exactly as written, and the user SHALL be able to edit it before marking. Selecting different text while the mark form is open SHALL replace the pre-filled name, unless the user has typed in it. When marking, the user SHALL be able to choose the skill's importance for the posting (required or preferred), or leave it unspecified, and SHALL be able to change it later. Each mark SHALL record its origin: a selection by the user, or an accepted model suggestion. Skill names SHALL be trimmed and compared case-insensitively. The user SHALL be able to remove a mark. Marks SHALL be shown highlighted in the description, with their importance. A mark whose quoted text no longer appears in the latest snapshot SHALL still be listed and labelled as not found in the current description.

#### Scenario: Marking a skill
- **WHEN** the user selects "experience with PyTorch" and assigns it to new skill `PyTorch`
- **THEN** skill `PyTorch` exists, the posting lists it with the quoted text, and the text is highlighted

#### Scenario: Marking with importance
- **WHEN** the user selects "Familiarity with Terraform is a plus" and assigns it to skill `Terraform` as preferred
- **THEN** the posting lists `Terraform` as preferred, with origin selection

#### Scenario: Changing importance
- **WHEN** the user changes the importance of an existing `PyTorch` mark from unspecified to required
- **THEN** the posting lists `PyTorch` as required, and its quote and origin are unchanged

#### Scenario: Marks from before importance existed
- **WHEN** the database is upgraded with existing skill marks
- **THEN** those marks have unspecified importance and origin selection

#### Scenario: Description changed
- **WHEN** a re-capture adds a snapshot whose description no longer contains a marked quote
- **THEN** the mark is still listed for the posting and labelled as not found in the current description

#### Scenario: Skill name pre-filled from the selection
- **WHEN** the user selects "  Python programming " in the description
- **THEN** the mark form opens with the skill name "Python programming"

#### Scenario: Accepting the pre-filled name
- **WHEN** the user selects "Python programming" and marks it without changing the name
- **THEN** skill `Python programming` exists and the posting lists it with the quoted text "Python programming"

#### Scenario: Editing the pre-filled name
- **WHEN** the user selects "experience with PyTorch", changes the name to `PyTorch` and marks it
- **THEN** skill `PyTorch` exists and the posting lists it with the quoted text "experience with PyTorch"

#### Scenario: Pre-filled name matches an existing skill
- **WHEN** skill `Python` exists and the user selects "python" and marks it without changing the name
- **THEN** the mark is assigned to the existing skill `Python` and no new skill is created

#### Scenario: Selection spanning a line break
- **WHEN** the user selects text that reads "Python" and "programming" on two lines
- **THEN** the mark form opens with the skill name "Python programming"

#### Scenario: Reselecting while the form is open
- **WHEN** the mark form is open with the pre-filled name "Python programming", and the user selects "Go" without having typed in the name
- **THEN** the skill name becomes "Go"

#### Scenario: Typed name is kept on reselect
- **WHEN** the user has typed `Python` into the skill name and then selects different description text
- **THEN** the skill name stays `Python` and only the quoted text changes
