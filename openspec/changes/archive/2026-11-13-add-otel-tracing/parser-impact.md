# Parser impact: add-otel-tracing

**Impact: none.** The change adds spans around model work (extraction, document reading, link judging, embeddings) and two start-up options on `serve` and `eval`. Importing isn't traced, and nothing about how parsers are found, called or what they return changes, so a parser that does nothing sees no difference.
