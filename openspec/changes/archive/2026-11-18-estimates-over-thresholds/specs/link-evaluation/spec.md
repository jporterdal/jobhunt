## ADDED Requirements

### Requirement: Comparing linking methods by estimates
The first combination SHALL be the app's current method, or the first named one when the current method is not among them. Every other combination SHALL be compared with it reference posting skill by reference posting skill. A reference posting skill counts as right when its link has the right skill and relation, or, for a confirmed refusal, when no link results. The report SHALL count the reference posting skills the combination gets right and the first gets wrong (fixed), and the other way round (broken). Judging the same posting skill twice, with a different shortlist or prompt, can change its answer, so small differences are expected by chance. For each combination after the first, the report SHALL give:
- the observed direction: `more right` when more are fixed than broken, `fewer right` when more are broken than fixed, `same` when both counts are equal (none differing included);
- the net change, (fixed − broken) divided by the number of reference posting skills, with a 95% interval for the difference of paired proportions (Newcombe's method 10);
- the one-sided mid-p value of the exact sign test for the observed direction: with n = fixed + broken and k the smaller of the two, the chance of fewer than k when each differing posting skill went either way with equal chance, plus half the chance of exactly k (for `same`, 0.5).

The report SHALL NOT classify a combination by comparing a p-value or an interval with a threshold, and SHALL give no verdict.

The report SHALL list the reference posting skills whose resulting link differs between combinations, with each combination's link and the user's. The JSON report SHALL include, per combination after the first, the fixed and broken counts, the direction, the net change with its interval and the mid-p value, and, per reference posting skill and combination, the candidates with their similarity and most similar pair of phrases, the judged relations, the resulting link and the user's link.

#### Scenario: Fixes without breaks
- **WHEN** the reference set has 40 posting skills, the current method gets 20 right, and the candidate fixes 5 and breaks none
- **THEN** the report shows `more right`, a net change of +0.125 with the interval [+0.023, +0.220], and mid-p 1 in 64 (0.016), with no verdict

#### Scenario: Breaks without fixes
- **WHEN** the reference set has 40 posting skills, the current method gets 20 right, and the candidate fixes none and breaks 4, two of them confirmed refusals
- **THEN** the report shows `fewer right`, a net change of −0.100 with the interval [−0.187, −0.008], and mid-p 1 in 32 (0.031), and the differing posting skills list the two refusals it broke

#### Scenario: Nothing differs
- **WHEN** the candidate fixes none and breaks none
- **THEN** the report shows `same`, a net change of 0 and mid-p 0.5

### Requirement: Adopting a linking method
A candidate-finding method or judging version SHALL become the app's current one only by the user's decision, made after it has been compared with the current method against the reference set. Whoever runs the measurement SHALL present the comparison's figures to the user, with the differing posting skills, and ask for the decision; it SHALL NOT decide, infer or assume adoption from any figure, rule or earlier answer. The change that adopts or discards it SHALL record the figures, the user's decision and the user's reasons. A candidate that isn't adopted SHALL be removed from the code.

#### Scenario: Decision asked
- **WHEN** a measurement of a candidate judging version is complete
- **THEN** the user is shown the fixed and broken counts, the net change with its interval, the mid-p value and the differing posting skills, and asked whether to adopt it

#### Scenario: Large differences don't decide
- **WHEN** a candidate fixes 12 reference posting skills and breaks none
- **THEN** it does not become the app's current method until the user decides, and the change records the decision and the user's reasons

## REMOVED Requirements

### Requirement: Comparing linking methods
**Reason**: its verdict classified a combination by a p ≤ 0.05 cutoff (`better`, `worse`, `within noise`).
**Migration**: "Comparing linking methods by estimates" keeps the same comparison, with fixed and broken counts, the direction, the net change with its interval and a mid-p value, and no verdict.
