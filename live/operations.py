"""Operations: every read and write declared once with ``@operation``.

A ``query`` lives in an app's ``queries.py`` and runs in a ``READ ONLY`` transaction with a local
``statement_timeout``; a ``command`` lives in ``services.py`` and runs in its own transaction. The
ninja route, the live subscription, the assistant and the API keys all call the same
``Operation``, which checks the permission, opens the transaction, validates the output and, for a
command, hands the names of the events it recorded to ``notify_hook`` after the COMMIT.
"""

import re
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from functools import partial
from typing import Any, Literal, TypeVar

import pydantic
from django.db import connection, transaction
from django.utils.translation import gettext
from ninja import Schema

from live.context import OperationContext, Scope
from live.errors import LiveMisuse, PermissionDenied

Kind = Literal["query", "command"]
NAME_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
QUERY_STATEMENT_TIMEOUT = "5s"
_MODULE_SUFFIX: dict[str, str] = {"query": ".queries", "command": ".services"}

F = TypeVar("F", bound=Callable[..., Any])


class UnknownOperation(LiveMisuse):
    """No operation is registered under that name."""


# Called after the COMMIT of a command with the event names it recorded; LiveConfig.ready() wires
# it to live.outbox.notify.
notify_hook: Callable[[Scope, list[str]], None] | None = None

current_operation: ContextVar["Operation | None"] = ContextVar("live_current_operation", default=None)
_pending_events: ContextVar[list[str] | None] = ContextVar("live_pending_events", default=None)


@dataclass(eq=False)
class Operation:
    name: str
    kind: Kind
    permission: str | None
    input: type[Schema]
    output: type[Schema]
    expose_api: bool
    ai: Any | None
    fn: Callable[[OperationContext, Schema], Any]

    @property
    def app_label(self) -> str:
        return self.name.split(".", 1)[0]

    def __call__(self, ctx: OperationContext, data: Schema) -> Schema:
        if not ctx.has(self.permission):
            # Translated now, in the caller's language (the request's, or the live stream's).
            raise PermissionDenied(
                gettext("Permission “%(permission)s” is required.") % {"permission": self.permission}
            )
        operation_token = current_operation.set(self)
        events_token = _pending_events.set([])
        try:
            with transaction.atomic():
                if self.kind == "query":
                    with connection.cursor() as cursor:
                        cursor.execute("SET TRANSACTION READ ONLY")
                        cursor.execute(f"SET LOCAL statement_timeout = '{QUERY_STATEMENT_TIMEOUT}'")
                result = self._validated(self.fn(ctx, data))
                if self.kind == "query":
                    # A query never commits. Nested in another transaction it runs in a savepoint:
                    # Postgres restores READ ONLY when the savepoint ends, but SET LOCAL
                    # statement_timeout would outlive a released savepoint; rolling it back undoes it.
                    transaction.set_rollback(True)
                else:
                    names = list(_pending_events.get())
                    if names:
                        transaction.on_commit(partial(_notify, ctx.scope, names), robust=True)
        finally:
            _pending_events.reset(events_token)
            current_operation.reset(operation_token)
        return result

    def _validated(self, result: Any) -> Schema:
        if isinstance(result, self.output):
            return result
        try:
            return self.output.model_validate(result)
        except pydantic.ValidationError as exc:
            raise LiveMisuse(f"{self.name} returned an output that is not a valid {self.output.__name__}: {exc}") from exc


registry: dict[str, Operation] = {}


def _declaration(op: Operation) -> tuple:
    return (op.fn, op.kind, op.permission, op.input, op.output, op.expose_api, op.ai)


def operation(
    name: str,
    *,
    kind: Kind,
    permission: str | None,
    input: type[Schema],
    output: type[Schema],
    expose_api: bool = False,
    ai: Any | None = None,
) -> Callable[[F], Operation]:
    """Declare and register an operation; misdeclarations fail at import time."""
    if not NAME_RE.match(name):
        raise LiveMisuse(f"Operation name {name!r} must be <app>.<entity>.<action> (lowercase snake_case).")
    if kind not in _MODULE_SUFFIX:
        raise LiveMisuse(f"Operation {name!r}: kind must be 'query' or 'command', not {kind!r}.")
    for role, schema in (("input", input), ("output", output)):
        if not (isinstance(schema, type) and issubclass(schema, Schema)):
            raise LiveMisuse(f"Operation {name!r}: {role} must be a ninja Schema class, not {schema!r}.")

    def register(fn: F) -> Operation:
        suffix = _MODULE_SUFFIX[kind]
        if not fn.__module__.endswith(suffix):
            raise LiveMisuse(f"Operation {name!r}: a {kind} must be declared in a {suffix[1:]}.py module, not in {fn.__module__}.")
        declared = Operation(
            name=name,
            kind=kind,
            permission=permission,
            input=input,
            output=output,
            expose_api=expose_api,
            ai=ai,
            fn=fn,
        )
        existing = registry.get(name)
        if existing is not None:
            # The same function with the same declaration is the same operation registered again.
            if _declaration(existing) == _declaration(declared):
                return existing
            raise LiveMisuse(f"Operation {name!r} is already declared in {existing.fn.__module__}.")
        registry[name] = declared
        return declared

    return register


def get(name: str) -> Operation:
    try:
        return registry[name]
    except KeyError:
        raise UnknownOperation(f"Unknown operation {name!r}.") from None


def clear_registry() -> None:
    """Forget every operation (tests only)."""
    registry.clear()


def pending_events() -> list[str]:
    """Event names recorded so far by the running operation (a copy; empty outside one)."""
    return list(_pending_events.get() or [])


def add_pending_event(name: str) -> None:
    """Record an event name to notify after the COMMIT of the running command (deduplicated)."""
    operation = current_operation.get()
    names = _pending_events.get()
    if operation is None or operation.kind != "command" or names is None:
        raise LiveMisuse(f"Event {name!r} can only be recorded inside a command operation.")
    if name not in names:
        names.append(name)


def _notify(scope: Scope, names: list[str]) -> None:
    if notify_hook is not None:
        notify_hook(scope, names)
