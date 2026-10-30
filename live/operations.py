"""Operations: every read and write declared once with ``@operation``.

A ``query`` lives in an app's ``queries.py`` and runs in a ``READ ONLY`` transaction with a local
``statement_timeout``; a ``command`` lives in ``services.py`` and runs in its own transaction. The
ninja route, the live subscription, the assistant and the API keys all call the same
``Operation``, which checks the permission, opens the transaction, validates the output and, for a
command, hands the names of the events it recorded to ``notify_hook`` after the COMMIT.

The transaction opens on ``default`` unless the project names a hook in ``LIVE["operation_database"]``: a dotted
path to ``(operation, context) -> context manager`` that yields the alias to use (hub-next phase 2: the hub of
``use_hub``, ``base.tenancy.context.operation_database``). ``READ ONLY``, ``statement_timeout`` and the
notification after the COMMIT follow that alias's transaction; the notification still goes to the control database.

An operation declared ``database=False`` touches no database: what waits on the network (another service's answer)
runs with no transaction open, so the wait holds no connection. It keeps the permission, the project's hook and the
validated output; a query to any database inside it, an event or an ``on_commit`` is a ``LiveMisuse``.

Every operation tells the assistant what it is (PLAN §30: every operation is a tool by default): ``ai=AI(description=…,
risk="normal"|"high")`` for a tool, ``ai=INTERNAL`` for what is not one, never by omission (``live.E017``). A ``dict``
declared before ``AI`` existed is still accepted: ``Operation.ai_spec()`` reads it as one of the two.
"""

import re
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, ExitStack, contextmanager, nullcontext
from contextvars import ContextVar
from dataclasses import dataclass
from functools import cache, partial
from typing import Any, Literal, Self, TypeVar

import pydantic
from django.conf import settings
from django.db import DEFAULT_DB_ALIAS, connections, transaction
from django.utils.module_loading import import_string
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

current_operation: ContextVar[Operation | None] = ContextVar("live_current_operation", default=None)
_pending_events: ContextVar[list[str] | None] = ContextVar("live_pending_events", default=None)
#: The alias the running operation's transaction is open on (``on_commit``).
_operation_alias: ContextVar[str | None] = ContextVar("live_operation_alias", default=None)


#: The words a ``dict`` declaration starts with to say it is no tool (the Hub's before ``INTERNAL`` existed).
NOT_A_TOOL = ("Not an assistant tool", "System only")
#: The risks of a tool: ``normal`` asks a click on its card, ``high`` to type a word (or how many records it touches).
RISKS = ("normal", "high")


@dataclass(frozen=True)
class AI:
    """An assistant tool: what it does, told to the model in English (``description``); its ``risk`` (``RISKS``); and,
    for a dangerous write, the read of its own app that shows what it will do on its card (``preview``:
    ``{"operation": <a query>, "fields": [<data of its answer>]}``)."""

    description: str
    risk: Literal["normal", "high"] = "normal"
    preview: dict | None = None


class Internal:
    """What is not an assistant tool: the platform's reactions, scheduled tasks and doors, a screen's own reads, a file.
    One instance, ``INTERNAL``; falsy, as no declaration is, so ``op.ai or {}`` reads it as nothing for the assistant."""

    _instance: Internal | None = None

    def __new__(cls) -> Self:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "INTERNAL"

    def __bool__(self) -> bool:
        return False

    def __reduce__(self) -> str:
        return "INTERNAL"


INTERNAL = Internal()


@dataclass(eq=False)
class Operation:
    name: str
    kind: Kind
    permission: str | None
    input: type[Schema]
    output: type[Schema]
    expose_api: bool
    #: ``AI``, ``INTERNAL`` or a ``dict`` (``ai_spec()``); ``None`` only until ``live.E017`` says so.
    ai: AI | Internal | dict | None
    fn: Callable[[OperationContext, Schema], Any]
    #: ``False``: it touches no database and runs with no transaction open (what waits on the network).
    database: bool = True

    @property
    def app_label(self) -> str:
        return self.name.split(".", 1)[0]

    def ai_spec(self) -> AI | Internal | None:
        """What ``ai=`` declares, typed: ``AI`` or ``INTERNAL`` as declared; a ``dict`` read as the rules of the Hub's
        assistant before ``AI`` existed — one without a description, one that says it is no tool (``NOT_A_TOOL``) and
        one on what only the platform runs (no permission, or one no app declares: its reactions and scheduled tasks)
        are ``INTERNAL``, any other the tool it describes —; ``None`` when it declares nothing (``live.E017``)."""
        declared = self.ai
        if declared is None or isinstance(declared, AI | Internal):
            return declared
        if not isinstance(declared, dict):
            return None
        description = str(declared.get("description", "")).strip()
        if not description or description.startswith(NOT_A_TOOL):
            return INTERNAL
        from live.meta import declared_permissions

        if self.permission is None or self.permission not in declared_permissions():
            return INTERNAL
        return AI(description, "high" if declared.get("risk") == "high" else "normal", declared.get("preview"))

    def __call__(self, ctx: OperationContext, data: Schema) -> Schema:
        if not ctx.has(self.permission):
            # Translated now, in the caller's language (the request's, or the live stream's).
            raise PermissionDenied(
                gettext("Permission “%(permission)s” is required.") % {"permission": self.permission}
            )
        if not self.database:
            return self._without_database(ctx, data)
        operation_token = current_operation.set(self)
        events_token = _pending_events.set([])
        try:
            with _database(self, ctx) as alias, transaction.atomic(using=alias):
                alias_token = _operation_alias.set(alias)
                try:
                    if self.kind == "query":
                        with transaction.get_connection(alias).cursor() as cursor:
                            cursor.execute("SET TRANSACTION READ ONLY")
                            cursor.execute(f"SET LOCAL statement_timeout = '{QUERY_STATEMENT_TIMEOUT}'")
                    result = self._validated(self.fn(ctx, data))
                    if self.kind == "query":
                        # A query never commits. Nested in another transaction it runs in a savepoint:
                        # Postgres restores READ ONLY when the savepoint ends, but SET LOCAL
                        # statement_timeout would outlive a released savepoint; rolling it back undoes it.
                        transaction.set_rollback(True, using=alias)
                    else:
                        names = list(_pending_events.get())
                        if names:
                            transaction.on_commit(partial(_notify, ctx.scope, names), using=alias, robust=True)
                finally:
                    _operation_alias.reset(alias_token)
        finally:
            _pending_events.reset(events_token)
            current_operation.reset(operation_token)
        return result

    def _without_database(self, ctx: OperationContext, data: Schema) -> Schema:
        operation_token = current_operation.set(self)
        events_token = _pending_events.set(None)
        alias_token = _operation_alias.set(None)
        try:
            with _database(self, ctx), _no_queries(self):
                return self._validated(self.fn(ctx, data))
        finally:
            _operation_alias.reset(alias_token)
            _pending_events.reset(events_token)
            current_operation.reset(operation_token)

    def _validated(self, result: Any) -> Schema:
        if isinstance(result, self.output):
            return result
        try:
            return self.output.model_validate(result)
        except pydantic.ValidationError as exc:
            raise LiveMisuse(f"{self.name} returned an output that is not a valid {self.output.__name__}: {exc}") from exc


registry: dict[str, Operation] = {}


def _declaration(op: Operation) -> tuple:
    return (op.fn, op.kind, op.permission, op.input, op.output, op.expose_api, op.ai, op.database)


def operation(
    name: str,
    *,
    kind: Kind,
    permission: str | None,
    input: type[Schema],
    output: type[Schema],
    expose_api: bool = False,
    ai: AI | Internal | dict | None = None,
    database: bool = True,
) -> Callable[[F], Operation]:
    """Declare and register an operation; misdeclarations fail at import time.

    ``database=False``: the operation touches no database and runs with no transaction open (it waits on the network).
    """
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
            database=database,
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


def on_commit(fn: Callable[[], Any], *, robust: bool = True) -> None:
    """Run ``fn`` after the COMMIT of the running operation's transaction, on that transaction's alias.

    What a ``services.py`` calls instead of ``transaction.on_commit``: with ``LIVE["operation_database"]`` the
    operation's transaction is not on ``default`` (hub-next phase 2: the hub's database), and a callback registered
    there would run at once, before the COMMIT, and also after a rollback. ``robust``: a callback that raises is
    logged and the others still run. Outside an operation it is a misuse.
    """
    running = current_operation.get()
    if running is not None and not running.database:
        raise LiveMisuse(f"{running.name} touches no database (database=False): it has no COMMIT to run on_commit after.")
    alias = _operation_alias.get()
    if alias is None:
        raise LiveMisuse("on_commit runs inside an operation, after the COMMIT of its transaction.")
    transaction.on_commit(fn, using=alias, robust=robust)


def add_pending_event(name: str) -> None:
    """Record an event name to notify after the COMMIT of the running command (deduplicated)."""
    operation = current_operation.get()
    if operation is not None and not operation.database:
        raise LiveMisuse(f"{operation.name} touches no database (database=False): it records no event {name!r}.")
    names = _pending_events.get()
    if operation is None or operation.kind != "command" or names is None:
        raise LiveMisuse(f"Event {name!r} can only be recorded inside a command operation.")
    if name not in names:
        names.append(name)


def _database(op: Operation, ctx: OperationContext) -> AbstractContextManager[str]:
    """The project's ``LIVE["operation_database"]`` for ``op`` in ``ctx``, or ``default`` without one."""
    path = getattr(settings, "LIVE", {}).get("operation_database")
    if not path:
        return nullcontext(DEFAULT_DB_ALIAS)
    return _load_database_hook(path)(op, ctx)


@contextmanager
def _no_queries(op: Operation) -> Iterator[None]:
    """While ``op`` runs, a query to any database is refused: it was declared ``database=False``."""

    def refuse(execute, sql, params, many, context):
        raise LiveMisuse(f"{op.name} touches no database (database=False), but it ran: {str(sql)[:80]!r}.")

    with ExitStack() as stack:
        for connection in connections.all(initialized_only=False):
            stack.enter_context(connection.execute_wrapper(refuse))
        yield


@cache
def _load_database_hook(path: str) -> Callable[[Operation, OperationContext], AbstractContextManager[str]]:
    try:
        return import_string(path)
    except ImportError as exc:
        raise LiveMisuse(f'settings.LIVE["operation_database"] = {path!r} cannot be imported: {exc}') from exc


def _notify(scope: Scope, names: list[str]) -> None:
    if notify_hook is not None:
        notify_hook(scope, names)
