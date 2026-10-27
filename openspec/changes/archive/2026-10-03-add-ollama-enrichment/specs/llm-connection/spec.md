## Purpose

Connects the local web app to a local Ollama server when one is running. Covers availability and GPU status, the user's model settings, and the background queue that runs model work without blocking the interface.

## ADDED Requirements

### Requirement: Configured Ollama address
The `serve` and `eval` commands SHALL accept an Ollama URL option. It SHALL default to the `JOBHUNT_OLLAMA_URL` environment variable, then to `http://localhost:11434`. The address SHALL be fixed when the command starts and SHALL NOT be changeable from the web interface. The system SHALL send model requests only to this address.

#### Scenario: Default address
- **WHEN** the user runs `jobhunt serve` with no Ollama option and `JOBHUNT_OLLAMA_URL` unset
- **THEN** the interface uses `http://localhost:11434` and the startup output prints that address

#### Scenario: Address from the environment
- **WHEN** `JOBHUNT_OLLAMA_URL` is `http://127.0.0.1:11500` and the user runs `jobhunt serve`
- **THEN** the interface uses `http://127.0.0.1:11500`

### Requirement: Works without Ollama
Every feature that does not need a model SHALL work the same whether or not the Ollama server is reachable. An unreachable server SHALL NOT delay page loads by more than the status check's short timeout. Actions that need a model SHALL be disabled, with an explanation, while the server is unreachable. Model output already stored SHALL still be shown.

#### Scenario: Server not running
- **WHEN** the Ollama server is not running and the user opens a posting that has stored model output
- **THEN** the page loads normally, shows the stored output, and the extract action is disabled with the explanation that Ollama is offline

### Requirement: Status indicator
Every page SHALL show a model status indicator. It SHALL be one of:
- offline
- online, naming the selected model
- online but no model selected, or the selected model is not installed
- online, with a warning that the loaded model is partly running on the CPU (the server reports less GPU memory in use than the model's size)

The indicator SHALL refresh periodically without reloading the page.

#### Scenario: Online with selected model
- **WHEN** the server is reachable and the selected model is installed
- **THEN** the indicator shows online and the model's name

#### Scenario: Model spills to CPU
- **WHEN** the server reports the selected model loaded with less GPU memory than its total size
- **THEN** the indicator warns that the model is partly running on the CPU and will be slower

#### Scenario: Selected model removed
- **WHEN** the selected model is no longer in the server's installed models
- **THEN** the indicator says the selected model is not installed, and the extract action is disabled

### Requirement: Model settings
A settings page SHALL let the user choose:
- the model used for extraction, from the models installed on the server. Models that cannot generate text, such as embedding-only models, SHALL be excluded.
- the context size sent with each request, defaulting to 8192 tokens
- the segmentation method, from the methods the system provides

Settings SHALL be stored in the database and survive restarts. The settings page SHALL show the configured Ollama address read-only. While the server is offline, the settings page SHALL show the stored values and explain that the model list is unavailable.

#### Scenario: Choosing a model
- **WHEN** the server has `gemma4:12b`, `phi4:latest` and `nomic-embed-text:latest` installed and the user opens settings
- **THEN** the model choices are `gemma4:12b` and `phi4:latest`, and after choosing `gemma4:12b` and restarting `serve` it is still selected

### Requirement: Deterministic, bounded model requests
Every extraction request SHALL:
- set temperature 0 and a fixed seed
- send the configured context size
- ask for output matching a JSON schema
- turn off the model's thinking mode when the model supports it
- ask the server to keep the model loaded while queued work remains

A response that is not valid JSON for the schema SHALL count as a failed step, not as an empty result.

#### Scenario: Model default temperature ignored
- **WHEN** the selected model's own default temperature is 1
- **THEN** extraction requests still use temperature 0

#### Scenario: Malformed response
- **WHEN** the server returns text that does not parse as JSON matching the schema
- **THEN** that step fails with an error naming the step, and no items from that step are stored

### Requirement: Background job queue
Model work requested from the web interface SHALL be added to a queue stored in the database and processed one job at a time, outside the request. The interface SHALL show each queued job's state: queued, running, done, failed or cancelled. Failed jobs SHALL show their error. The user SHALL be able to cancel queued jobs. Cancelling a running job SHALL stop it before its next step, and nothing from it SHALL be stored. Jobs that were running when `serve` stopped SHALL be queued again at the next start. While the server is unreachable, queued jobs SHALL wait rather than fail. Queue processing SHALL run only while `serve` runs, and SHALL do nothing except call the configured Ollama address and store results.

#### Scenario: Queue progress
- **WHEN** the user queues extraction for three postings
- **THEN** the interface shows one running and two queued, and updates each to done or failed without a page reload

#### Scenario: Restart with queued work
- **WHEN** `serve` stops while one job is running and two are queued, and is started again
- **THEN** all three jobs are queued and are processed

#### Scenario: Ollama goes offline mid-queue
- **WHEN** the server becomes unreachable while jobs are queued
- **THEN** the queued jobs stay queued and processing resumes when the server is reachable again

#### Scenario: Cancelling
- **WHEN** the user cancels the queue while two jobs are queued
- **THEN** both are marked cancelled and no model requests are made for them
