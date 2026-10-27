## MODIFIED Requirements

### Requirement: Model settings
A settings page SHALL let the user choose:
- the model used for extraction and link judging, from the models installed on the server. Models that cannot generate text, such as embedding-only models, SHALL be excluded.
- the context size sent with each request, defaulting to 8192 tokens
- the segmentation method, from the methods the system provides
- the embedding model used to shortlist link candidates, from the installed models that can produce embeddings, defaulting to `nomic-embed-text` when it is installed

The skill extraction method SHALL NOT be a setting: the app uses the one the code names (see "Step-wise extraction with replaceable steps" in `posting-enrichment`). Settings SHALL be stored in the database and survive restarts. The settings page SHALL show the configured Ollama address read-only. While the server is offline, the settings page SHALL show the stored values and explain that the model list is unavailable. While no embedding model is chosen or installed, link judging SHALL wait and the links page SHALL say why.

#### Scenario: Choosing a model
- **WHEN** the server has `gemma4:12b`, `phi4:latest` and `nomic-embed-text:latest` installed and the user opens settings
- **THEN** the model choices are `gemma4:12b` and `phi4:latest`, and after choosing `gemma4:12b` and restarting `serve` it is still selected

#### Scenario: Choosing a skill extraction method
- **WHEN** the system registers the app's method `atomic@2` and a candidate `atomic@5`, and the user opens settings
- **THEN** the page offers no skill extraction method to choose

#### Scenario: Unknown method rejected
- **WHEN** a settings request names the skill extraction method `atomic@5`
- **THEN** no setting is changed, and the page says that the skill extraction method is not a setting

#### Scenario: Choosing an embedding model
- **WHEN** the server has `gemma4:12b` and `nomic-embed-text:latest` installed and no embedding model was ever chosen
- **THEN** the embedding model choices are `nomic-embed-text:latest` only, and it is selected
