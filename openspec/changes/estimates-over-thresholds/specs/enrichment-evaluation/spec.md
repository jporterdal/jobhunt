## MODIFIED Requirements

### Requirement: Holdout share setting
The settings page SHALL let the user set the holdout share r, the share of labelled postings the draw aims for in holdout, from 0.1 to 0.9, defaulting to 0.5. It SHALL be stored as user-authored data and survive restarts. Values outside the range SHALL be refused. Changing the share SHALL NOT move any posting: it affects only later draws. The settings page SHALL show the number of labelled postings in each set, and SHALL explain beside the share when to change it:
- raise it when new dev postings fail in ways already seen, so more labels go where decisions are made;
- lower it for a while when starting a round of prompt work with fewer than about 8 dev postings;
- raise it when method comparisons on holdout keep giving differences too imprecise to tell methods apart, since holdout is then too small;
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
