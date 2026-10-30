## ADDED Requirements

### Requirement: Dev and holdout sets
Every labelled posting SHALL belong to one of two sets, **dev** or **holdout**. A posting's set SHALL be decided when its labelling is first flagged complete, either by a draw (see "Drawing a posting's set") or by the user's choice (see "Choosing a posting's set by hand"), and SHALL be stored as user-authored data with how it was decided: drawn, chosen, moved to dev, or allocated before random allocation. Clearing the complete flag and setting it again SHALL keep the posting's set and SHALL NOT draw again. Only the user's move to dev SHALL change a posting's set afterwards.

The report SHALL show its figures for dev postings, for holdout postings, and for both together, with the number of postings in each, whether or not either set is empty. When some holdout postings were not drawn, the report SHALL also show the figures for the drawn holdout postings alone, with their number. The JSON report SHALL give each posting's set and how it was decided. The comparison of several methods SHALL show the same sets, and SHALL name each posting's set in its list of mark differences.

Postings whose labelling was flagged complete before this rule existed, whether or not the flag is still set, SHALL keep the set the held-out start gave them: postings first flagged complete after a recorded held-out start SHALL be holdout, and every other such posting SHALL be dev, each marked as allocated before random allocation.

#### Scenario: Both sets reported
- **WHEN** 7 labelled postings are dev and 6 are holdout, all drawn
- **THEN** the report shows figures for 7 dev postings, 6 holdout postings and 13 together, and no separate drawn-only figures

#### Scenario: Re-flagging keeps the set
- **WHEN** the user clears the complete flag on a holdout posting, edits its marks, and flags it complete again
- **THEN** the posting is still holdout, and no draw is made

#### Scenario: Drawn holdout postings alone
- **WHEN** the holdout set has 6 postings, 5 drawn and 1 chosen by hand
- **THEN** the report shows figures for the 6 holdout postings and, beside them, for the 5 drawn holdout postings

#### Scenario: Upgrading with no held-out start
- **WHEN** the database is upgraded with 9 labelled postings and no held-out start recorded
- **THEN** the 9 postings are dev, marked as allocated before random allocation, and the holdout set is empty

#### Scenario: Upgrading with a held-out start
- **WHEN** the database is upgraded with a held-out start recorded, 9 postings first flagged complete before it and 2 after it
- **THEN** the 9 are dev and the 2 are holdout, all marked as allocated before random allocation

### Requirement: Drawing a posting's set
When the user flags a posting's labelling complete for the first time and leaves its set to be drawn, the system SHALL put it in the holdout set with probability P and in the dev set otherwise, where, with r the holdout share (see "Holdout share setting"), N the number of labelled postings already in a set and H the number of those in holdout, the shortfall is d = r·N − H and

P = 1 / (1 + ((1 − r) / r) · e^(−d))

So P SHALL equal r when the holdout set holds exactly its share, and the odds of holdout SHALL multiply by e for each posting holdout falls short of its share, and divide by e for each posting it is ahead. Balance SHALL count labelled postings, whatever their number of marks, and SHALL count postings whose set was chosen by hand, moved or allocated before random allocation like drawn ones. Each draw SHALL be independent of the posting's content and of earlier draws apart from these counts.

#### Scenario: Balanced sets
- **WHEN** the holdout share is 0.5 and 10 labelled postings are split 5 dev and 5 holdout
- **THEN** the next posting flagged complete is drawn into holdout with probability 0.5

#### Scenario: Holdout behind its share
- **WHEN** the holdout share is 0.5 and the 9 labelled postings are all dev
- **THEN** the next posting is drawn into holdout with probability 0.989

#### Scenario: Another share
- **WHEN** the holdout share is 0.3 and 10 labelled postings include 2 holdout postings
- **THEN** the next posting is drawn into holdout with probability 0.538

### Requirement: Choosing a posting's set by hand
When flagging a posting's labelling complete for the first time, the user SHALL be able to choose Auto (the default: draw the set), Dev or Holdout. A posting already in a set SHALL NOT offer the choice. The user SHALL be able to move a holdout posting to dev at any time, whether or not its labelling is currently flagged complete. The system SHALL refuse to move a dev posting to holdout, saying that prompts may have been tuned on it.

#### Scenario: Choosing holdout
- **WHEN** the user picks Holdout and flags a posting's labelling complete for the first time
- **THEN** the posting is holdout, marked as chosen, and no draw is made

#### Scenario: Moving to dev
- **WHEN** the user moves a holdout posting to dev
- **THEN** the posting is dev, marked as moved, and the next report counts it as dev

#### Scenario: Dev to holdout refused
- **WHEN** a request asks to move a dev posting to holdout
- **THEN** the posting stays dev and the user is told that prompts may have been tuned on it

### Requirement: Holdout share setting
The settings page SHALL let the user set the holdout share r, the share of labelled postings the draw aims for in holdout, from 0.1 to 0.9, defaulting to 0.5. It SHALL be stored as user-authored data and survive restarts. Values outside the range SHALL be refused. Changing the share SHALL NOT move any posting: it affects only later draws. The settings page SHALL show the number of labelled postings in each set, and SHALL explain beside the share when to change it:
- raise it when new dev postings fail in ways already seen, so more labels go where decisions are made;
- lower it for a while when starting a round of prompt work with fewer than about 8 dev postings;
- raise it when method comparisons keep coming out within noise, since holdout is then too small to tell methods apart;
- changing it moves no posting, and later draws move towards the new share.

#### Scenario: Default share
- **WHEN** the user has never set the holdout share
- **THEN** the settings page shows 0.5, the help text, and the number of dev and holdout postings

#### Scenario: Changing the share
- **WHEN** 9 postings are dev and 0 holdout and the user sets the share to 0.3
- **THEN** no posting changes set, and the next draw uses the share 0.3

#### Scenario: Out of range
- **WHEN** a request sets the holdout share to 0.95
- **THEN** the share is unchanged and the page says it must be from 0.1 to 0.9

## REMOVED Requirements

### Requirement: Development and held-out postings
**Reason**: A time-based split freezes the development set at the start and groups postings by when they were labelled. Each posting's set is now drawn when its labelling is first flagged complete.
**Migration**: Upgrading keeps every labelled posting's set (see "Dev and holdout sets"). The held-out start, its settings controls and `POST /settings/holdout` are removed; use the holdout share and "Choosing a posting's set by hand" instead. JSON consumers read `sets.dev` and `sets.holdout` in place of `sets.development` and `sets.held_out`, and no longer get `holdout_start`.
