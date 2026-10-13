"""Server-Sent Events frames and the subscription list of ``/api/live`` (plan §4.1).

One stream per browser tab. The SDK declares its subscriptions when it opens the stream, as
``?s=<base64url JSON [{id, op, params}]>``; if they change it closes and reopens the stream. The
server answers with ``hello``, then ``result``/``error`` frames per subscription id, a
``heartbeat`` every :data:`HEARTBEAT_EVERY` seconds and ``bye`` before closing.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from typing import Any

from django.core.serializers.json import DjangoJSONEncoder

HELLO = "hello"
RESULT = "result"
ERROR = "error"
HEARTBEAT = "heartbeat"
BYE = "bye"

#: Subscriptions one stream may declare.
MAX_SUBS = 50
#: Largest serialised result a ``result`` frame may carry; bigger ones become an ``error``.
MAX_RESULT_BYTES = 256 * 1024
#: Seconds between two ``heartbeat`` frames.
HEARTBEAT_EVERY = 15.0
#: Reconnection delay the browser is told to use (``retry:`` line), in milliseconds.
RETRY_MS = 3000

_SUBSCRIPTION_KEYS = frozenset({"id", "op", "params"})
_BASE64URL = re.compile(r"[A-Za-z0-9_-]*={0,2}")
_LINE_BREAK = re.compile(r"[\r\n]")


def frame(
    event: str,
    data: dict[str, Any] | None = None,
    *,
    id: str | None = None,
    retry_ms: int | None = None,
) -> bytes:
    """One SSE frame: ``event``, optional ``id`` and ``retry`` lines, and one ``data`` line.

    ``data`` is serialised as compact JSON on a single line (JSON escapes every line break inside
    strings), so a value can never split the frame. ``None`` sends ``{}``.
    """
    for name, value in (("event", event), ("id", id)):
        if value is not None and _LINE_BREAK.search(value):
            raise ValueError(f"SSE {name} must not contain a line break: {value!r}")
    lines = [f"event: {event}"]
    if id is not None:
        lines.append(f"id: {id}")
    if retry_ms is not None:
        lines.append(f"retry: {int(retry_ms)}")
    payload = json.dumps(
        {} if data is None else data,
        cls=DjangoJSONEncoder,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    lines.append(f"data: {payload}")
    return ("\n".join(lines) + "\n\n").encode("utf-8")


def parse_subscriptions(s: str, *, max_subs: int = MAX_SUBS) -> list[dict[str, Any]]:
    """Decode the ``s`` query parameter into ``[{"id": str, "op": str, "params": dict}, …]``.

    ``s`` is base64url (padding optional) of a JSON list. Raises ``ValueError`` with the message
    ``"too_many_subscriptions"`` above ``max_subs`` and ``"invalid_subscriptions"`` for anything
    malformed: bad base64url or JSON, a wrong shape, an unknown key or a repeated id (results are
    routed to the client by id).
    """
    subscriptions = _decode(s)
    if not isinstance(subscriptions, list):
        raise ValueError("invalid_subscriptions")
    if len(subscriptions) > max_subs:
        raise ValueError("too_many_subscriptions")
    seen: set[str] = set()
    parsed = []
    for item in subscriptions:
        if not _is_subscription(item) or item["id"] in seen:
            raise ValueError("invalid_subscriptions")
        seen.add(item["id"])
        parsed.append({"id": item["id"], "op": item["op"], "params": item["params"]})
    return parsed


def _decode(s: str) -> Any:
    if not s or not _BASE64URL.fullmatch(s):
        raise ValueError("invalid_subscriptions")
    padded = s.rstrip("=") + "=" * (-len(s.rstrip("=")) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise ValueError("invalid_subscriptions") from exc


def _is_subscription(item: Any) -> bool:
    return (
        isinstance(item, dict)
        and item.keys() == _SUBSCRIPTION_KEYS
        and isinstance(item["id"], str)
        and bool(item["id"])
        and isinstance(item["op"], str)
        and bool(item["op"])
        and isinstance(item["params"], dict)
    )
