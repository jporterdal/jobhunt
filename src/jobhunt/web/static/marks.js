// Skill marks on the posting detail page (design D7):
//  - highlight every stored quote in the description, matching case-insensitively with whitespace collapsed,
//    with a class for the mark's importance (required, preferred);
//  - when the user selects description text, offer a small "Mark skill" form that posts the selection.
(function () {
  "use strict";

  const description = document.getElementById("description");
  const popup = document.getElementById("mark-popup");
  const data = document.getElementById("mark-quotes");
  if (!description || !popup || !data) return;

  const collapse = (s) => s.replace(/\s+/g, " ").trim();

  // The description as one string of collapsed, lower-cased text, with a map from each of its
  // characters back to (text node, offset), so a match can be turned back into a DOM range.
  function indexText(root) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const chars = [];
    const map = [];
    let lastWasSpace = true;
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const text = node.nodeValue;
      for (let i = 0; i < text.length; i++) {
        const isSpace = /\s/.test(text[i]);
        if (isSpace && lastWasSpace) continue;
        chars.push(isSpace ? " " : text[i].toLowerCase());
        map.push([node, i]);
        lastWasSpace = isSpace;
      }
      // Block boundaries read as a space, as BeautifulSoup's get_text(" ") does on the server.
      if (!lastWasSpace) {
        chars.push(" ");
        map.push(null);
        lastWasSpace = true;
      }
    }
    return { text: chars.join(""), map };
  }

  function rangesFor(quote) {
    const needle = collapse(quote).toLowerCase();
    if (!needle) return [];
    const { text, map } = indexText(description);
    const ranges = [];
    let from = 0;
    for (let at = text.indexOf(needle, from); at !== -1; at = text.indexOf(needle, from)) {
      let start = at;
      let end = at + needle.length - 1;
      while (start <= end && !map[start]) start++;
      while (end >= start && !map[end]) end--;
      if (start <= end) ranges.push([map[start], map[end]]);
      from = at + needle.length;
    }
    return ranges;
  }

  // Wrap each text-node piece of a match separately, so matches across <strong> or <li> stay valid HTML.
  function highlight(startPoint, endPoint, importance) {
    const [startNode, startOffset] = startPoint;
    const [endNode, endOffset] = endPoint;
    const walker = document.createTreeWalker(description, NodeFilter.SHOW_TEXT);
    const pieces = [];
    let inside = false;
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      if (node === startNode) inside = true;
      if (inside) {
        const a = node === startNode ? startOffset : 0;
        const b = node === endNode ? endOffset + 1 : node.nodeValue.length;
        if (b > a) pieces.push([node, a, b]);
      }
      if (node === endNode) break;
    }
    for (const [node, a, b] of pieces) {
      const range = document.createRange();
      range.setStart(node, a);
      range.setEnd(node, b);
      const mark = document.createElement("mark");
      if (importance) {
        mark.className = importance;
        mark.title = importance;
      }
      range.surroundContents(mark);
    }
  }

  // Collect every match first: wrapping changes the text nodes the later matches point into.
  let quotes = [];
  try {
    quotes = JSON.parse(data.textContent);
  } catch (e) {
    quotes = [];
  }
  for (const { quote, importance } of quotes) {
    for (const [start, end] of rangesFor(quote).reverse()) highlight(start, end, importance);
  }

  // Selecting text offers the "Mark skill" form next to the selection.
  const quoteInput = popup.querySelector("input[name=quote]");
  const quotePreview = popup.querySelector(".quote");
  const skillInput = popup.querySelector("input[name=skill]");
  const unspecified = popup.querySelector("input[name=importance][value='']");
  // The skill name is pre-filled from the selection; once the user types in it, reselecting keeps their text.
  let skillTyped = false;
  skillInput.addEventListener("input", () => { skillTyped = true; });

  function hide() {
    popup.classList.add("hidden");
  }

  document.addEventListener("mouseup", (event) => {
    if (popup.contains(event.target)) return;
    const selection = window.getSelection();
    const text = selection ? collapse(selection.toString()) : "";
    if (!text || selection.rangeCount === 0 || !description.contains(selection.getRangeAt(0).commonAncestorContainer)) {
      hide();
      return;
    }
    const rect = selection.getRangeAt(0).getBoundingClientRect();
    quoteInput.value = text;
    quotePreview.textContent = "“" + (text.length > 160 ? text.slice(0, 157) + "…" : text) + "”";
    popup.style.left = window.scrollX + rect.left + "px";
    popup.style.top = window.scrollY + rect.bottom + 6 + "px";
    const opening = popup.classList.contains("hidden");
    if (opening && unspecified) unspecified.checked = true;
    const prefill = opening || !skillTyped;
    if (prefill) {
      skillInput.value = text;
      skillTyped = false;
    }
    popup.classList.remove("hidden");
    skillInput.focus({ preventScroll: true });
    if (prefill) skillInput.select();
  });

  popup.querySelector("[data-action=cancel]").addEventListener("click", hide);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") hide();
  });
})();
