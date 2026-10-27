## Why

Skill recommendations on Insights treat each unlinked posting skill as its own candidate. Variant names of one skill therefore split its demand. `fine-tuning` (#11, +15.0, 9 postings) and `LLM fine-tuning` (#13, +13.8, 4 postings) are listed as two skills to learn, and neither shows the skill's whole weight. A pooling check on the user's database (2026-10-06, stored data only) found that the effect is mostly on skill recommendations; match scores rise by about 1 point on average. Pooled, `fine-tuning` moves to #5 (+31.7, 12 postings), the `Azure` family rises from +25.5 to +58.1, and pools such as `APIs` and `Testing`, whose members are each too small to list, rise into the top 15.

## What Changes

- **Unlinked posting skills are pooled for skill recommendations.** Similar unlinked skills form one candidate, named after the member asked for in the most postings. Its gain counts every posting that asks for any member. Two skills share a pool when:
  - their stored name embeddings are very similar (cosine ≥ 0.90), or
  - one name's words appear whole in the other's (`fine-tuning` in `LLM fine-tuning`) and their cosine is at least 0.80.

  Each member is compared with the pool's first member, never with another member, so pools don't chain into topics. With no stored embeddings, nothing is pooled and recommendations are as today.
- **A pooled row lists its other names** ("also: LLM fine-tuning, Model fine-tuning"). "Have it" and "Don't have it" act on the pool's name, as for any unlinked skill today. The other names then reach that profile skill through link judging, as `add-recommendations` already does for variants of a `missing` skill.
- **Nothing else changes.** Match scores, posting recommendations, links and the linking method stay as they are. Pools are computed when the page is opened, from stored embeddings, so the page makes no model requests and nothing new is stored.

Not in this change:
- correcting a wrong pool by hand (pools are visible, and answering one sends its members to link judging, which can refuse them);
- pooling with a model judge;
- pooling in match scores or posting gaps;
- pooling profile skills (near-duplicates from CV merges stay a manual clean-up).

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `recommendations` (added by `add-recommendations`, to be archived before this change): "Skill recommendations" pools similar unlinked posting skills into one candidate and shows its other names.

## Impact

- `src/jobhunt/recommend.py`: a pure pooling function, its two thresholds as constants, pooled candidates in `skill_gains`, and the embedding model and vectors loaded in `recommendations`.
- `src/jobhunt/queries.py`: one read for the embedding model of the newest succeeded link judgment. Vectors are read through the existing `links.stored_vectors`.
- `src/jobhunt/web/templates/insights.html`: a pool's other names on its row.
- Tests: `tests/test_recommend.py` (pooling scenarios with explicit vectors, plus a database case) and `tests/test_web.py` (the "also" names).
- No schema change, migration, setting, model request or dependency. Pooling adds up to about a second to an Insights page load at today's size (about 520 unlinked skills, 768-dimension vectors, pure Python).
- Docs: CLAUDE.md ("Match score and recommendations") and FUTURE_CHANGE.md.
