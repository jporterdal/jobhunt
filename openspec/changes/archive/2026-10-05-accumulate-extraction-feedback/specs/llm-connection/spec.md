## MODIFIED Requirements

### Requirement: Model settings
A settings page SHALL let the user choose:
- the model used for extraction, from the models installed on the server. Models that cannot generate text, such as embedding-only models, SHALL be excluded.
- the context size sent with each request, defaulting to 8192 tokens
- the segmentation method, from the methods the system provides
- the skill extraction method, from the methods the system provides, each shown by name and version, defaulting to `atomic@2`

Settings SHALL be stored in the database and survive restarts. The settings page SHALL show the configured Ollama address read-only. While the server is offline, the settings page SHALL show the stored values and explain that the model list is unavailable. A stored skill extraction method that the system no longer provides SHALL be shown as unavailable, and extraction SHALL use the default until the user chooses another.

#### Scenario: Choosing a model
- **WHEN** the server has `gemma4:12b`, `phi4:latest` and `nomic-embed-text:latest` installed and the user opens settings
- **THEN** the model choices are `gemma4:12b` and `phi4:latest`, and after choosing `gemma4:12b` and restarting `serve` it is still selected

#### Scenario: Choosing a skill extraction method
- **WHEN** the user opens settings on a database where no skill extraction method was ever chosen, and chooses `atomic@4`
- **THEN** the choices are `atomic@2` and `atomic@4`, `atomic@2` is selected before the change, and after restarting `serve` `atomic@4` is still selected

#### Scenario: Unknown method rejected
- **WHEN** a settings request names the skill extraction method `atomic@3`
- **THEN** the setting is not changed and the page says which methods are available
