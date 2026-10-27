## MODIFIED Requirements

### Requirement: Skills a posting has
A posting's skills SHALL be:
- its skill marks, with their importance and quote
- plus the verified suggestions from its latest successful app run on its latest snapshot (see "Derived data is stored separately and never edited" in `posting-enrichment`), except suggestions the user rejected for that posting, for any reason.

When a mark and a suggestion name the same skill, the mark SHALL be used. A posting skill SHALL be identified by its name, trimmed, case-insensitively and with whitespace collapsed. Posting skills from runs on older snapshots SHALL NOT be used, and neither SHALL posting skills from eval runs.

#### Scenario: Marks and suggestions combined
- **WHEN** a posting has the mark `Python` (required), and its latest run on the latest snapshot suggests `python` (preferred), `Docker` and `Kubernetes`, of which `Kubernetes` was rejected as not for me
- **THEN** the posting's skills are `Python` (required, from the mark) and `Docker`

#### Scenario: Unverified suggestion left out
- **WHEN** the latest run has an unverified suggestion `Terraform`
- **THEN** `Terraform` is not one of the posting's skills

#### Scenario: Eval run left out
- **WHEN** a labelled posting has 26 marks, no app run, and an eval run that suggests `Prompt engineering`, which no mark names
- **THEN** the posting's skills are its 26 marks, `Prompt engineering` is not among them, and link judging doesn't consider it for this posting
