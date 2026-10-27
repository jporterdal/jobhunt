## Purpose

Measuring how well candidate-finding and link judging reproduce the links the user chose by hand, so a new linking method can be adopted or discarded on evidence instead of by reading the links page.

## ADDED Requirements

### Requirement: Reference set
Link measurement SHALL use the user's link overrides as its reference. An override SHALL be in the reference set when its posting skill is still a posting skill, has no same-identity profile skill, and the override is not stale. An override naming a profile skill SHALL count as a reference link, with that skill and relation. An override of "no link" SHALL count as a confirmed refusal. The report SHALL state the number of reference links and confirmed refusals, and the number of overrides left out for each reason. Measuring SHALL NOT change overrides, marks or rejected suggestions.

#### Scenario: Building the reference set
- **WHEN** the user has 55 overrides: 5 on posting skills with a same-identity profile skill, 1 naming a skill that has left the profile, 29 other links and 20 other "no link" answers
- **THEN** the reference set has 29 links and 20 confirmed refusals, and the report states that 5 were left out for same identity and 1 as stale

### Requirement: Link measuring command
`jobhunt eval --links` SHALL measure links instead of skill extraction. It SHALL accept a list of candidate-finding methods (`--retrieval`) and a list of judging versions (`--judge`), each defaulting to the app's current one, and SHALL measure every combination of them. It SHALL use the chat model from the settings unless one is given, and the embedding model from the settings. It SHALL accept the database and Ollama address options with the same defaults as `serve`, and SHALL print its report as text or, when asked, as JSON.

Before making any model request, the command SHALL state the number of expansion, embedding and judging requests it needs. When asked for a dry run, it SHALL stop after stating them. It SHALL reuse stored expansions, stored vectors, and stored judgments (its own or the app's) made for the same posting skill, judging version, chat model, embedding model and candidate profile skills in the same order (the judge numbers them in order). When asked to run fresh, it SHALL make new judgments but still reuse expansions and vectors. Results stored before an interruption SHALL be kept and reused by the next run.

The command SHALL exit with a non-zero status, without model requests, when the reference set is empty, when a named method or version is unknown (naming the available ones), or when no chat model or embedding model is chosen or installed. It SHALL exit with a non-zero status when requests are needed and the Ollama server is unreachable, after stating the requests.

#### Scenario: Stating requests first
- **WHEN** the user runs `jobhunt eval --links --retrieval skill-expand@1 --dry-run` and 50 reference posting skills and 48 profile skills have no expansion at that version
- **THEN** the command states 98 expansion requests, the embedding and judging requests, and makes no model request

#### Scenario: Reusing the app's judgments
- **WHEN** the reference posting skill `Python packaging` was judged by the app with the current judging version, chat model and embedding model, and its shortlist is unchanged
- **THEN** measuring the current method uses that judgment and makes no judging request for it

#### Scenario: Unknown version
- **WHEN** the user runs `jobhunt eval --links --judge link-judge@9`
- **THEN** the command names the available judging versions, makes no model request and exits with a non-zero status

#### Scenario: No overrides
- **WHEN** the user has no overrides in the reference set
- **THEN** the command says that measuring needs links set on the links page, makes no model request and exits with a non-zero status

### Requirement: Candidate-finding measures
For each candidate-finding method, the report SHALL show:
- the number of reference links whose profile skill is in the shortlist, at the method's own shortlist size and floor, and for each one that is not, the profile skill's rank and similarity
- a table over a range of shortlist sizes and floors, computed from the same stored vectors without further requests, giving for each the number of reference links whose skill is shortlisted and the mean number of candidates per reference posting skill
- the number of confirmed refusals with no candidate at all.

#### Scenario: A missed candidate
- **WHEN** the right profile skill for `Claude Code` ranks 40th of 48 with similarity 0.66 under bare-name comparison, with shortlist size 5
- **THEN** the report lists `Claude Code` as missed, with its right skill, rank 40 and similarity 0.66

#### Scenario: Sweeping sizes and floors
- **WHEN** the report is printed for a method
- **THEN** it includes, for each listed size and floor, the shortlisted reference links and the mean number of candidates, and the sweep made no model request

### Requirement: Judging measures
For each combination of candidate-finding method and judging version, the report SHALL count, over the reference links:
- the right skill with the right relation
- the right skill with another relation
- a link to another profile skill that the judge gave the same relation as the right skill, so that only the candidates' order decided between them (tied with the user's choice)
- no link, although the right skill was a candidate
- a link to another profile skill, otherwise
- no link, with the right skill not a candidate.

It SHALL count the confirmed refusals that end with no link. It SHALL count the reference links again with the right profile skill added to the candidates wherever the shortlist lacked it, so that judging errors are counted apart from candidate-finding errors. Adding the right skill SHALL only be done while measuring.

#### Scenario: Judging on its own shortlist
- **WHEN** the judge links `Written communication` to nothing although `Communication` was a candidate, and the user linked it to `Communication` as `general`
- **THEN** it counts as no link although the right skill was a candidate

#### Scenario: Right skill added
- **WHEN** `Git`'s shortlist lacks the user's choice `serverless CI/CD`
- **THEN** `Git` is judged a second time with `serverless CI/CD` added to its candidates, and that judgment counts only in the figures with the right skill added

#### Scenario: Tied with the user's choice
- **WHEN** the user linked `Master's degree` to `MSc` as `specific`, and the judge calls both `MEng` and `MSc` `specific` with `MEng` first in the shortlist
- **THEN** the link to `MEng` counts as tied with the user's choice, not as a link to another skill

#### Scenario: Refusal kept
- **WHEN** the user confirmed "no link" for `Vector databases`, and the judge says none to all its candidates
- **THEN** the refusal counts as kept

### Requirement: Comparing linking methods
The first combination SHALL be the app's current method, or the first named one when the current method is not among them. Every other combination SHALL be compared with it reference posting skill by reference posting skill. A reference posting skill counts as right when its link has the right skill and relation, or, for a confirmed refusal, when no link results. The report SHALL count the reference posting skills the combination gets right and the first gets wrong (fixed), and the other way round (broken), and SHALL give the chance of a split at least that uneven if each differing posting skill went either way with equal chance (a one-sided exact sign test). Judging the same posting skill twice, with a different shortlist or prompt, can change its answer, so small differences are expected by chance. The verdict SHALL be:
- `same` when nothing is fixed or broken
- `better` when more are fixed than broken and that chance is at most 0.05
- `worse` when more are broken than fixed and that chance is at most 0.05
- `within noise` otherwise.

The report SHALL list the reference posting skills whose resulting link differs between combinations, with each combination's link and the user's. The JSON report SHALL include, per reference posting skill and combination, the candidates with their similarity and most similar pair of phrases, the judged relations, the resulting link and the user's link.

#### Scenario: Better beyond chance
- **WHEN** the candidate fixes 5 reference posting skills and breaks none
- **THEN** the chance is 1 in 32, and the candidate's verdict is `better`

#### Scenario: Within noise
- **WHEN** the candidate fixes none and breaks 4, two of them confirmed refusals
- **THEN** the chance is 1 in 16, the verdict is `within noise`, and the differing posting skills list the two refusals it broke

### Requirement: Preview over all posting skills
When asked, the command SHALL also find candidates and judge every posting skill without an override or same-identity profile skill, for each combination, and SHALL report per combination how many have a link and how many links differ from the app's current links. These figures SHALL NOT be scored. The command SHALL include the requests this needs in its statement before making any.

#### Scenario: Previewing a candidate method
- **WHEN** the user runs `jobhunt eval --links --judge link-judge@5,link-judge@6 --all-skills`
- **THEN** the report shows, for each judging version, the number of posting skills linked and the number whose link would differ from the app's, without precision or recall figures for them

### Requirement: Measurement results stay apart
Judgments made by link measurement SHALL be stored as derived data apart from the app's judgments. They SHALL never determine a link, appear on the links page, or count as a judgment when the app decides what to re-judge. Expansions made while measuring SHALL be the same as those the app would make for the same skill, step version and context, and the app MAY use them.

#### Scenario: Measuring a candidate version
- **WHEN** the user measures `link-judge@6` while the app uses `link-judge@5`, and then opens the links page
- **THEN** every model link on the page comes from a `link-judge@5` judgment made by the app
