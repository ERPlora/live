"""Markdown to safe HTML: the store's app documentation and the Hub's help (round 16, spec §6).

Ported from the old SaaS (``apps/public/modules/services/rendering.py``): ``fenced_code``,
``tables`` and ``sane_lists``, the same allowlist sanitised with ``nh3``, and ```` ```mermaid ````
blocks as ``<pre class="mermaid">`` for mermaid.js. Round 16 adds:

- **images** only from the app's own ``docs/img/``: a relative ``docs/img/<path>`` becomes
  ``image_base + <path>``; any other source (another host, ``data:``, an absolute path, a ``.``,
  ``..`` or empty segment, a space or control character, another extension than
  ``IMAGE_EXTENSIONS``) removes the ``<img>``, and without ``image_base`` none survives;
- **ids on the headings** (``toc`` with ``slugify_unicode``), the slug the WORKBOOK's anchors use.
"""

import re
from pathlib import PurePosixPath
from urllib.parse import unquote

import markdown as md
import nh3
from markdown.extensions.toc import slugify_unicode

_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_ALLOWED_TAGS = {
    "p",
    "br",
    "strong",
    "em",
    "b",
    "i",
    "u",
    "s",
    *_HEADINGS,
    "ul",
    "ol",
    "li",
    "a",
    "code",
    "pre",
    "blockquote",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "hr",
    "img",
    "span",
    "div",
    "dl",
    "dt",
    "dd",
}
_ALLOWED_ATTRIBUTES = {
    "a": {"href", "title", "target"},
    "img": {"src", "alt", "title", "width", "height"},
    "th": {"align"},
    "td": {"align"},
    # class on <pre> so that mermaid blocks render as <pre class="mermaid">.
    "pre": {"class"},
    # The anchors of the headings (toc).
    **{heading: {"id"} for heading in _HEADINGS},
}
_EXTENSIONS = [
    "markdown.extensions.fenced_code",
    "markdown.extensions.tables",
    "markdown.extensions.sane_lists",
    "markdown.extensions.toc",
]
_EXTENSION_CONFIGS = {"markdown.extensions.toc": {"slugify": slugify_unicode}}

# fenced_code's output for ```mermaid → the <pre> mermaid.js picks up.
_MERMAID_RE = re.compile(
    r'<pre><code class="language-mermaid">(.*?)</code></pre>', re.DOTALL
)

#: The only image sources that survive: the app's own docs/img/ folder, relative.
IMAGE_PREFIX = "docs/img/"
#: The image formats an app's docs may use (spec §4.4): ``svg`` can carry script.
IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})
_IMAGE_PATH_RE = re.compile(r"[A-Za-z0-9._/-]+")
# nh3 serialises every attribute as name="value", with '"' escaped, so a quoted value never ends
# early: an <img> left without src (dropped by the attribute filter) is matched as a whole.
_IMG_TAG_RE = re.compile(r'<img(?:\s+[a-z-]+="[^"]*")*\s*/?>')


def _image_src(src: str, image_base: str) -> str | None:
    """The rewritten source of an image, or ``None`` to remove it.

    Checked once percent-decoded (a browser resolves ``%2e%2e`` as ``..``): only letters, digits,
    ``.``, ``_``, ``-`` and ``/`` (a browser strips TAB, LF and CR from a URL, so ``.\\t.`` would
    resolve as ``..``; no space, ``%``, ``?``, ``#``, ``\\`` or ``:`` either), no empty, ``.`` or
    ``..`` segment and one of ``IMAGE_EXTENSIONS``. The decoded path is what is emitted.
    """
    if not image_base or not src.startswith(IMAGE_PREFIX):
        return None
    path = unquote(src[len(IMAGE_PREFIX) :])
    if (
        not _IMAGE_PATH_RE.fullmatch(path)
        or any(segment in ("", ".", "..") for segment in path.split("/"))
        or PurePosixPath(path).suffix.lower() not in IMAGE_EXTENSIONS
    ):
        return None
    return image_base + path


def _drop_image_without_src(match: re.Match[str]) -> str:
    return match.group(0) if ' src="' in match.group(0) else ""


def render_markdown(text: str, *, image_base: str = "") -> str:
    """Markdown → sanitised HTML; ``""`` for empty text.

    ``image_base`` is where the app's ``docs/img/`` is published (the SaaS:
    ``HUB_STATIC_BASE_URL + "catalog/<id>/img/"``; the Hub's help: ``/static/catalog/<id>/img/``).
    """
    if not text:
        return ""

    html = md.markdown(
        text, extensions=_EXTENSIONS, extension_configs=_EXTENSION_CONFIGS
    )
    html = _MERMAID_RE.sub(r'<pre class="mermaid">\1</pre>', html)

    def attribute_filter(tag: str, attribute: str, value: str) -> str | None:
        if tag == "img" and attribute == "src":
            return _image_src(value, image_base)
        return value

    html = nh3.clean(
        html,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRIBUTES,
        attribute_filter=attribute_filter,
    )
    return _IMG_TAG_RE.sub(_drop_image_without_src, html)
