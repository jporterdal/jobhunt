## MODIFIED Requirements

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
