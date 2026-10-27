## Purpose

The user's own judgments about each posting: how interesting it is, how well it fits, why it was dismissed, and which skills it asks for. This data drives triage now and preference analysis later.

## ADDED Requirements

### Requirement: Interest and fit ratings
The user SHALL be able to give each posting an interest rating and a fit rating, each an integer from 1 to 5. Either rating SHALL be clearable. A change SHALL be saved as soon as it is made, without a separate save step. A rating SHALL be stored only when the user sets it, never by default.

#### Scenario: Rating a posting
- **WHEN** the user sets interest to 4 on a posting and reloads the page
- **THEN** the posting shows interest 4 and fit unset

#### Scenario: Clearing a rating
- **WHEN** the user clears the interest rating
- **THEN** the posting shows no interest rating and appears under the "unrated" filter

### Requirement: Tags
The user SHALL be able to add free-form tags to a posting and remove them. Tags SHALL be trimmed and compared case-insensitively: adding "ML" where "ml" already exists SHALL reuse the existing tag. While typing, the interface SHALL suggest existing tags. A posting SHALL NOT carry the same tag twice.

#### Scenario: Reusing a tag
- **WHEN** tag `ml` exists and the user adds ` ML ` to another posting
- **THEN** that posting is tagged with the existing `ml` tag and no new tag is created

### Requirement: Notes
The user SHALL be able to write markdown notes on a posting. Notes SHALL be shown rendered as markdown, with any raw HTML in them shown as text rather than interpreted.

#### Scenario: Markdown note
- **WHEN** the user saves the note `**Ask** about <b>visa</b>`
- **THEN** "Ask" is shown in bold and `<b>visa</b>` is shown literally

### Requirement: Dismissal with reasons
The user SHALL be able to dismiss a posting with one or more reasons and an optional free-text comment. Reasons SHALL come from a list the user can add to, which starts with: too senior, too junior, location or on-site, compensation, wrong domain, skills mismatch, company, and other. The user SHALL be able to restore a dismissed posting. Restoring SHALL keep the earlier dismissal, its reasons and its time in the posting's history.

#### Scenario: Dismissing
- **WHEN** the user dismisses a posting with reasons "too senior" and "location or on-site"
- **THEN** the posting is hidden from the default list, appears under the "dismissed" filter, and its detail page shows both reasons

#### Scenario: Restoring
- **WHEN** the user restores that posting and later dismisses it again for "compensation"
- **THEN** the posting is dismissed, and its history shows both dismissals with their reasons and the restore between them

### Requirement: Skills marked from description text
On a posting's detail page, the user SHALL be able to select text in the description and assign it to a skill, either an existing one or a new one. The system SHALL record that the posting asks for that skill, together with the selected text. Skill names SHALL be trimmed and compared case-insensitively. The user SHALL be able to remove a mark. Marks SHALL be shown highlighted in the description. A mark whose quoted text no longer appears in the latest snapshot SHALL still be listed and labelled as not found in the current description.

#### Scenario: Marking a skill
- **WHEN** the user selects "experience with PyTorch" and assigns it to new skill `PyTorch`
- **THEN** skill `PyTorch` exists, the posting lists it with the quoted text, and the text is highlighted

#### Scenario: Description changed
- **WHEN** a re-capture adds a snapshot whose description no longer contains a marked quote
- **THEN** the mark is still listed for the posting and labelled as not found in the current description

### Requirement: Skill self-assessment
For each skill, the user SHALL be able to record their own level as `have`, `missing` or `learning`, or leave it unset. The level SHALL belong to the skill, not to a posting, and SHALL be shown wherever the skill is marked. A skills page SHALL list every skill with its level, the number of postings that ask for it, and how many of those postings the user rated 4 or more for interest.

#### Scenario: Setting a level
- **WHEN** the user sets `Kubernetes` to `missing` on one posting's detail page
- **THEN** every posting that marks Kubernetes shows it as missing

#### Scenario: Skills page
- **WHEN** three postings mark `PyTorch` and two of them have interest 4 or more
- **THEN** the skills page shows `PyTorch` with 3 postings, 2 of them high-interest

### Requirement: Triage data is user-authored
Ratings, tags, notes, dismissals, skill marks and skill levels SHALL be stored as user-authored data keyed by job ID (skills by their own identity). Re-capturing a posting SHALL leave them unchanged.

#### Scenario: Re-capture after triage
- **WHEN** a rated, tagged posting is re-captured with a changed description
- **THEN** its ratings, tags, notes and skill marks are unchanged
