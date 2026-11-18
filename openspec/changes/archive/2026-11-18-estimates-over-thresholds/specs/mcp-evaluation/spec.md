## ADDED Requirements

### Requirement: Comparing code versions
Comparing two stages of the same question set (two code versions, the same model, kind, history condition, order and sample counts) SHALL give, for each question: the pass counts of both; the observed direction, `more` when the second stage passed more samples, `fewer` when it passed fewer and `same` when the counts are equal; the difference in pass rate (the second's minus the first's) with a 95% Newcombe score interval; and the one-sided mid-p value for the observed direction, from the hypergeometric distribution of the two counts with the total of passes fixed (for `same`, 0.5). When both stages passed, or both failed, every sample of a question, the report SHALL say so in place of an interval. The comparison SHALL NOT classify a question or the set by comparing a p-value or an interval with a threshold, and SHALL give no verdict for a question or the set; it SHALL count the set's questions in each direction. The report SHALL show the stages' condition. Stages of different history conditions or orders SHALL be refused.

#### Scenario: A large difference
- **WHEN** a question passes 2 of 10 rollouts with the current code and 9 of 10 with a candidate
- **THEN** the report shows that question as `more`, +0.70 with the interval [+0.27, +0.87], and mid-p 0.001

#### Scenario: A small difference
- **WHEN** a question passes 6 of 10 with the current code and 8 of 10 with a candidate
- **THEN** the report shows `more`, +0.20 with the interval [−0.19, +0.52], and mid-p 0.192, and no verdict

#### Scenario: Every sample passed in both
- **WHEN** both stages pass a question in 10 of 10 samples
- **THEN** the report shows `same`, mid-p 0.5, and that both stages passed every sample, with no interval

#### Scenario: The set
- **WHEN** a candidate passes more samples on two questions, fewer on one and the same on two
- **THEN** the report counts 2 `more`, 1 `fewer` and 2 `same`, and gives the set no verdict

#### Scenario: Different conditions
- **WHEN** the current code's `fixed` stage is compared with a candidate's `none` stage as code versions
- **THEN** the comparison refuses them

### Requirement: Adopting a change to the MCP server's wording or results by the user's decision
A change to the MCP server's tool descriptions, argument descriptions, instructions or result fields made to change how models use the tools SHALL be adopted only by the user's decision. Before the decision, the change SHALL be measured against the current code with the same model: full rollouts of the dev and held-out sets in the set's order under both the `fixed` and the `none` history conditions, and a session batch through the documented client with the change. Whoever runs the measurement SHALL present the figures to the user and ask for the decision; it SHALL NOT decide, infer or assume adoption from any figure, rule or earlier answer. The change's design SHALL record each comparison's figures (held-out as counts and the figures computed from them), the session batch's results, the user's decision and the user's reasons. The figures presented SHALL cover at least: the direction and size of the dev differences under each condition; any dev question that passed fewer samples, and by how much; the held-out set's directions under each condition; and any question that rollouts passed and that failed in every session. A candidate that isn't adopted SHALL be removed from the code.

#### Scenario: Figures presented, decision asked
- **WHEN** a candidate's four rollout comparisons and its session batch are complete
- **THEN** the user is shown the figures for each and asked whether to adopt it, and nothing is adopted until the user answers

#### Scenario: Adopted
- **WHEN** the user decides to adopt a candidate
- **THEN** its design records both conditions' comparisons for dev and held-out, the session batch's results, the decision and the user's reasons

#### Scenario: Not adopted
- **WHEN** the user decides against a candidate
- **THEN** it is removed from the code, and its design records the figures, the decision and the user's reasons

#### Scenario: Large differences don't decide
- **WHEN** a candidate passes more samples on every dev question under both conditions, with mid-p values below 0.01
- **THEN** it is still not adopted until the user decides

## MODIFIED Requirements

### Requirement: Comparing conditions
Comparing two stages of the same code, set, model and kind that differ in history condition or order SHALL give, for each question, the same figures as the comparison of code versions: both pass counts, the observed direction (`more` when the second stage passed more samples, `fewer`, or `same`), the difference in pass rate with its 95% interval, and the one-sided mid-p value for the observed direction. It SHALL NOT classify a question by a threshold. It SHALL refuse stages of different code, sets, models or kinds, and stages whose conditions are the same. It SHALL give no verdict for the set.

#### Scenario: A history effect
- **WHEN** a question passes 2 of 10 rollouts under `fixed` and 9 of 10 under `none`, with the same code
- **THEN** comparing the `fixed` stage with the `none` stage shows that question as `more`, +0.70 with the interval [+0.27, +0.87], and mid-p 0.001

#### Scenario: Different code
- **WHEN** the two stages ran different code
- **THEN** the comparison of conditions refuses them

## REMOVED Requirements

### Requirement: Comparison verdict
**Reason**: it classified each question and the set by a p ≤ 0.05 cutoff (`better`, `worse`, `within noise`).
**Migration**: "Comparing code versions" reports the same comparison as counts, direction, an estimated difference with its interval and a mid-p value, with no verdict.

### Requirement: Adopting a change to the MCP server's wording or results
**Reason**: its conditions were verdicts from a p ≤ 0.05 cutoff.
**Migration**: "Adopting a change to the MCP server's wording or results by the user's decision" requires the same measurements and records the user's decision over their figures.
