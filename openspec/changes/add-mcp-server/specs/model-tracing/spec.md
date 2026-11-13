## ADDED Requirements

### Requirement: Spans for MCP tool calls
While tracing is on, the MCP server (see `mcp-server`) SHALL emit one span for each tool call that starts a tool, whether the tool answers or fails, and each such span SHALL be its own trace. The span SHALL carry the tool's name, that it is a tool call, the transport (standard input and output), the posting's integer id when the call names one, the number of items in the result, the total number of matches for a search, the size of the result in characters, and whether the result was cut at a size limit. A call that fails SHALL have an error status and the kind of failure. A call refused before a tool starts (an unknown or unshared tool, arguments outside the tool's schema) SHALL emit no span, and neither SHALL any other protocol message (connecting, listing tools). No span other than these SHALL be sent for the server's work. Attributes that the OpenTelemetry semantic conventions for MCP and GenAI name SHALL use those names; the rest SHALL be prefixed `jobhunt.`. Whether tracing is on SHALL NOT change a tool's result.

#### Scenario: A search
- **WHEN** tracing is on and a client calls `search_postings`, which returns 20 of 45 matching postings
- **THEN** one trace holds one span named for the `search_postings` tool call, with 20 items, a total of 45 and the result's size

#### Scenario: One posting
- **WHEN** tracing is on and a client calls `posting_fit` with `job_id` 12
- **THEN** the span carries posting id 12 and the tool's name

#### Scenario: A failed call
- **WHEN** tracing is on and a client calls `get_posting` with an id that doesn't exist
- **THEN** the span has an error status and names the kind of failure

#### Scenario: A refused argument
- **WHEN** tracing is on and a client calls `search_postings` with `sort` `salary`
- **THEN** no span is emitted

#### Scenario: Connecting and listing
- **WHEN** tracing is on and a client connects and lists the tools without calling one
- **THEN** no span is sent

#### Scenario: Same result
- **WHEN** the same tool call is made once with tracing off and once with tracing on
- **THEN** both return the same result

## MODIFIED Requirements

### Requirement: Trace endpoint is fixed at start-up and local
The `serve`, `eval` and `mcp` commands SHALL accept a trace endpoint option, `--otlp-endpoint`, defaulting to the `JOBHUNT_OTLP_ENDPOINT` environment variable and otherwise to no endpoint. The value SHALL be the full OTLP/HTTP traces address. Its host SHALL be a loopback address (`localhost`, an address in `127.0.0.0/8`, or `::1`) and its scheme `http` or `https`; any other value SHALL be refused before the command does anything else, with exit status 2 and a message saying that traces are only sent to this machine. The endpoint SHALL be fixed when the command starts, SHALL NOT be readable from or changeable through the web interface's requests or settings or through an MCP client, and SHALL be the only address spans are sent to. `serve` SHALL print the endpoint at start-up when tracing is on, and `mcp` SHALL write it to standard error.

#### Scenario: Endpoint from the option
- **WHEN** the user runs `jobhunt serve --otlp-endpoint http://localhost:4318/v1/traces` with the extra installed
- **THEN** the start-up output names that address as the trace endpoint, and spans of model work are sent to it

#### Scenario: Endpoint from the environment
- **WHEN** `JOBHUNT_OTLP_ENDPOINT` is `http://127.0.0.1:4318/v1/traces` and the user runs `jobhunt eval`
- **THEN** the evaluation's spans are sent to that address

#### Scenario: Remote endpoint refused
- **WHEN** the user runs `jobhunt serve --otlp-endpoint https://traces.example.com/v1/traces`
- **THEN** the command exits with status 2 before opening the database, saying that traces are only sent to this machine

#### Scenario: Not settable from the browser
- **WHEN** a settings request includes a trace endpoint
- **THEN** it is ignored, and spans keep going only to the endpoint given at start-up, or nowhere

#### Scenario: Endpoint for the MCP server
- **WHEN** a client starts `jobhunt mcp --share postings --otlp-endpoint http://localhost:4318/v1/traces` with the `otel` extra installed
- **THEN** standard error names that address as the trace endpoint, standard output holds only protocol messages, and spans of tool calls are sent to that address

### Requirement: Spans for runs, steps and model calls
While tracing is on, the system SHALL emit:
- one **run** span for each posting run, each document run and each link-judging job, whether it succeeds, fails or is cancelled;
- one **step** span inside the run span for each step the run starts (a posting run's segment, skills and salary steps; a document run's sections, lines, records, skills and context-link steps; a links job's expansion, embedding and one judging step per posting skill sent to the model);
- one **model call** span inside its step span for each chat request and each embedding call, including a request made again after an empty answer.

`jobhunt eval` and `jobhunt eval --links` SHALL emit one root span per command, with the run, step and model call spans of the work they do inside it. A stored result that is reused SHALL emit no span. A links job run by `serve` and each job of the queue SHALL be its own trace. Work that calls no model outside these (importing, page views, recommendations, CV proposals, the prune) SHALL emit no span, with one exception: a tool call answered by the MCP server (see "Spans for MCP tool calls").

#### Scenario: A posting run
- **WHEN** tracing is on and a posting is extracted with the `llm-lines` segmenter, where the skills step makes two requests
- **THEN** one trace holds a run span with three step spans (segment, skills, salary) under it, and under them one chat span for the segment request, two for the skills requests and one per salary request

#### Scenario: A links job
- **WHEN** tracing is on and a links job embeds 12 new skill names and judges 5 posting skills that have candidates
- **THEN** its trace holds a run span, an embedding step with one embedding call span, and 5 judging steps with one chat span each

#### Scenario: An evaluation with reused runs
- **WHEN** tracing is on and `jobhunt eval` reuses 8 stored runs and makes 2 new ones
- **THEN** one trace holds the command's root span with 2 run spans under it

#### Scenario: A cancelled run
- **WHEN** a running posting job is cancelled after its segment step
- **THEN** its run span ends with a cancelled status and holds the segment step span only

### Requirement: No text in spans by default
By default, spans SHALL NOT contain posting text, document text, prompts, model answers, quotes, skill names, titles, company names, addresses, profile values, the text of a tool call's arguments (such as a search text or a tag) or the message text of an error; identifiers SHALL be the database's integer ids. The `serve`, `eval` and `mcp` commands SHALL accept `--trace-content`, defaulting to on when the `JOBHUNT_TRACE_CONTENT` environment variable is `1`, fixed at start-up like the endpoint. With it, each chat span SHALL also carry the request's system and user messages and the model's answer, a judging step SHALL carry its posting skill's name, a tool call span SHALL carry the call's arguments, and failed spans SHALL carry the error's message. Embedding call spans SHALL NOT carry their texts either way, and tool call spans SHALL NOT carry the tool's result either way. `serve` SHALL print at start-up that span content is on when it is, and `mcp` SHALL write it to standard error.

#### Scenario: Default spans
- **WHEN** tracing is on without `--trace-content` and a posting whose description mentions "Example Robotics" is extracted
- **THEN** no span attribute, name or event of the trace contains "Example Robotics", the prompt or the model's answer

#### Scenario: Content switched on
- **WHEN** `jobhunt serve --otlp-endpoint http://localhost:4318/v1/traces --trace-content` extracts the same posting
- **THEN** each chat span carries its messages and answer, and the start-up output says span content is on

#### Scenario: Error text
- **WHEN** tracing is on without `--trace-content` and a step fails
- **THEN** the failed spans name the kind of failure and the step, without the error's message

#### Scenario: A tool call by default
- **WHEN** tracing is on without `--trace-content` and a client calls `search_postings` with `q` "Example Robotics" and `tag` "shortlist"
- **THEN** the tool call span contains neither "Example Robotics" nor "shortlist", nor any title, company or skill name from the result

#### Scenario: A tool call with content on
- **WHEN** `jobhunt mcp --share postings --otlp-endpoint http://localhost:4318/v1/traces --trace-content` answers the same call
- **THEN** the span carries the call's arguments, including "Example Robotics", and nothing from the result
