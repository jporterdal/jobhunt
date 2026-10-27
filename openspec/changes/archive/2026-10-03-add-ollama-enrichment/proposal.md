## Why

Marking skills and noting salary by hand doesn't scale past a few dozen postings, and the analysis goals (which skills the preferred postings ask for, and how pay varies) need that data for every posting. A local Ollama server with a GPU is now available. It can make these suggestions privately, with no data leaving the machine, provided the output is checked against the posting text and the user stays in control of what becomes their own data.

Exploration on real postings showed that a single call returning salary, required skills and preferred skills is unreliable on 7–14B models. Results changed sharply with prompt wording, models often returned empty lists, and one posting listed two salary ranges in different currencies. The design therefore splits the work into small, replaceable steps, checks every result against the text, and adds a measurement loop from the start.

## What Changes

- **Ollama connection.** `jobhunt serve` gains `--ollama-url` (default `$JOBHUNT_OLLAMA_URL` or `http://localhost:11434`). Model features appear only while the server is reachable; the rest of the app is unaffected when it is down. A status badge shows offline, online with the selected model, or a warning when the model is partly running on the CPU.
- **Settings page.** Choose the model from those installed (embedding-only models excluded), the context size and the segmentation method. Stored in a new settings table.
- **Background job queue.** Extraction requests go into a database queue processed by one worker thread inside `serve`, with progress shown through htmx and a cancel action. Queued jobs survive restarts.
- **Modular extraction pipeline**, replaceable step by step:
  - A *segmenter* splits the description into labelled spans (required, preferred, other), identified by character offsets into the original text. It is chosen by name; this change ships a rule-based segmenter and an LLM line classifier.
  - A *skill extractor* turns required and preferred spans into atomic skills, each with a short name, a kind and a verbatim quote.
  - A *salary extractor* runs only on lines a pattern identifies as mentioning pay. It returns a list of ranges, each with currency, period, location and quote.
  - A *validator* (pure Python) checks that every quote occurs in the text and every salary number occurs in its quote. Unverified items are kept but flagged.
- **Derived storage.** Adds `posting_enrichments` (one run per snapshot, model and pipeline version, with step outputs), `enrichment_skills` and `enrichment_salaries`. Derived rows are never edited.
- **"Model says" panel** on the posting detail page, plus a salary summary in the posting list. The panel shows salary ranges and required and preferred skills, and flags runs made on an older snapshot. The user can accept an item, which creates a skill mark, or reject it, which hides it on later runs as well.
- **Skill marks gain importance and origin.** A mark records `required` or `preferred` (optional), and whether it came from a selection or an accepted suggestion. The mark popup lets the user choose the importance.
- **Labelling and evaluation.** The user can flag a posting's skill marks as complete, which builds a labelled set. A new `jobhunt eval` command runs the pipeline on that set and reports precision and recall per model and pipeline. For each missed skill it also reports which step lost it, segmentation or extraction, so the step to improve is clear. Postings labelled without accepted suggestions are reported separately from reviewed ones.
- No new Python dependencies: the Ollama client uses the standard library.

Out of scope, planned for the next change (`add-cv-skill-profile`): ODT text extraction, CV skill extraction, primary-CV selection, skill aliases with embedding-suggested merges, and match scores.

## Capabilities

### New Capabilities
- `llm-connection`: connecting to a local Ollama server, availability and GPU status, model settings, and the background job queue that runs model work.
- `posting-enrichment`: the modular extraction pipeline (segmenter, extractors, validator), derived-data storage and versioning, and reviewing suggestions in the web interface.
- `enrichment-evaluation`: the labelled set of postings and the `jobhunt eval` command that measures extraction quality.

### Modified Capabilities
- `posting-triage`: skill marks gain an optional importance (required or preferred) and an origin (selection or accepted suggestion); the user can flag a posting's skill labelling as complete; rejected suggestions are user-authored triage data that re-capture and re-extraction leave unchanged.

## Impact

- **Code.** New package `src/jobhunt/enrich/`: Ollama client, pipeline steps, derived-data writer, job queue and worker, and evaluation. New web blueprint for the status badge, settings, queue and suggestion review. Changes to `db.py`, `userdata.py` (marks, settings, rejections, labelled flag), `queries.py`, `cli.py` (`--ollama-url`, `eval`), the detail and list templates, `marks.js` and the mark popup.
- **Schema.** Alembic revision `0003`, which:
  - adds `app_settings`, `llm_jobs`, `posting_enrichments`, `enrichment_skills`, `enrichment_salaries` and `rejected_suggestions`
  - adds `importance` and `origin` to `posting_skill_marks`
  - adds `skills_complete_at` to `posting_triage`
  
  Existing marks get origin `selection` and no importance.
- **Runtime.** `serve` starts one worker thread (not in the debug reloader's parent process). It sends HTTP requests only to the configured Ollama URL, which is fixed at startup and cannot be changed from the browser.
- **Docs.** CLAUDE.md architecture, data kinds, commands and settings.
