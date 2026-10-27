## Context

The "Mark skill" popup is the `#mark-popup` form in `postings/detail.html`. Its `mouseup` handler in `static/marks.js` reads the selection, runs `collapse()` on it (whitespace runs become single spaces, then the result is trimmed), stores that in the hidden `quote` input, shows a preview, positions the popup and focuses the empty `skill` input. Importance is reset to "unspecified" only when the popup opens from hidden, so it survives reselecting while the form is open. The server (`triage.add_mark` → `userdata`) already trims skill names and matches them case-insensitively.

## Goals / Non-Goals

**Goals:**
- Pre-fill the skill name from the same text that becomes the quote, so the two always agree.
- Make "accept as is" a single keypress, and replacing the name just as easy.
- Never discard a name the user typed.

**Non-Goals:**
- Normalising, shortening or spell-correcting the selection (for example removing "experience with"). The text stays as written.
- Suggesting a skill from the model, or picking an existing skill automatically. The datalist and server-side matching stay as they are.
- Opening the popup from keyboard-only selections. Today it opens only on `mouseup`, and that doesn't change.

## Decisions

**Fill from `collapse(selection)`, the value already used for the quote.** This gives "trimmed, otherwise as written" with case and punctuation kept. A selection across `<li>` boundaries contains newlines, which a single-line `<input>` would strip or mangle, so collapsing them to spaces is the only sensible single-line form. *Alternative:* trim only the ends. Rejected because a two-line selection would then differ between the quote and the name.

**Select the pre-filled text when focusing.** After `focus()`, call `skillInput.select()`. Enter then submits the default, typing replaces it entirely, and an arrow key or click places the cursor to edit it. This is the usual pattern for rename dialogs. *Alternative:* put the cursor at the end. Rejected because replacing a long selection would then mean clearing it by hand.

**Track "typed since filled" with a flag, not with popup visibility.** A `skillTyped` flag is cleared each time the script fills the box and set by the input's `input` event. On `mouseup` with a valid selection, the box is filled when the popup was hidden (a new marking always starts fresh) or when `skillTyped` is false. *Alternative:* reuse the importance rule and fill only when opening from hidden. Rejected because reselecting to fix a sloppy selection would leave the name of the earlier selection. *Alternative:* always overwrite. Rejected because it discards typing.

## Risks / Trade-offs

- [Long selections, such as a whole sentence, produce a long default name] → The text is selected on focus, so typing replaces it at once. Nothing is saved until the user submits.
- [Accepting without looking creates near-duplicate skills ("Python programming" vs "Python")] → The datalist still suggests existing skills as the user types. Spotting duplicates is the user's call, as it is today.
- [No automated JavaScript tests] → Verify by hand against the spec scenarios in a browser. Server-side behavior is unchanged and already tested.
