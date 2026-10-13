"""Content Security Policy of the SPA on Django 6.1's native CSP (plan §4.1).

``settings.SECURE_CSP = base_policy()`` in production and ``debug_policy()`` with DEBUG, with
``django.middleware.csp.ContentSecurityPolicyMiddleware`` and the ``csp`` context processor. Every
``<script>`` carries the response nonce; ``'strict-dynamic'`` lets the scripts it loads run.
Nothing comes from a CDN. ``connect-src ipc: http://ipc.localhost`` keeps the Tauri app's hardware
bridge alive: without it the app loses the hardware with no visible error.
"""

from __future__ import annotations

import json
import logging

from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.utils.csp import CSP, build_policy
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

logger = logging.getLogger(__name__)

#: Directives DEBUG widens to the Vite dev server (styles injected by HMR, fonts, images and the
#: HMR socket). ``script-src`` is never widened: the HMR client and the entry enter by nonce.
_DEV_SERVER_DIRECTIVES = ("connect-src", "style-src", "font-src", "img-src")
#: Most of a violation report that goes to the log.
_MAX_LOGGED_REPORT = 8 * 1024


def base_policy(*, report_uri: str | None = "/csp-report/") -> dict[str, list[str]]:
    """The production policy, a fresh dict on every call (callers may extend it)."""
    policy = {
        "default-src": [CSP.SELF],
        "script-src": [CSP.SELF, CSP.NONCE, CSP.STRICT_DYNAMIC],
        "style-src": [CSP.SELF, CSP.UNSAFE_INLINE],
        "img-src": [CSP.SELF, "data:", "blob:"],
        "font-src": [CSP.SELF, "data:"],
        "connect-src": [CSP.SELF, "ipc:", "http://ipc.localhost"],
        "frame-ancestors": [CSP.NONE],
        "base-uri": [CSP.SELF],
        "form-action": [CSP.SELF],
        "object-src": [CSP.NONE],
        "require-trusted-types-for": ["'script'"],
        # Trusted Types policies: the page's own `default` and Vue 3.5 (`vue`).
        "trusted-types": ["default", "vue", "'allow-duplicates'"],
    }
    if report_uri:
        policy["report-uri"] = [report_uri]
    return policy


def debug_policy(dev_server: str = "http://localhost:5173") -> dict[str, list[str]]:
    """``base_policy()`` plus the Vite dev server for connect/style/font/img, without enforcing
    Trusted Types (the Vite error overlay writes HTML directly)."""
    policy = base_policy()
    socket = (
        "ws" + dev_server.removeprefix("http")
        if dev_server.startswith("http")
        else dev_server
    )
    for directive in _DEV_SERVER_DIRECTIVES:
        policy[directive].append(dev_server)
    policy["connect-src"].append(socket)
    del policy["require-trusted-types-for"]
    return policy


def policy_header(policy: dict, nonce: str | None = None) -> str:
    """The header value Django's middleware sends for ``policy`` (``django.utils.csp.build_policy``)."""
    return build_policy(policy, nonce)


@csrf_exempt
@require_POST
def csp_report(request: HttpRequest) -> HttpResponse:
    """Receive a violation report (``report-uri`` or Reporting API), log it and answer 204."""
    try:
        report = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return HttpResponseBadRequest()
    text = json.dumps(report, ensure_ascii=False, separators=(",", ":"))
    logger.warning("csp.violation %s", text[:_MAX_LOGGED_REPORT])
    return HttpResponse(status=204)
