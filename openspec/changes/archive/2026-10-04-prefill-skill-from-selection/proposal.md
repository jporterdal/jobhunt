## Why

Marking a skill on a posting starts with selecting text in the description, and very often the selected text *is* the skill's name ("Python programming", "Kubernetes"). Today the "Mark skill" popup opens with an empty skill box, so the user retypes what they just selected. That costs time and causes typos, and it matters most during labelling, when the user marks every skill on 5–10 postings in a row.

## What Changes

- When the user selects description text and the "Mark skill" popup opens, the skill name box is pre-filled with the selected text. Surrounding whitespace is trimmed, and runs of whitespace inside it (for example a line break between list items) become single spaces. Otherwise the text is exactly as written, including letter case and punctuation.
- The user can edit the pre-filled name before submitting, or submit it unchanged. Matching against existing skills is unchanged: names are still trimmed and compared case-insensitively, so a selection whose text matches an existing skill attaches to that skill.
- If the user selects different text while the popup is open, the name box follows the new selection, but only when the user hasn't typed in it since it was filled. A name the user typed is never overwritten.
- No server, database or migration changes. The stored quote and the form fields are unchanged.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `posting-triage`: the "Skills marked from description text" requirement adds that the skill name is pre-filled from the selection and stays editable.

## Impact

- `src/jobhunt/web/static/marks.js`: the selection handler fills `input[name=skill]` alongside the hidden `quote` field.
- No change to `detail.html`, `triage.py`, `userdata.py`, the schema or `PARSER_VERSION`.
- There is no JavaScript test harness. The existing `test_web.py` check that the page loads `marks.js` still covers wiring, and the behavior is checked by hand in a browser.
