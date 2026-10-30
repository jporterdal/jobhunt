# posting-triage Specification

## Purpose

The user's own judgments about each posting: how interesting it is, how well it fits, why it was dismissed, and which skills it asks for. This data drives triage now and preference analysis later.

## Requirements

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

### Requirement: Skill self-assessment
For each skill, the user SHALL be able to record their own level as `missing`, `learning`, `familiar`, `proficient` or `expert`, or leave it unset. The levels SHALL form an ordered scale in that order. The level SHALL belong to the skill's claim (see "Claims and levels" in `skill-profile`), not to a posting, and SHALL be shown wherever the skill is marked. For a skill that is an alias of another, the level SHALL be that of the other skill's claim, and setting it SHALL set the other skill's claim. Setting a level from a posting or the skills page SHALL create the claim when the skill has none, adding the skill to the profile, and clearing it SHALL remove the claim, removing the skill from the profile. A skills page SHALL list every skill with its level, whether it is in the profile, the number of postings that ask for it, and how many of those postings the user rated 4 or more for interest.

#### Scenario: Setting a level
- **WHEN** the user sets `Kubernetes` to `missing` on one posting's detail page
- **THEN** every posting that marks Kubernetes shows it as missing, and `Kubernetes` has a claim at `missing`

#### Scenario: Level of an alias
- **WHEN** `Postgres` is an alias of `PostgreSQL`, whose claim is at `proficient`
- **THEN** a posting that marks `Postgres` shows it at `proficient`

#### Scenario: Skills page
- **WHEN** three postings mark `PyTorch` and two of them have interest 4 or more
- **THEN** the skills page shows `PyTorch` with 3 postings, 2 of them high-interest

#### Scenario: Old level values
- **WHEN** a database holds skills with the level `have` from before this change
- **THEN** after migration those skills are at `proficient`

### Requirement: User-authored triage data
Ratings, tags, notes, dismissals, skill marks (with their importance and origin), skill levels, the skill-labelling-complete flag and rejected model suggestions SHALL be stored as user-authored data keyed by the posting's key (skills by their own identity). Re-capturing a posting SHALL leave them unchanged. Extracting a posting with a model SHALL leave them unchanged, except when the user explicitly accepts or rejects a suggestion. Accepting a document suggestion SHALL change skill levels only as "Offered suggestions" in `profile-extraction` allows, and SHALL never change a level the user set.

#### Scenario: Re-capture after triage
- **WHEN** a rated, tagged posting is re-captured with a changed description
- **THEN** its ratings, tags, notes and skill marks are unchanged

#### Scenario: Extraction after triage
- **WHEN** a posting with skill marks and a rejected suggestion is extracted again
- **THEN** its marks, importances and rejections are unchanged

#### Scenario: Document suggestion after triage
- **WHEN** the user set `Kubernetes` to `missing` and a document run suggests `Kubernetes` at `familiar`
- **THEN** no change to `Kubernetes`'s level is offered, and it stays at `missing`

### Requirement: Skill labelling complete
The user SHALL be able to flag that they have marked all the skills a posting asks for, and to clear the flag. The flag SHALL record when it was set. The posting detail page SHALL show the flag. The posting list SHALL offer a filter for labelled and unlabelled postings, encoded in the page URL like the other filters.

When the posting is not yet in an evaluation set, the flag control SHALL offer the set choice Auto (the default), Dev or Holdout (see "Choosing a posting's set by hand" in `enrichment-evaluation`). Once the posting is in a set, the detail page SHALL show its set beside the flag, and, for a holdout posting, a control to move it to dev.

#### Scenario: Flagging a posting
- **WHEN** the user marks five skills on a posting and flags its labelling complete, leaving the set choice at Auto
- **THEN** the detail page shows labelling complete with the time and the posting's drawn set, and the posting appears under the "labelled" filter

#### Scenario: Clearing the flag
- **WHEN** the user clears the flag
- **THEN** the posting no longer appears under the "labelled" filter, and its marks and its set are unchanged

#### Scenario: Flagging again
- **WHEN** the user flags a holdout posting complete again after clearing it
- **THEN** no set choice is offered, and the detail page shows the posting as holdout with a control to move it to dev

### Requirement: Skills asked for panel
The posting detail page SHALL list the posting's skill marks in a "Skills asked for" panel. The panel's heading SHALL show the number of marks and, when the flag is set, that labelling is complete. Under the heading, the panel SHALL show a short description of four sentences saying that:
- it lists the user's marks on this posting (text they selected, or model suggestions they accepted);
- suggestions not yet accepted are in "Model says", below the description, where they can be accepted or rejected;
- importance applies to this posting only;
- level is the user's level for the skill under this name wherever it is marked, setting it adds that skill to the profile and clearing it removes it, and the level of a linked profile skill is changed from the skill summary's link to the profile page.

The heading and description SHALL always be visible. The marks with their controls (importance, level, remove) and the labelling-complete control SHALL be in a section that is collapsed each time the page loads, and that the user can expand and collapse. Changing something in the expanded section SHALL leave it expanded. Marks SHALL be highlighted in the description, and text SHALL be markable by selection, whether the section is expanded or not.

#### Scenario: Collapsed when the page loads
- **WHEN** the user opens a posting with 12 marks and labelling complete
- **THEN** the panel's heading reads "Skills asked for (12 marked · labelling complete)", its description is shown, and the marks and their controls are hidden until the user expands them

#### Scenario: Stays open while editing
- **WHEN** the user expands the section and changes a mark's importance
- **THEN** the change is saved and the section is still expanded

#### Scenario: Marking while collapsed
- **WHEN** the section is collapsed and the user selects "Terraform" in the description and marks it
- **THEN** `Terraform` is highlighted in the description and the heading counts one more mark

#### Scenario: No marks
- **WHEN** a posting has no marks
- **THEN** the heading reads "Skills asked for (none marked)", and the collapsed section says to select text in the description to mark a skill
