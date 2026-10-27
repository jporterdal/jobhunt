## MODIFIED Requirements

### Requirement: Validation against the text
Every suggested skill and salary range SHALL be checked against the snapshot's description. The check compares case-insensitively, with whitespace collapsed. A quote SHALL count as verified only if it occurs in the description text. A salary range SHALL count as verified only if its quote is verified and each of its amounts occurs in the quote, allowing written forms such as `175,000`, `175000` and `175k`. Unverified items SHALL be stored and flagged. They SHALL be hidden from default views, kept apart from verified items, and SHALL NOT be accepted until the user shows them.

A verified quote SHALL be stored at one occurrence in the description. When the model names the line an item came from, that line SHALL be searched first, then the whole description. Within each search, the first whole-word occurrence SHALL be used, and the first occurrence of any kind only when there is no whole-word one. An occurrence SHALL count as whole-word when it has no letter or digit directly before it if the quote starts with a letter or digit, and none directly after it if the quote ends with a letter or digit. Where a quote is stored SHALL NOT affect whether it counts as verified.

#### Scenario: Invented quote
- **WHEN** the model suggests skill `Kubernetes` with a quote that does not occur in the description
- **THEN** the suggestion is stored as unverified and is not shown among the posting's suggested skills by default

#### Scenario: Wrong amount
- **WHEN** a salary range has maximum 210000 but its quote says "$175,000 - $200,000"
- **THEN** the range is stored as unverified

#### Scenario: Short quote inside a longer word
- **WHEN** the model suggests `CI` quoting "CI" from the line "Specific tooling: Git, CI, containers"
- **THEN** the suggestion is verified and stored at "CI", not inside "Specific"

#### Scenario: Quote next to punctuation
- **WHEN** the model suggests `C#` quoting "C#" from the line "Strong C#/.NET skills"
- **THEN** the suggestion is verified and stored at "C#"

#### Scenario: Partial-word quote still verifies
- **WHEN** the model quotes "Kubernete" and the description says "Kubernetes" but never "Kubernete" as a whole word
- **THEN** the suggestion is verified and stored at the start of "Kubernetes"

#### Scenario: Source line comes first
- **WHEN** the model quotes "Python" from the second line, and "Python" occurs as a whole word on both the first and second lines
- **THEN** the suggestion is stored at the occurrence on the second line
