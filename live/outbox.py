"""Outbox: the events a command records in its transaction and one notification after the COMMIT.

``record_event`` writes an ``OutboxEvent`` in the running command's transaction, so the row and
the business change commit or roll back together, and hands the name to the operation. After the
COMMIT, ``live.operations`` calls ``notify`` (wired as ``notify_hook`` by ``LiveConfig.ready``),
which sends a single ``pg_notify`` with the unique names on the scope's channel, in the control
database. Postgres caps a payload below 8000 bytes: past ``MAX_NOTIFY_BYTES`` the payload becomes
``"*"`` and listeners re-run everything of that scope.
"""

import json
import logging
from collections.abc import Sequence
from typing import Any

from django.conf import settings
from django.db import DEFAULT_DB_ALIAS, connections

from live import operations
from live.context import OperationContext, Scope
from live.errors import LiveMisuse
from live.models import OutboxEvent
from live.operations import NAME_RE

logger = logging.getLogger(__name__)

MAX_NOTIFY_BYTES = 7000
ALL_EVENTS_PAYLOAD = '{"events":["*"]}'
_ACTOR_MAX_LENGTH = OutboxEvent._meta.get_field("actor").max_length


def record_event(ctx: OperationContext, name: str, payload: dict[str, Any] | None = None) -> OutboxEvent:
    """Write ``<app>.<entity>.<fact>`` in the running command's transaction and notify it after the COMMIT."""
    running = operations.current_operation.get()
    if running is None or running.kind != "command":
        raise LiveMisuse(f"Event {name!r} can only be recorded inside a command operation.")
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise LiveMisuse(f"Event name {name!r} must be <app>.<entity>.<fact> (lowercase snake_case).")
    event = OutboxEvent.objects.create(
        scope_kind=ctx.scope.kind,
        scope_key=ctx.scope.key,
        name=name,
        payload=payload or {},
        actor=str(ctx.actor)[:_ACTOR_MAX_LENGTH],
    )
    operations.add_pending_event(name)
    return event


def channel_for(scope: Scope) -> str:
    """The channel a scope's notifications go to (and its listeners LISTEN on)."""
    return scope.channel


def notify(scope: Scope, names: Sequence[str]) -> None:
    """Send one ``{"events": [...]}`` notification on the scope's channel; called after the COMMIT."""
    payload = json.dumps({"events": sorted(set(names))}, separators=(",", ":"))
    if len(payload.encode()) > MAX_NOTIFY_BYTES:
        payload = ALL_EVENTS_PAYLOAD
    # The only place of the package that picks a connection by alias: every process holds its
    # single LISTEN on the control database, so notifications always go there, whatever database
    # the command wrote to (in hub-next phase 2, the hub's own database).
    alias = getattr(settings, "LIVE", {}).get("control_alias", DEFAULT_DB_ALIAS)
    connection = connections[alias]
    if connection.in_atomic_block:
        logger.warning(
            "Notifying %s inside a transaction on %r: it is delivered only when that transaction commits.",
            scope.channel,
            alias,
        )
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_notify(%s, %s)", [channel_for(scope), payload])
