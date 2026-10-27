## MODIFIED Requirements

### Requirement: Model settings
A settings page SHALL let the user choose:
- the model used for extraction and link judging, from the models installed on the server. Models that cannot generate text, such as embedding-only models, SHALL be excluded.
- the context size sent with each request, defaulting to 8192 tokens
- the segmentation method, from the methods the system provides
- the skill extraction method, from the methods the system provides, each shown by name and version, defaulting to `atomic@2`
- the embedding model used to shortlist link candidates, from the installed models that can produce embeddings, defaulting to `nomic-embed-text` when it is installed

Settings SHALL be stored in the database and survive restarts. The settings page SHALL show the configured Ollama address read-only. While the server is offline, the settings page SHALL show the stored values and explain that the model list is unavailable. A stored skill extraction method that the system no longer provides SHALL be shown as unavailable, and extraction SHALL use the default until the user chooses another. While no embedding model is chosen or installed, link judging SHALL wait and the links page SHALL say why.

#### Scenario: Choosing a model
- **WHEN** the server has `gemma4:12b`, `phi4:latest` and `nomic-embed-text:latest` installed and the user opens settings
- **THEN** the model choices are `gemma4:12b` and `phi4:latest`, and after choosing `gemma4:12b` and restarting `serve` it is still selected

#### Scenario: Choosing a skill extraction method
- **WHEN** the user opens settings on a database where no skill extraction method was ever chosen, and chooses `atomic@4`
- **THEN** the choices are `atomic@2` and `atomic@4`, `atomic@2` is selected before the change, and after restarting `serve` `atomic@4` is still selected

#### Scenario: Unknown method rejected
- **WHEN** a settings request names the skill extraction method `atomic@3`
- **THEN** the setting is not changed and the page says which methods are available

#### Scenario: Choosing an embedding model
- **WHEN** the server has `gemma4:12b` and `nomic-embed-text:latest` installed and no embedding model was ever chosen
- **THEN** the embedding model choices are `nomic-embed-text:latest` only, and it is selected

### Requirement: Deterministic, bounded model requests
Every chat request (posting extraction, document extraction and link judging) SHALL:
- set temperature 0 and a fixed seed
- send the configured context size
- ask for output matching a JSON schema
- turn off the model's thinking mode when the model supports it
- ask the server to keep the model loaded while queued work remains

A response that is not valid JSON for the schema SHALL count as a failed step, not as an empty result. Embedding requests SHALL send only the embedding model and the texts, and a response without one vector per text SHALL count as a failed step.

#### Scenario: Model default temperature ignored
- **WHEN** the selected model's own default temperature is 1
- **THEN** extraction requests still use temperature 0

#### Scenario: Malformed response
- **WHEN** the server returns text that does not parse as JSON matching the schema
- **THEN** that step fails with an error naming the step, and no items from that step are stored

#### Scenario: Short embedding response
- **WHEN** an embedding request for 20 skill names returns 19 vectors
- **THEN** that step fails with an error, and no embeddings from it are stored

### Requirement: Background job queue
Model work SHALL be added to a queue stored in the database and processed one job at a time, outside the request, oldest first. A job SHALL be one of: extracting a posting, extracting a document, or judging links. Posting extraction SHALL be queued only when the user requests it. Document extraction SHALL be queued when the user requests it or uploads a CV (see "Adding a document to the profile"), and link judging when the user requests it or skills change (see "Re-judging when skills change"). The interface SHALL show each queued job's subject (a posting, a document, or skill links) and state: queued, running, done, failed or cancelled. Failed jobs SHALL show their error. The user SHALL be able to cancel queued jobs. Cancelling a running job SHALL stop it before its next step. Nothing from a cancelled posting or document extraction SHALL be stored. A cancelled link-judging job SHALL keep the judgments it finished before stopping. Jobs that were running when `serve` stopped SHALL be queued again at the next start. While the server is unreachable, queued jobs SHALL wait rather than fail. Queue processing SHALL run only while `serve` runs, and SHALL do nothing except call the configured Ollama address and store results.

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

#### Scenario: Mixed kinds in order
- **WHEN** a posting extraction is queued, then a CV is uploaded, which queues a document extraction, and that extraction's merge queues link judging
- **THEN** the jobs run in that order, and the queue shows a posting, a document and "skill links" as their subjects

#### Scenario: Cancelling link judging midway
- **WHEN** the user cancels a running link-judging job after 40 of 120 posting skills were judged
- **THEN** the 40 judgments are kept and take effect, and the rest are judged by the next judging job
