"""One error envelope for the 404 and 405 that never reach a route of the API.

``live.ninja.install_error_handlers`` turns every failure inside a route into ``{"error": {"code",
"message"}}``. Two failures happen before any route runs: a path under the API prefix that
resolves to nothing falls to Django's HTML 404, and a known path called with the wrong method gets
ninja's plain-text 405. ``ApiErrorEnvelopeMiddleware`` rewrites both into the envelope in place,
so the status and every header (``Allow`` included) stay as they were.

Left untouched: responses that already are JSON, streaming responses (never read), the live
stream and the API docs, and every path outside the prefix (``settings.LIVE["api_prefix"]``,
``/api/`` by default), where the SPA catch-all answers.
"""

import json
from typing import Any

from asgiref.sync import iscoroutinefunction, markcoroutinefunction
from django.conf import settings
from django.http import HttpRequest
from django.http.response import HttpResponseBase
from django.utils.translation import gettext_lazy as _

DEFAULT_API_PREFIX = "/api/"
#: First segments under the prefix that are not JSON endpoints: the SSE stream and Swagger UI.
UNTOUCHED_SEGMENTS = frozenset({"live", "docs"})
#: Status → (code, message) of the envelope that replaces a non-JSON answer, in the request's language.
ENVELOPES = {
    404: ("not_found", _("Not found")),
    405: ("method_not_allowed", _("Method not allowed")),
}


class ApiErrorEnvelopeMiddleware:
    """Answer an API 404/405 that is not JSON with the error envelope (sync and async)."""

    sync_capable = True
    async_capable = True

    def __init__(self, get_response: Any) -> None:
        self.get_response = get_response
        self.is_async = iscoroutinefunction(get_response)
        if self.is_async:
            markcoroutinefunction(self)

    def __call__(self, request: HttpRequest) -> Any:
        if self.is_async:
            return self._acall(request)
        return envelope_api_error(request, self.get_response(request))

    async def _acall(self, request: HttpRequest) -> HttpResponseBase:
        return envelope_api_error(request, await self.get_response(request))


def envelope_api_error(
    request: HttpRequest, response: HttpResponseBase
) -> HttpResponseBase:
    """``response`` with its body replaced by the envelope when it is an API 404/405 that is not JSON."""
    entry = ENVELOPES.get(response.status_code)
    if (
        entry is None
        or response.streaming
        or _is_json(response)
        or not _is_api_path(request.path_info)
    ):
        return response
    code, message = entry
    response.content = json.dumps(
        {"error": {"code": code, "message": str(message)}}
    ).encode()
    response["Content-Type"] = "application/json"
    if response.has_header("Content-Length"):
        response["Content-Length"] = str(len(response.content))
    return response


def _is_json(response: HttpResponseBase) -> bool:
    media_type = response.get("Content-Type", "").split(";", 1)[0].strip().lower()
    return media_type == "application/json" or media_type.endswith("+json")


def _is_api_path(path: str) -> bool:
    prefix = (
        getattr(settings, "LIVE", {}).get("api_prefix", DEFAULT_API_PREFIX).rstrip("/")
        + "/"
    )
    if not path.startswith(prefix):
        return False
    return path[len(prefix) :].split("/", 1)[0] not in UNTOUCHED_SEGMENTS
