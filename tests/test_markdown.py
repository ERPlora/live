"""Markdown to safe HTML (round 16, spec §6): the store's documentation and the Hub's help.

Ported from the old SaaS (``apps/public/modules/services/rendering.py``, origin/develop): the same
extensions, allowlist and Mermaid blocks. New in round 16: images only from the app's own
``docs/img/``, rewritten to ``image_base``, and ids on the headings for the anchors.
"""

import re

import pytest
from markdown.extensions.toc import slugify_unicode

from live.markdown import render_markdown

BASE = "https://hubs.example.com/static/catalog/demo/img/"
_IMG_RE = re.compile(r"<img\b[^>]*>")


def images(html):
    return _IMG_RE.findall(html)


# --- What the old SaaS did --------------------------------------------------------------------------


def test_empty_text_is_an_empty_string():
    assert render_markdown("") == ""


def test_markdown_becomes_html():
    html = render_markdown("Some **bold** and *italic* text.")

    assert html == "<p>Some <strong>bold</strong> and <em>italic</em> text.</p>"


def test_a_script_is_removed_with_its_content():
    html = render_markdown("Hello\n\n<script>alert(1)</script>")

    assert "<script" not in html
    assert "alert(1)" not in html
    assert "Hello" in html


@pytest.mark.parametrize(
    "dangerous",
    [
        '<p onclick="alert(1)">x</p>',
        '<a href="javascript:alert(1)">x</a>',
        '<iframe src="https://evil.example"></iframe>',
        '<div style="position:fixed">x</div>',
        '<span class="evil">x</span>',
    ],
)
def test_tags_and_attributes_outside_the_allowlist_are_removed(dangerous):
    html = render_markdown(dangerous)

    for forbidden in ("onclick", "javascript:", "<iframe", "style=", "class="):
        assert forbidden not in html


def test_links_are_kept_with_a_safe_rel():
    html = render_markdown("[ERPlora](https://erplora.com)")

    assert (
        html
        == '<p><a href="https://erplora.com" rel="noopener noreferrer">ERPlora</a></p>'
    )


def test_tables():
    html = render_markdown("| A | B |\n|---|---|\n| 1 | 2 |")

    assert "<table>" in html
    assert "<th>A</th>" in html
    assert "<td>2</td>" in html


def test_sane_lists_keep_an_ordered_and_an_unordered_list_apart():
    html = render_markdown("1. one\n\n* two")  # without sane_lists: one <ol> of two items

    assert html == "<ol>\n<li>one</li>\n</ol>\n<ul>\n<li>two</li>\n</ul>"


def test_fenced_code_is_a_pre_code_block_without_classes():
    html = render_markdown("```python\nx = 1 < 2\n```")

    assert html == "<pre><code>x = 1 &lt; 2\n</code></pre>"


def test_a_mermaid_block_becomes_pre_mermaid():
    html = render_markdown("```mermaid\ngraph TD\n  A-->B\n```")

    assert html == '<pre class="mermaid">graph TD\n  A--&gt;B\n</pre>'


def test_the_allowlist_of_tags_survives():
    text = "> quote\n\n---\n\n<dl><dt>term</dt><dd>definition</dd></dl>\n\nline<br>break `code` ~~no~~"
    html = render_markdown(text)

    for tag in ("<blockquote>", "<hr>", "<dl>", "<dt>", "<dd>", "<br>", "<code>"):
        assert tag in html


# --- Images: only the app's own docs/img/, rewritten to the base (new in round 16) ---------------------


def test_a_relative_docs_img_image_is_rewritten_to_the_base():
    [image] = images(
        render_markdown("![Flow chart](docs/img/flow.png)", image_base=BASE)
    )

    assert f'src="{BASE}flow.png"' in image
    assert 'alt="Flow chart"' in image


def test_a_subfolder_of_docs_img_is_kept():
    [image] = images(
        render_markdown("![Step](docs/img/steps/one.webp)", image_base=BASE)
    )

    assert f'src="{BASE}steps/one.webp"' in image


def test_a_relative_base_works_too():
    """The Hub's help uses /static/catalog/<id>/img/."""
    [image] = images(
        render_markdown(
            "![Flow](docs/img/flow.png)", image_base="/static/catalog/demo/img/"
        )
    )

    assert 'src="/static/catalog/demo/img/flow.png"' in image


def test_the_title_and_an_escaped_alt_survive():
    [image] = images(
        render_markdown('![a > "b"](docs/img/x.png "Title")', image_base=BASE)
    )

    assert 'alt="a &gt; &quot;b&quot;"' in image
    assert 'title="Title"' in image


@pytest.mark.parametrize(
    "src",
    [
        "https://evil.example/docs/img/x.png",
        "//evil.example/docs/img/x.png",
        "/docs/img/x.png",
        "data:image/png;base64,iVBORw0KGgo=",
        "../docs/img/x.png",
        "docs/img/../../secret.png",
        "docs/img/%2e%2e/%2E%2E/secret.png",
        "docs/img/..%2fsecret.png",
        "docs/img/",
        "img/x.png",
        "x.png",
        "DOCS/IMG/x.png",
    ],
)
def test_any_other_source_removes_the_image(src):
    html = render_markdown(f"Before ![Alt text]({src}) after", image_base=BASE)

    assert images(html) == []
    assert "Alt text" not in html
    assert "Before" in html and "after" in html


def test_without_a_base_no_image_survives():
    assert images(render_markdown("![Flow](docs/img/flow.png)")) == []


def test_raw_html_images_follow_the_same_rule():
    text = (
        '<img src="docs/img/ok.png" alt="a > b" onerror="alert(1)">\n\n'
        '<img src="https://evil.example/x.png" alt="evil">\n\n'
        "<img src=docs/img/bare.png alt=bare>"
    )
    html = render_markdown(text, image_base=BASE)

    assert len(images(html)) == 2
    assert f'src="{BASE}ok.png"' in html
    assert f'src="{BASE}bare.png"' in html
    assert "evil" not in html
    assert "onerror" not in html


def test_an_image_attribute_cannot_smuggle_a_second_tag():
    html = render_markdown(
        '<img alt="&lt;img src=x&gt;" src="https://evil.example/x.png">ok',
        image_base=BASE,
    )

    assert images(html) == []
    assert "ok" in html


# --- Ids on the headings, for the anchors (new in round 16) -------------------------------------------


def test_every_heading_gets_an_id():
    html = render_markdown(
        "\n\n".join(f"{'#' * level} Level {level}" for level in range(1, 7))
    )

    for level in range(1, 7):
        assert f'<h{level} id="level-{level}">Level {level}</h{level}>' in html


def test_the_id_is_the_unicode_slug_of_the_title():
    title = "Configuración básica: ¿qué hace?"
    html = render_markdown(f"## {title}")

    assert f'<h2 id="{slugify_unicode(title, "-")}">' in html
    assert 'id="configuración-básica-qué-hace"' in html


def test_repeated_titles_get_distinct_ids():
    html = render_markdown("## Setup\n\n## Setup")

    assert 'id="setup"' in html
    assert 'id="setup_1"' in html


def test_ids_are_only_allowed_on_headings():
    html = render_markdown('<p id="x">text</p>\n\n<a id="y" href="#x">link</a>')

    assert 'id="' not in html
    assert 'href="#x"' in html
