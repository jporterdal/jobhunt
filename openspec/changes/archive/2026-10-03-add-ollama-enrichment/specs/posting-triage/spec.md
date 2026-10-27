## MODIFIED Requirements

### Requirement: Skills marked from description text
On a posting's detail page, the user SHALL be able to select text in the description and assign it to a skill, either an existing one or a new one. The system SHALL record that the posting asks for that skill, together with the selected text. When marking, the user SHALL be able to choose the skill's importance for the posting (required or preferred), or leave it unspecified, and SHALL be able to change it later. Each mark SHALL record its origin: a selection by the user, or an accepted model suggestion. Skill names SHALL be trimmed and compared case-insensitively. The user SHALL be able to remove a mark. Marks SHALL be shown highlighted in the description, with their importance. A mark whose quoted text no longer appears in the latest snapshot SHALL still be listed and labelled as not found in the current description.

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

### Requirement: Triage data is user-authored
Ratings, tags, notes, dismissals, skill marks (with their importance and origin), skill levels, the skill-labelling-complete flag and rejected model suggestions SHALL be stored as user-authored data keyed by job ID (skills by their own identity). Re-capturing a posting SHALL leave them unchanged. Extracting a posting with a model SHALL leave them unchanged, except when the user explicitly accepts or rejects a suggestion.

#### Scenario: Re-capture after triage
- **WHEN** a rated, tagged posting is re-captured with a changed description
- **THEN** its ratings, tags, notes and skill marks are unchanged

#### Scenario: Extraction after triage
- **WHEN** a posting with skill marks and a rejected suggestion is extracted again
- **THEN** its marks, importances and rejections are unchanged

## ADDED Requirements

### Requirement: Skill labelling complete
The user SHALL be able to flag that they have marked all the skills a posting asks for, and to clear the flag. The flag SHALL record when it was set. The posting detail page SHALL show the flag. The posting list SHALL offer a filter for labelled and unlabelled postings, encoded in the page URL like the other filters.

#### Scenario: Flagging a posting
- **WHEN** the user marks five skills on a posting and flags its labelling complete
- **THEN** the detail page shows labelling complete with the time, and the posting appears under the "labelled" filter

#### Scenario: Clearing the flag
- **WHEN** the user clears the flag
- **THEN** the posting no longer appears under the "labelled" filter, and its marks are unchanged
