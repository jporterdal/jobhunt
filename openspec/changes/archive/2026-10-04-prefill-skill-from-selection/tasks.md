## 1. Pre-fill the skill name

- [x] 1.1 In `src/jobhunt/web/static/marks.js`, add a `skillTyped` flag set by an `input` listener on `skillInput`. In the `mouseup` handler, when the popup was hidden or `skillTyped` is false, set `skillInput.value` to the collapsed selection and clear the flag. Verify that `pytest tests/test_web.py` still passes.
- [x] 1.2 After `skillInput.focus({ preventScroll: true })`, call `skillInput.select()` so Enter accepts the default and typing replaces it. Verify in the browser that pressing Enter right after selecting marks the skill under the selected name.

## 2. Verify in the browser

- [x] 2.1 Run `jobhunt serve` against a database with at least one posting and walk through the delta spec scenarios on its detail page: a padded selection gives a trimmed name, accepting unchanged, editing to `PyTorch`, a selection matching an existing skill in a different case attaches to that skill, a selection spanning two list items gives a single-spaced name, reselecting without typing updates the name, reselecting after typing keeps the typed name. Confirm each by the posting's marks list and highlights.
- [x] 2.2 Check that importance handling and Cancel/Escape behave as before: importance resets only when the popup opens from hidden, and Cancel or Escape hides the popup.

## 3. Wrap up

- [x] 3.1 Run `openspec validate prefill-skill-from-selection --strict` and the full `pytest` suite. Both pass.
