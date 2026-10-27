## 0. Before starting

- [x] 0.1 Archive `add-recommendations` (`openspec archive add-recommendations`), so that `openspec/specs/recommendations/spec.md` exists for this change's MODIFIED "Skill recommendations". Verify that `openspec list --specs` shows `recommendations`.

## 1. Pooling (`src/jobhunt/recommend.py`)

- [x] 1.1 Add `POOL_SIMILARITY = 0.90`, `POOL_NAME_SIMILARITY = 0.80` and a pure pooling function from D1/D2. It takes keys with their posting counts and display names, and unit vectors by key. It returns each key's leader. Similarity uses `math.sumprod`, and the name-containment word rule is the one in D2. Verify with new tests in `tests/test_recommend.py`, using small vectors built from angles to give exact cosines, covering:
  - "One name inside another" (`fine-tuning` and `LLM fine-tuning` at 0.857)
  - "Similar names" (`Azure` and `Microsoft Azure` at 0.957)
  - "A shared word is not enough" (`Planning` and `Sprint planning` at 0.78)
  - "Pools don't chain" (`Containers` starts its own pool)
  - a key without a vector alone
  - equal word lists (`Fine tuning`/`fine-tuning`, `Knowledge graph`/`Knowledge graphs`) pooled
  - ordering: most asked first, then shorter name, then key
- [x] 1.2 Give `skill_gains` an optional `vectors` argument. It pools the unlinked keys it collects and makes one candidate per pool: `key` and `name` from the leader, `also` with the other members' names (most asked first), and every member credited `HAVE`. Profile-skill candidates stay as they are. Verify with tests:
  - the `fine-tuning` pool's gain counts the postings of both names, and its `also` is `["LLM fine-tuning"]`;
  - "Linked skills are not pooled";
  - with `vectors=None` every existing `test_recommend.py` test passes unchanged.

## 2. Loading

- [x] 2.1 Add `queries.latest_embed_model(conn)`: the `embed_model` of the newest succeeded `link_judgments` row, or `None`. In `recommend.recommendations`:
  - read that model's vectors with `links.stored_vectors`;
  - unit-normalize the ones for unlinked keys;
  - pass them to `skill_gains`.

  Verify with database tests in `tests/test_recommend.py`:
  - vectors stored through `derived.save_embeddings` plus one stored judgment pool two marked variants into one recommended skill;
  - with no judgment ("No stored embeddings"), nothing is pooled;
  - row counts across user, derived and operational tables are unchanged.

## 3. Page

- [x] 3.1 In `insights.html`, show a pool's other names under its name ("also: …", muted, small). Verify with a `tests/test_web.py` test: the pooled row lists `also` names, and an unpooled row has none.
- [x] 3.2 Verify "Answering a pool" with a `tests/test_web.py` test. "Don't have it" on the pool posts the leader's name; afterwards, the leader is in the profile at `missing`, a links job is queued, and the other member is a candidate of its own. This needs no route change.

## 4. Check and docs

- [x] 4.1 Check against the user's real database with a read-only connection and `create_app(..., ollama=None)`. Don't use `jobhunt serve`, don't trigger any model work, and confirm that the database file's checksum is unchanged. Render `/insights` and time the page load. Report to the user:
  - the pooled top 15 with each pool's members;
  - where `fine-tuning` lands;
  - the load time;
  - any pool in the top 15 that looks wrong.
- [x] 4.2 Update the docs:
  - CLAUDE.md: the "Match score and recommendations" bullet (pooling rule, constants, vectors from the newest judgment's model, scores unchanged);
  - FUTURE_CHANGE.md: section 2 notes pooling as delivered, and the unfixed pool errors as a follow-up.

  Run `pytest`, and `JOBHUNT_TEST_PG_URL=postgresql+psycopg:///jobhunt_test pytest`, and `openspec validate pool-unlinked-skills --strict`, and verify all pass.
