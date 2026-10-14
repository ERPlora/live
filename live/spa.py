"""The HTML of the SPA: Vite manifest, CSP nonce, dev server, palette and the SDK's config (plan §4.2).

A project serves :func:`render_spa` for every path without a URL of its own in Django
(``re_path(spa_path_pattern(prefixes), view)``, last in the URLconf). The page links the Vite build
from ``{STATIC_URL}spa/`` (Vite's ``base``) or, with DEBUG, the dev server's HMR client and entry;
every ``<script>`` and ``modulepreload`` carries the response's CSP nonce, as 'strict-dynamic'
requires. No django-vite: one implementation for both projects.

Settings, under ``LIVE["spa"]``: ``entry`` (manifest key, e.g. ``frontend/main.ts``; a page that
is not the SPA asks :func:`spa_assets` for another entry of the same build), ``manifest``
(path of ``.vite/manifest.json``), ``dev_server`` (e.g. ``http://localhost:5173``; used only with
DEBUG), ``palettes`` and ``palette_default`` (the ``data-ep-palette`` palettes of the UI's theme),
``title`` (optional), ``user_scalable`` (optional, default ``False``: the page does not zoom, as a
point of sale wants; ``True`` lets it zoom, as a web panel must for WCAG 1.4.4).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.serializers.json import DjangoJSONEncoder
from django.http import HttpRequest, HttpResponse
from django.middleware.csp import get_nonce
from django.shortcuts import render
from django.utils.safestring import mark_safe
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_safe

#: First path segments that always belong to Django, never to the SPA. Each project adds its own
#: (hub-next: ``ws``, ``p``; saas-next: ``_allauth``, ``webhooks``…).
BASE_NON_SPA_PREFIXES = ("api", "internal", "admin", "static", "healthz", "readyz", "csp-report")

#: Cookie with the palette the shell painted last (``@erplora/ui`` theme writes it).
PALETTE_COOKIE = "ep_palette"
#: Element id of the SDK's config JSON; ``extra_json`` may not reuse it.
SPA_CONFIG_ID = "spa-config"

_JSON_SCRIPT_ESCAPES = {ord(">"): "\\u003E", ord("<"): "\\u003C", ord("&"): "\\u0026"}

#: The ``viewport`` meta: fixed scale (a point of sale; ``LIVE["spa"]["user_scalable"]`` False, the
#: default) or zoomable (a web panel; WCAG 1.4.4 forbids ``maximum-scale`` and ``user-scalable=no``).
VIEWPORT_FIXED = (
    "viewport-fit=cover, width=device-width, initial-scale=1.0, "
    "minimum-scale=1.0, maximum-scale=1.0, user-scalable=no"
)
VIEWPORT_ZOOMABLE = "width=device-width, initial-scale=1, viewport-fit=cover"


@dataclass(frozen=True)
class EntryAssets:
    """Files of one entry, relative to Vite's ``base``."""

    js: str
    css: list[str] = field(default_factory=list)
    preload: list[str] = field(default_factory=list)


class ViteManifest:
    """The ``manifest.json`` that ``vite build`` writes with ``build.manifest``."""

    _cache: dict[Path, tuple[int, ViteManifest]] = {}

    def __init__(self, chunks: dict[str, dict[str, Any]], path: Path):
        self.chunks = chunks
        self.path = path

    @classmethod
    def load(cls, path: Path | str) -> ViteManifest:
        """Read ``path``, once per modification time."""
        path = Path(path)
        try:
            mtime = path.stat().st_mtime_ns
        except FileNotFoundError:
            raise ImproperlyConfigured(
                f"Vite manifest not found at {path}: build the frontend first "
                f"(`pnpm --filter <project> build`, e.g. `pnpm --filter hub build`)."
            ) from None
        cached = cls._cache.get(path)
        if cached and cached[0] == mtime:
            return cached[1]
        try:
            chunks = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise ImproperlyConfigured(f"Vite manifest at {path} is not valid JSON: {exc}") from exc
        manifest = cls(chunks, path)
        cls._cache[path] = (mtime, manifest)
        return manifest

    def entry(self, key: str) -> EntryAssets:
        """The entry's file, the chunks it imports (transitively) and all their CSS.

        Lazily imported chunks (``dynamicImports``) are left to the browser: one chunk per page.
        """
        if key not in self.chunks:
            raise ImproperlyConfigured(f"Entry {key!r} is not in the Vite manifest at {self.path}.")
        css: list[str] = []
        preload: list[str] = []
        seen: set[str] = set()

        def visit(chunk_key: str, *, is_entry: bool) -> None:
            if chunk_key in seen:
                return
            seen.add(chunk_key)
            chunk = self.chunks[chunk_key]
            if not is_entry:
                preload.append(chunk["file"])
            for href in chunk.get("css", []):
                if href not in css:
                    css.append(href)
            for imported in chunk.get("imports", []):
                visit(imported, is_entry=False)

        visit(key, is_entry=True)
        return EntryAssets(js=self.chunks[key]["file"], css=css, preload=preload)


def _spa_settings() -> dict[str, Any]:
    try:
        return settings.LIVE["spa"]
    except (AttributeError, KeyError):
        raise ImproperlyConfigured('settings.LIVE["spa"] is required to serve the SPA.') from None


def _base_url() -> str:
    """Vite's ``base``: where the build is served from (and the dev server serves under)."""
    return f"{settings.STATIC_URL}spa/"


def spa_assets(request: HttpRequest, *, entry: str | None = None) -> dict[str, list[str]]:
    """URLs of the scripts, stylesheets and modulepreloads of an entry of the Vite build.

    ``entry`` is a manifest key (e.g. ``frontend/public.ts``, the public web of saas-next, round
    16); by default, the SPA's, ``LIVE["spa"]["entry"]``. With DEBUG, the dev server serves it.
    """
    config = _spa_settings()
    entry = entry or config["entry"]
    base = _base_url()
    dev_server = config.get("dev_server")
    if settings.DEBUG and dev_server:
        origin = dev_server.rstrip("/")
        return {
            "scripts": [f"{origin}{base}@vite/client", f"{origin}{base}{entry}"],
            "css": [],
            "preload": [],
        }
    assets = ViteManifest.load(config["manifest"]).entry(entry)
    return {
        "scripts": [f"{base}{assets.js}"],
        "css": [f"{base}{href}" for href in assets.css],
        "preload": [f"{base}{href}" for href in assets.preload],
    }


def palette(request: HttpRequest) -> str:
    """The palette of the ``ep_palette`` cookie if it is a known one, else the default."""
    config = _spa_settings()
    chosen = request.COOKIES.get(PALETTE_COOKIE)
    return chosen if chosen in config["palettes"] else config["palette_default"]


def spa_config(request: HttpRequest) -> dict[str, Any]:
    """What the SDK reads from the ``spa-config`` JSON block before its first request."""
    return {
        "csrfCookieName": settings.CSRF_COOKIE_NAME,
        "csrfHeader": "X-CSRFToken",
        "liveUrl": "/api/live",
        "apiBase": "/api",
        "lang": getattr(request, "LANGUAGE_CODE", None) or settings.LANGUAGE_CODE,
        "palette": palette(request),
    }


def _json_for_script(value: Any) -> str:
    """JSON safe inside ``<script type="application/json">`` (the escapes of ``json_script``)."""
    return mark_safe(json.dumps(value, cls=DjangoJSONEncoder).translate(_JSON_SCRIPT_ESCAPES))


@require_safe
@never_cache
@ensure_csrf_cookie
def render_spa(
    request: HttpRequest, *, extra_json: dict[str, Any] | None = None, extra_config: dict[str, Any] | None = None
) -> HttpResponse:
    """The SPA's HTML. ``extra_json`` adds one ``<script id=key type="application/json">`` per entry;
    ``extra_config`` adds the project's own keys to ``spa-config`` (never one of the SDK's).

    GET/HEAD only, never cached (a cached copy would replay a nonce), and it sets the CSRF cookie
    the SDK sends back on its writes.
    """
    nonce = get_nonce(request)
    if nonce is None:
        raise ImproperlyConfigured(
            "The SPA needs django.middleware.csp.ContentSecurityPolicyMiddleware: "
            "without a nonce, 'strict-dynamic' blocks every script."
        )
    extra_json = extra_json or {}
    if SPA_CONFIG_ID in extra_json:
        raise ValueError(f"extra_json may not use the reserved id {SPA_CONFIG_ID!r}.")
    config = spa_config(request)
    clashes = sorted(config.keys() & (extra_config or {}).keys())
    if clashes:
        raise ValueError(f"extra_config may not replace the SDK's keys: {', '.join(clashes)}.")
    config.update(extra_config or {})
    user_scalable = _spa_settings().get("user_scalable", False)
    context = {
        "csp_nonce": nonce,
        "lang": config["lang"],
        "palette": config["palette"],
        "title": _spa_settings().get("title", "ERPlora"),
        "viewport": VIEWPORT_ZOOMABLE if user_scalable else VIEWPORT_FIXED,
        "assets": spa_assets(request),
        "json_blocks": [
            {"id": SPA_CONFIG_ID, "json": _json_for_script(config)},
            *({"id": key, "json": _json_for_script(value)} for key, value in extra_json.items()),
        ],
    }
    return render(request, "live/spa.html", context)


def spa_path_pattern(prefixes: tuple[str, ...]) -> str:
    """Regex for ``re_path``: every path except those whose first segments are one of ``prefixes``.

    A prefix counts only as whole segments: ``api`` excludes ``/api`` and ``/api/…`` but not
    ``/apiary``.
    """
    alternatives = "|".join(re.escape(prefix.strip("/")) for prefix in prefixes)
    return rf"^(?!(?:{alternatives})(?:/|$)).*$"
