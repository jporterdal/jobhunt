import json
from pathlib import Path

import pytest

from jobhunt.sanitize import clean_html, html_to_text

POSTINGS = Path(__file__).parent / "fixtures" / "postings"


def test_unsafe_markup_is_removed():
    html = (
        '<div onclick="steal()"><p class="x">Hi <a href="javascript:alert(1)" onclick="x()">click</a></p>'
        "<script>alert(1)</script><style>p{}</style><!-- note --><button>More</button></div>"
    )
    assert clean_html(html) == "<p>Hi <a>click</a></p>"


@pytest.mark.parametrize("href, kept", [
    ("https://example.com/a?b=1", True),
    ("http://example.com", True),
    ("mailto:jobs@example.com", True),
    ("  HTTPS://example.com  ", True),
    ("/relative/path", False),
    ("page.html", False),
    ("#top", False),
    ("javascript:alert(1)", False),
    ("JaVaScRiPt:alert(1)", False),
    ("java\tscript:alert(1)", False),
    ("data:text/html,<b>x</b>", False),
    ("vbscript:x", False),
])
def test_links_keep_only_http_https_and_mailto(href, kept):
    cleaned = clean_html(f'<a href="{href}" target="_blank">text</a>')
    assert ("href=" in cleaned) == kept
    assert "text" in cleaned and "target" not in cleaned


def test_list_with_emoji():
    html = "<ul><li>Python 🐍</li><li>Café ☕</li><li>Rust 🦀</li></ul>"
    assert clean_html(html) == html
    assert html_to_text(html) == "- Python 🐍\n- Café ☕\n- Rust 🦀"


def test_nested_paragraphs_and_breaks():
    html = "<div><p>One <span>two</span></p><div><p>Three<br>Four</p></div></div><h3>Five</h3>"
    assert clean_html(html) == "<p>One two</p><p>Three<br/>Four</p><h3>Five</h3>"
    assert html_to_text(html) == "One two\nThree\nFour\nFive"


def test_list_item_bullet_sits_on_its_first_line():
    assert html_to_text("<ul><li><p>First</p><p>more</p></li></ul>") == "- First\nmore"


@pytest.mark.parametrize("path", sorted(POSTINGS.glob("*.json")), ids=lambda p: p.name)
def test_clean_html_is_idempotent_over_fixture_descriptions(path):
    html = json.loads(path.read_text(encoding="utf-8"))["description_html"]
    once = clean_html(html)
    assert clean_html(once) == once
    assert html_to_text(once) == html_to_text(html)
