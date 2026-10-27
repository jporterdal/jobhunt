## MODIFIED Requirements

### Requirement: Posting recommendations
The system SHALL rank postings by match score times an interest factor: the user's interest rating divided by 3, with an unrated posting counting as 3. Ties SHALL be broken by last seen, newest first. Postings that are dismissed, that have an application, or that have no score SHALL be left out; the number left out for having no skills SHALL be stated. The top 20 SHALL be shown, each with its title, company, workplace type (`On-site`, `Hybrid` or `Remote`, or a dash when the posting has none), score, the number of its skills without a link, up to three gaps (the skills that lose the most weighted credit, required first), a link to its detail page and its original-posting link.

#### Scenario: Interest lifts a posting
- **WHEN** posting A scores 50% with interest 5 and posting B scores 60% unrated
- **THEN** A is ranked above B (0.83 against 0.60)

#### Scenario: Dismissed and applied postings
- **WHEN** a posting is dismissed, or has an application
- **THEN** it is not among the recommended postings

#### Scenario: Workplace type shown
- **WHEN** a recommended posting's latest snapshot has workplace type `Hybrid`, and another has none
- **THEN** the first posting's row shows `Hybrid` and the second's shows a dash

## ADDED Requirements

### Requirement: Workplace filter
Insights SHALL offer a workplace filter with one choice per workplace type (`On-site`, `Hybrid`, `Remote`), all chosen by default. The filter SHALL narrow the postings that recommendations consider, by each posting's latest snapshot, so it applies to both lists:
- posting recommendations, including the number of postings considered and the number left out for having no skills;
- skill recommendations, whose gains are summed over the postings considered.

Choosing every type, or none, SHALL mean no filter, and postings without a workplace type SHALL then be considered. When only some types are chosen, only postings of those types SHALL be considered; postings without a workplace type SHALL be left out.

The chosen types SHALL be encoded in the page URL, so reloading or bookmarking it reproduces the same recommendations. Unknown values SHALL be ignored. The filter SHALL NOT be stored. After the user answers a recommended skill or changes a level on Insights, the recommendations SHALL be shown again under the same filter.

When the filter leaves no posting to consider, both lists SHALL say that no posting of the chosen workplace types is left to recommend, rather than their usual empty messages.

#### Scenario: Default is every posting
- **WHEN** the user opens Insights without choosing any workplace type, and a considered posting has no workplace type
- **THEN** recommendations are the same as with every type chosen, and that posting is considered

#### Scenario: Remote and hybrid only
- **WHEN** the user unchooses `On-site`, and an `On-site` posting is the only one asking for `Kubernetes` (no link)
- **THEN** that posting is not among the recommended postings and is not counted as considered, `Kubernetes` is not a recommended skill, and the URL carries `Hybrid` and `Remote`

#### Scenario: Skill gain from filtered postings only
- **WHEN** `AWS` (no link) would raise one unrated `Remote` posting by 0.3 and one unrated `On-site` posting by 0.4, and only `Remote` is chosen
- **THEN** `AWS`'s gain is +30, improving 1 posting

#### Scenario: Posting without a workplace type
- **WHEN** a posting has no workplace type and only `Remote` is chosen
- **THEN** the posting is not considered

#### Scenario: Unknown value
- **WHEN** the URL's workplace values are `Remote` and `Moon`
- **THEN** only `Remote` is chosen; and when its only value is `Moon`, there is no filter

#### Scenario: Filter kept after an answer
- **WHEN** only `Remote` is chosen and the user answers "don't have it" for `AWS`
- **THEN** the recommendations shown next are computed with `AWS` at `missing` and only `Remote` chosen

#### Scenario: Nothing of the chosen types
- **WHEN** only `On-site` is chosen and every `On-site` posting is dismissed
- **THEN** both lists say no posting of the chosen workplace types is left to recommend
