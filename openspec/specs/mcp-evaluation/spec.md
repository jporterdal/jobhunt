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
Questions SHALL be kept in two sets, **dev** and **held-out**, each a data file in the repository. Each question SHALL carry its text, its place in the set's order (earlier questions form its history), the final answer used for it when it is history for a later question, and its checks: which facts a right answer states (the postings' original URLs, figures up to rounding, named skills or amounts), which tool calls a right answer needs, and which diagnostics apply. A question SHALL be in one set only. A test SHALL build the demo and check each question's expected facts against the tools' own results, so a change to the demo that alters an expected fact fails the suite.

#### Scenario: An expected figure no longer holds
- **WHEN** the demo changes so that the Senior Data Analyst posting's match score is no longer 0.644
- **THEN** the test fails, naming the question and the expected fact

#### Scenario: Held-out questions exercise other cases
- **WHEN** the held-out set is read
- **THEN** it holds questions on cases the dev set doesn't ask about: a filter other than `workplace` carried from an earlier question, a dismissed posting asked about by name, a question naming only a company, and a posting named by the number in its URL

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
A rollout SHALL answer one question the way the documented client would, without the client: it SHALL send Ollama the requests the client sends (the same tool names, descriptions and input schemas as the client renders them from the working tree's server, the same request options, the question's history of earlier questions and their recorded final answers, and, within the question, each assistant message with its tool calls and each tool result as the client passes it on), answer each tool call by calling the working tree's server in-process with the call's arguments, and stop at the model's final answer or at the client's loop limit. A rollout SHALL record every request, reply and tool result. Several rollouts of the same question SHALL be independent samples from the same history. A single-step rollout SHALL send only the question's first request and record its tool calls.

#### Scenario: Current tool wording
- **WHEN** a tool's description is changed in the working tree and a rollout runs
- **THEN** the rollout's requests carry the changed description, rendered as the client renders it

#### Scenario: Current tool results
- **WHEN** a rollout's model calls `search_postings` with `q` "Machine Learning Engineer" and `workplace` `Remote`
- **THEN** the next request carries the result the working tree's server returns for those arguments on the demo

#### Scenario: Loop limit
- **WHEN** a model keeps calling tools without answering
- **THEN** the rollout stops after the client's loop limit and records the question as unanswered

### Requirement: Rollouts match a real capture
A check SHALL compare the requests a rollout builds with those in a capture of a real session of the same code, for the same history and the same tool calls and results: apart from the model's sampled output, the tools, options and messages SHALL be equal. The check SHALL be run whenever the documented client's version changes, and its result SHALL be recorded in `docs/mcp-eval.md` with that version.

#### Scenario: Same request
- **WHEN** a capture of a real session is replayed through the rollout's request building with the capture's own tool calls
- **THEN** each built request equals the captured one in its tools, options and messages

### Requirement: Report
For a stage (a batch of sessions or of rollouts of one code version), the report SHALL show, per question, how many samples passed each of its checks and in how many samples each diagnostic was seen, and per set, how many samples passed every question. Diagnostics SHALL include at least: the number in a posting's URL passed as a `job_id`, a title and a company in one `q`, an argument the tool doesn't have, a filter argument carried from an earlier question that the question doesn't ask for, an amount of money in the answer that no tool result of that sample holds, a call refused, and a result with warnings. A sample SHALL pass a question only when every one of its checks passed.

#### Scenario: A failed check
- **WHEN** a rollout's answer to the Machine Learning Engineer question gives a salary of $140,000
- **THEN** the report counts that sample as failing the question and counts a made-up amount

### Requirement: Comparison verdict
Comparing two stages of the same question set (two code versions, the same model and sample counts) SHALL give, for each question, the pass counts of both and a verdict: `better` when the second passes more often with a one-sided exact test of the two counts at p ≤ 0.05, `worse` when it passes less often by the same test, and `within noise` otherwise. The comparison SHALL give the set a verdict: `better` when at least one question is `better` and none is `worse`, `worse` when any question is `worse`, `within noise` otherwise. The report SHALL show each p-value.

#### Scenario: A clear improvement
- **WHEN** a question passes 2 of 10 rollouts with the current code and 9 of 10 with a candidate, and no other question differs
- **THEN** that question and the set are `better`

#### Scenario: Small differences
- **WHEN** a question passes 6 of 10 with the current code and 8 of 10 with a candidate
- **THEN** that question is `within noise`

### Requirement: Adopting a change to the MCP server's wording or results
A change to the MCP server's tool descriptions, argument descriptions, instructions or result fields made to change how models use the tools SHALL be adopted only when, against the current code, rollouts give the dev set `better` and the held-out set not `worse`, with the same model, and a session batch through the documented client with the change shows no question that rollouts passed failing in every session. The change's design SHALL record the comparison's figures. A candidate that isn't adopted SHALL be removed from the code.

#### Scenario: Better on dev, worse on held-out
- **WHEN** a candidate is `better` on the dev set and `worse` on the held-out set
- **THEN** it isn't adopted

#### Scenario: Better on both
- **WHEN** a candidate is `better` on dev and `within noise` on held-out, and its session batch agrees
- **THEN** it may be adopted, and its design records the figures
