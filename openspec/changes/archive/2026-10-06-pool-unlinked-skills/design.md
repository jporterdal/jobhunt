## Context

See proposal.md for why. What the change builds on:

- `recommend.skill_gains` (from `add-recommendations`) makes every posting key without a link option a candidate of its own, crediting it `same` × `proficient` (0.85) wherever it is asked for.
- Link judging stores a vector for every posting skill name and every profile skill name in `skill_embeddings`, keyed by `(model, text_key)` (`derived.save_embeddings`). `links.stored_vectors(conn, model)` reads them, and `link_judgments.embed_model` records the model each judgment used. On the user's database, all 522 unlinked keys have a `nomic-embed-text:latest` vector.
- `link_judgments`' shortlist floor is 0.75: once a pool's name becomes a profile skill, members at cosine ≥ 0.80 to it reach that skill's shortlist.
- Python 3.13 has `math.sumprod`, which takes a dot product of two 768-float lists at C speed. numpy isn't a dependency, and this change doesn't add it.

### Smoke tests (2026-10-06, user's database, stored vectors only, no model requests)

Each method was run over the 522 unlinked keys of the 40 considered postings, and the pooled top 15 was read by hand.

| Method | Pools (2+ members) | Largest | Finding |
|---|---|---|---|
| Embedding, any-pair chaining, ≥ 0.85 | 56 | 169 | One topic blob (`Anthropic` with `AI evaluation`) |
| Name containment, any-pair chaining | 36 | 76 | Blobs through generic words (`Architecture`, `Planning`) |
| Embedding, any-pair chaining, ≥ 0.90 | 61 | 10 | Sensible, but `LLM fine-tuning` pooled with `LLM`, not `fine-tuning` |
| Embedding, complete linkage, ≥ 0.86 / 0.88 | 113 / 93 | 5 / 4 | Small pools; `fine-tuning` still split |
| Embedding, leader, ≥ 0.86 / 0.88 / 0.90 | 94 / 83 / 69 | 11 / 8 / 5 | `fine-tuning` still split |
| **Leader: embedding ≥ 0.90, or name containment with ≥ 0.80** | 72 | 12 | `fine-tuning` pooled (+31.7, 12 postings); chosen |

Name embeddings weigh the modifier word heavily. `fine-tuning`~`LLM fine-tuning` is 0.857 while `LLM`~`LLM fine-tuning` is 0.906, so no embedding threshold alone pools the motivating example. Name containment catches it, and the 0.80 floor removes some containment pools that are only topical (`transformer architectures` under `Architecture`).

By my reading, about 8 of the chosen method's 72 pools are wrong (`Microsoft Graph API` under `Graph database`, `AI security` under `AI safety`, `Deployment models` under `Model deployment`, `Learning from human feedback` under `Feedback`) and about 8 are too broad (generic first members: `Integrations` holding `Continuous integration`, `Design`, `Architecture`, `Security`, `Planning`). The rest look right: `Azure` family, `AWS`, `Monitoring`, `fine-tuning`, `Agile`, `Data quality`, `Spark`/`Apache Spark`, `Containerisation`/`Containerization`, `Knowledge graph(s)`, `UrbanCodeDeploy` spellings.

## Goals / Non-Goals

**Goals:**
- Pooling is one pure function in `recommend.py`, tested with small explicit vectors, with its two thresholds as constants beside the other weights.
- No new tables, migration, setting or model request. Without stored vectors, the output is exactly today's.

**Non-Goals:**
- Measuring pooling against a labelled reference. There is none, and the user corrects pools by answering them (D5).
- Pools on the posting list, the posting page or the links page.

## Decisions

### D1. Leader pooling over the unlinked keys, most asked first

- Keys are ordered by the number of considered postings asking for them (descending), then name length, then key.
- Each key is compared only with the first member (the leader) of each existing pool. It joins the qualifying pool with the highest cosine, or else starts a pool.
- Comparing with leaders only keeps pools from chaining: every member is close to the pool's name, which is what the row shows and what an answer adds to the profile.
- The most asked leader names the pool. That is usually the general form (`Azure`, `fine-tuning`, `Testing`). Sometimes it is a narrower name that happens to be asked more (`Google Cloud AI` over `Google Cloud`).
- *Alternatives:* any-pair chaining (union-find), which forms blobs (see the smoke tests), and complete linkage, which is safe but too strict to pool `fine-tuning` and is slower.

### D2. The qualifying rule: embedding ≥ 0.90, or name containment with ≥ 0.80

- `POOL_SIMILARITY = 0.90` and `POOL_NAME_SIMILARITY = 0.80` are constants at the top of `recommend.py`.
- **Name containment:** the leader's words, in order, are a contiguous run of the key's words. Words come from the key (`name_key` is already casefolded), split on anything not a letter or digit (so `fine-tuning` is `fine tuning`). A trailing `s` is dropped from words longer than three letters that don't end in `ss`. Equal word lists count as containment, which pools `Fine tuning`/`fine-tuning` and `Knowledge graph`/`Knowledge graphs`.
- *Alternative:* containment alone. It pools `Continuous integration` with `Integrations` and `transformer architectures` with `Architecture`. The 0.80 floor removes the second and keeps most of the useful ones.

### D3. Where it runs

- `skill_gains(..., vectors=None)` takes unit vectors by key. It pools the unlinked keys it already collects, then builds one candidate per pool, crediting `HAVE` to every member: `changed = {member: have for member in pool}`.
- The candidate dict keeps `key` (the leader's), `name` (the leader's display name), and gains `also`: the other members' names, most asked first.
- Profile-skill candidates are unchanged.
- `recommendations(conn)`:
  1. reads the embedding model of the newest succeeded link judgment (a small `queries.latest_embed_model(conn)`, returning `None` with none);
  2. reads that model's vectors with `links.stored_vectors`;
  3. unit-normalizes the ones for unlinked keys and passes them in.
  
  Pure tests call `skill_gains` with hand-made vectors.
- **Cost:** about `n × leaders` dot products. Measured at 1.4 s for 270,000 products with `math.sumprod`; the real case is under half that (522 keys against about 450 leaders, averaging half of them). Acceptable for a page opened by hand. Caching can come later if it isn't.
- *Alternative:* the current embedding setting (`llm.embed_model`). With nothing chosen, that needs the installed models list from Ollama, and the page must work with Ollama down. The newest judgment's model is the one whose vectors are known to exist.

### D4. Scores stay per posting skill

Pooling a posting's own variants would raise its score (about +1.4 points on average in the smoke test, top 5 unchanged). It would also change the score definition, the gaps and the "X of N unlinked" count. It is left out to keep this change to skill recommendations.

### D5. Answers act on the pool's name; link judging does the rest

- "Have it" and "Don't have it" on a pool post its leader's name, as today. That key becomes a profile skill with a same-key link.
- The other members are unlinked until the queued link judging judges them against it. Meanwhile, they pool among themselves as usual.
- The judge confirms members it relates to the new skill (they then count under it as a profile-skill candidate, through `options`). Members it refuses stay apart.
- So a wrong pool corrects itself once answered, with no new correction UI.

## Risks / Trade-offs

- **About 1 in 9 pools is wrong, and about 1 in 9 too broad** (D2 smoke test). → Every row shows its other names, so the user sees the pool before acting on it. Answering sends members to the judge (D5). A model-judged pooler or hand corrections are later changes if this proves too noisy.
- **Generic leaders** (`Design`, `Architecture`) can rank highly by absorbing many compounds. → They are visible with their members. Weighting soft or generic skills down is already a later round in FUTURE_CHANGE.md.
- **The thresholds are tuned on one database**, like the link shortlist floor. → They are constants, and the real-database check in the tasks reports the pools that reach the top 15.
- **Page load cost** rises by up to about a second. → Measured in the tasks. Caching the pooling by (model, keys) is the fallback.
- **Members without a vector** (a new posting skill before its first link judging) sit alone. → They are pooled after the next links job, which runs after any successful posting run.

## Migration Plan

No schema change. Deploying is the code change, and rolling back is reverting it.

`add-recommendations` must be archived first, so that `openspec/specs/recommendations/spec.md` exists for this change's MODIFIED requirement.
