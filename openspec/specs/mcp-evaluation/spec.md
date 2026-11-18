# mcp-evaluation Specification

## Purpose

Measuring how a model uses jobhunt's MCP server on the demo database, so that a change to the tools' wording or results is adopted only when it measures better on questions it was tuned on and isn't worse on questions it wasn't. Covers the question sets and their checks, sessions through the documented client, rollouts that reproduce that client's requests, the report, the comparison verdict and the rule for adopting a change.

## Requirements

### Requirement: Demo data only
Every measurement command SHALL refuse, before calling a model or starting a client, a database that isn't marked as a demo database, with a non-zero exit status and a message saying it measures on the demo only. The commands SHALL open the database read-only, as the MCP server does. Question sets, expected answers and test fixtures SHALL use only the demo's fictional data.

#### Scenario: The user's own database
- **WHEN** a measurement command is given `sqlite:///data/jobhunt.db`, a database that wasn't built by `jobhunt demo`
- **THEN** it exits with an error before contacting Ollama or starting a client, and the database is unchanged

#### Scenario: The demo
- **WHEN** it is given a database built by `jobhunt demo`
- **THEN** it runs

### Requirement: Local only, started by hand
The commands SHALL contact only loopback addresses (the Ollama server and, for sessions, the capture proxy) and SHALL refuse any other Ollama address before sending a request. A command that runs a model SHALL do so only when a person starts it; nothing SHALL schedule or repeat a measurement by itself. Before sending any request, a command SHALL state how many requests or sessions it will run per question and code version, and SHALL offer a dry run that stops there.

#### Scenario: A remote Ollama address
- **WHEN** a command is given `--ollama-url http://gpu.example.com:11434`
- **THEN** it exits with an error and sends nothing

#### Scenario: Dry run
- **WHEN** a rollout comparison of two code versions is started with the dry-run option on the dev set with 10 rollouts each
- **THEN** it states the number of questions, rollouts and code versions and sends no request

### Requirement: Question sets
Questions SHALL be kept in two sets, **dev** and **held-out**, each a data file in the repository. Each question SHALL carry its text, its place in the set's order (earlier questions form its history under the `fixed` condition), the final answer used for it when it is history for a later question, and its checks: which facts a right answer states (the postings' original URLs, figures up to rounding, named skills or amounts), which tool calls a right answer needs, and which diagnostics apply. Each question's text SHALL be answerable on its own, without any earlier question, so that it can be asked under every history condition. A question SHALL be in one set only. A test SHALL build the demo and check each question's expected facts against the tools' own results, so a change to the demo that alters an expected fact fails the suite.

#### Scenario: An expected figure no longer holds
- **WHEN** the demo changes so that the Senior Data Analyst posting's match score is no longer 0.644
- **THEN** the test fails, naming the question and the expected fact

#### Scenario: Held-out questions exercise other cases
- **WHEN** the held-out set is read
- **THEN** it holds questions on cases the dev set doesn't ask about: a filter other than `workplace` carried from an earlier question, a dismissed posting asked about by name, a question naming only a company, and a posting named by the number in its URL

#### Scenario: A question that needs its history
- **WHEN** a proposed question refers to an earlier one ("which of those pay the most?")
- **THEN** it isn't added to a set, since it can't be asked without history

### Requirement: Held-out results are figures only
Reports SHALL show held-out questions as pass counts and diagnostic counts only, without their calls, results, answers or the model's thinking. Showing a held-out question's transcript SHALL require an explicit option, and doing so SHALL move that question to the dev set in its data file, saying so. A dev question SHALL never move to the held-out set.

#### Scenario: Looking at a held-out failure
- **WHEN** the user asks to see the calls and answer of a held-out question with the explicit option
- **THEN** they are shown, the question is moved to the dev set file, and the command says it was moved

#### Scenario: Without the option
- **WHEN** the user asks to see a held-out question's transcript without the option
- **THEN** the command refuses and shows nothing of it

### Requirement: Sessions through the documented client
A session SHALL run the client and model that `docs/mcp.md` documents, started as that page starts it, against `jobhunt mcp` on the demo database from the working tree, with every request and reply recorded through the capture proxy. It SHALL ask the set's questions in order, confirm each tool call the client asks about, stop a question at the client's loop limit, and record the connections the client and server make. A batch SHALL run a given number of fresh sessions and store each one's capture and terminal record under the ignored data folder, by stage name.

#### Scenario: A batch of three
- **WHEN** the user runs a batch of 3 sessions of the dev set named `example-stage`
- **THEN** three sessions run one after another, each with its own capture of every request and reply, and the batch reports how many questions each session finished

### Requirement: Rollouts reproduce the client's requests
A rollout SHALL answer one question the way the documented client would, without the client: it SHALL send Ollama the requests the client sends (the same tool names, descriptions and input schemas as the client renders them from the working tree's server, the same request options, the question's history under the stage's history condition and order, and, within the question, each assistant message with its tool calls and each tool result as the client passes it on), answer each tool call by calling the working tree's server in-process with the call's arguments, and stop at the model's final answer or at the client's loop limit. A rollout SHALL record every request, reply and tool result. Under the `fixed` and `none` conditions, several rollouts of the same question in the same position SHALL be independent samples from the same history. A single-step rollout SHALL send only the question's first request and record its tool calls; single steps SHALL be refused under the `own` condition.

#### Scenario: Current tool wording
- **WHEN** a tool's description is changed in the working tree and a rollout runs
- **THEN** the rollout's requests carry the changed description, rendered as the client renders it

#### Scenario: Current tool results
- **WHEN** a rollout's model calls `search_postings` with `q` "Machine Learning Engineer" and `workplace` `Remote`
- **THEN** the next request carries the result the working tree's server returns for those arguments on the demo

#### Scenario: Loop limit
- **WHEN** a model keeps calling tools without answering
- **THEN** the rollout stops after the client's loop limit and records the question as unanswered

### Requirement: History conditions
A rollout stage SHALL run under one history condition, recorded with the stage: **fixed** (each question after the earlier questions of the set with their recorded final answers; the default), **own** (chains: each chain asks the set's questions in order, and each final answer the model gives becomes history for the later questions of that chain, as the documented client keeps it, a question stopped at the loop limit being left out), or **none** (each question alone, with no earlier messages). A chain SHALL give one sample of every question of the set. A stage recorded without a condition SHALL be read as `fixed`. Sessions SHALL be recorded as `own`.

#### Scenario: No history
- **WHEN** a stage runs with history `none`
- **THEN** each question's first request holds only that question as a user message, with the same tools and options as under `fixed`

#### Scenario: The model's own history
- **WHEN** a chain's model answers the first question with a given text
- **THEN** the second question's first request holds the first question and that text as history, and not the first question's recorded final answer

#### Scenario: A question stopped at the loop limit
- **WHEN** a chain's question is stopped at the loop limit
- **THEN** it is left out of the history of the chain's later questions

#### Scenario: An earlier stage
- **WHEN** a stage recorded before conditions existed is scored or compared
- **THEN** it is read as history `fixed` in the set's order

### Requirement: Question order
A stage SHALL ask questions in the set's order unless a balanced order is asked for. A balanced order SHALL follow a Williams design over the set's questions: each question in each position equally often, and directly after each other question equally often, across its orders, with sample *k* of each question taken from the *k*-th order (cycling); for five questions that is ten orders. The stage SHALL record its orders, and each sample its order. When the sample count isn't a multiple of the number of orders, the command SHALL say before running that the stage isn't balanced. A balanced order SHALL be refused with history `none`. The documentation SHALL give the set's order as the default and the balanced order as an option for one-off evaluations.

#### Scenario: A balanced dev stage
- **WHEN** a dev stage runs 10 samples a question with history `fixed` and a balanced order
- **THEN** each dev question is asked twice in each of the five positions and twice directly after each other dev question, and each sample's history is the questions before it in its order

#### Scenario: Not a whole number of orders
- **WHEN** a balanced stage of five questions is started with 7 samples a question
- **THEN** the command states that the stage isn't balanced before sending any request

### Requirement: Rollouts match a real capture
A check SHALL compare the requests a rollout builds with those in a capture of a real session of the same code, for the same history and the same tool calls and results: apart from the model's sampled output, the tools, options and messages SHALL be equal. The check SHALL be run whenever the documented client's version changes, and its result SHALL be recorded in `docs/mcp-eval.md` with that version.

#### Scenario: Same request
- **WHEN** a capture of a real session is replayed through the rollout's request building with the capture's own tool calls
- **THEN** each built request equals the captured one in its tools, options and messages

### Requirement: Stopped stages resume
A rollout stage SHALL record each sample as it finishes, so that a stage stopped by the user or by a failure keeps what it recorded. Resuming a stopped stage SHALL run only the samples it lacks, with the stage's own set, questions, sample count, model, kind, history condition and order, and SHALL be refused when the code, the set's questions or recorded answers, the tools as sent or the Ollama version differ from the stage's. A chain stopped part-way SHALL continue at its first unrecorded question, with its recorded answers as history.

#### Scenario: Interrupted and resumed
- **WHEN** a stage of 2 samples of two questions is interrupted after the first sample of each, and then resumed
- **THEN** only the two second samples run, and the stage is then finished

#### Scenario: A chain stopped part-way
- **WHEN** an `own` stage stops after a chain's first question and is resumed
- **THEN** that chain's second question is asked with the first question's recorded answer as history

#### Scenario: Changed code
- **WHEN** the server's code changed since the stage started
- **THEN** resuming is refused and nothing is sent

### Requirement: Report
For a stage (a batch of sessions or of rollouts of one code version), the report SHALL name the stage's history condition and order, and SHALL show, per question, how many samples passed each of its checks and in how many samples each diagnostic was seen, and per set, how many samples passed every question. Diagnostics SHALL include at least: the number in a posting's URL passed as a `job_id`, a title and a company in one `q`, an argument the tool doesn't have, a filter argument the question doesn't ask for (named as carried from an earlier question when the stage has history, and as unasked when it has none), an amount of money in the answer that no tool result of that sample holds, a call refused, and a result with warnings. A sample SHALL pass a question only when every one of its checks passed.

#### Scenario: A failed check
- **WHEN** a rollout's answer to the Machine Learning Engineer question gives a salary of $140,000
- **THEN** the report counts that sample as failing the question and counts a made-up amount

#### Scenario: A stage without history
- **WHEN** a `none` stage's search uses a filter its question doesn't ask for
- **THEN** the report names the stage's condition and counts an unasked filter, not a carried one

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

### Requirement: Comparing conditions
Comparing two stages of the same code, set, model and kind that differ in history condition or order SHALL give, for each question, the same figures as the comparison of code versions: both pass counts, the observed direction (`more` when the second stage passed more samples, `fewer`, or `same`), the difference in pass rate with its 95% interval, and the one-sided mid-p value for the observed direction. It SHALL NOT classify a question by a threshold. It SHALL refuse stages of different code, sets, models or kinds, and stages whose conditions are the same. It SHALL give no verdict for the set.

#### Scenario: A history effect
- **WHEN** a question passes 2 of 10 rollouts under `fixed` and 9 of 10 under `none`, with the same code
- **THEN** comparing the `fixed` stage with the `none` stage shows that question as `more`, +0.70 with the interval [+0.27, +0.87], and mid-p 0.001

#### Scenario: Different code
- **WHEN** the two stages ran different code
- **THEN** the comparison of conditions refuses them

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

### Requirement: Terms defined in the documentation
`docs/mcp-eval.md` SHALL define, in its own text and before the commands, at least: question set, history (and its conditions), rollout, single-step rollout, chain, session, sample, stage and order, so that a reader needs no spec or design to know what a figure counts.

#### Scenario: Reading a report
- **WHEN** a reader sees "dev-2 passed 2/10" in a stage's report
- **THEN** `docs/mcp-eval.md` alone says what a sample and a stage are, and which history the stage's questions were asked with
