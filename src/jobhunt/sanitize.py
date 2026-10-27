"""Reduce any parser's description HTML to a small allowlist, and derive its plain text.

The store runs `clean_html` on every accepted posting, so whatever a parser returns is rendered only through
this allowlist. `clean_html` is idempotent: cleaning cleaned HTML leaves it unchanged.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, Comment, NavigableString

ALLOWED_TAGS = {"p", "br", "ul", "ol", "li", "strong", "b", "em", "i", "u", "a", "h1", "h2", "h3", "h4", "h5", "h6"}
BLOCK_TAGS = {"p", "div", "ul", "ol", "li", "h1", "h2", "h3", "h4", "h5", "h6"}
REMOVED_TAGS = ("script", "style", "button")
LINK_SCHEMES = {"http", "https", "mailto"}


def safe_href(href: str | None) -> str | None:
    """The address, if it is an absolute http, https or mailto address; None for anything else."""
    if not href:
        return None
    href = href.strip()
    try:
        scheme = urlsplit(href).scheme.lower()
    except ValueError:
        return None
    return href if scheme in LINK_SCHEMES else None


def clean_html(html: str) -> str:
    """The HTML with only allowlisted tags, no comments, and no attributes except a link's safe address."""
    fragment = BeautifulSoup(html, "html.parser")
    for comment in fragment.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()
    for tag in fragment.find_all(REMOVED_TAGS):
        tag.decompose()
    for tag in fragment.find_all(True):
        if tag.name not in ALLOWED_TAGS:
            tag.unwrap()
            continue
        href = safe_href(tag.get("href")) if tag.name == "a" else None
        tag.attrs = {"href": href} if href else {}
    return fragment.decode().strip()


def html_to_text(html: str) -> str:
    """Plain text with one line per paragraph, line break or list item; list items start with "- "."""
    # As in a browser, source whitespace is just a space; only block edges and <br> break lines.
    # Markers keep the two apart until adjacent block edges have been merged.
    block, brk, bullet = "\x00", "\x01", "\x02"
    parts: list[str] = []

    def walk(node) -> None:
        for child in node.children:
            if isinstance(child, Comment):
                continue
            if isinstance(child, NavigableString):
                parts.append(re.sub(r"\s+", " ", str(child).replace("\xa0", " ")))
            elif child.name == "br":
                parts.append(brk)
            elif child.name in REMOVED_TAGS:
                continue
            elif child.name in BLOCK_TAGS:
                parts.append(block + bullet if child.name == "li" else block)
                walk(child)
                parts.append(block)
            else:
                walk(child)

    walk(BeautifulSoup(html, "html.parser"))
    text = "".join(parts)
    text = re.sub(f" *{block}[ {block}]*", block, text)  # adjacent block edges are one line break
    text = re.sub(f"{bullet}[ {block}{brk}]*", bullet, text)  # "- " sits on the item's first line
    text = text.replace(block, "\n").replace(brk, "\n").replace(bullet, "- ")
    text = "\n".join(line.strip() for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()
