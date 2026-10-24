"""An operation that touches no database (``database=False``; hub APP-BASE-9): what waits on the network.

The Hub's assistant asks erplora.com for the month's messages, a report or a dictation: up to 15 s of waiting. Inside
``transaction.atomic`` that wait would hold a connection to the hub's database (and, on the Free plan, its one
transaction at a time: PLAN §14.2), so the till would wait too. Declared ``database=False``, the operation opens no
transaction, and keeps what ``@operation`` gives: the permission, the project's hook (``LIVE["operation_database"]``:
the hub of the context, the app's right) and the validated output. A query to any database inside it is a misuse, as
recording an event or asking for ``on_commit``: there is no transaction for them.
"""

from contextlib import contextmanager

import pytest
from django.db import connections
from live import operations
from live.context import OperationContext, Scope
from live.errors import LiveMisuse, PermissionDenied
from live.operations import add_pending_event, operation, registry
from ninja import Schema

HOOK = "tests.test_operation_no_database.on_other"
SCOPE = Scope("host", "a")
entered: list[tuple[str, str]] = []

pytestmark = pytest.mark.django_db(databases=["default", "other"], transaction=True)


@contextmanager
def on_other(op, ctx):
    """The test's hook: every operation runs on ``other``; it notes when it enters and leaves."""
    entered.append((op.name, "enter"))
    try:
        yield "other"
    finally:
        entered.append((op.name, "exit"))


class Empty(Schema):
    pass


class Seen(Schema):
    default_atomic: bool = False
    other_atomic: bool = False


@pytest.fixture(autouse=True)
def isolated_registry(settings):
    settings.LIVE = {**settings.LIVE, "operation_database": HOOK}
    saved = dict(registry)
    entered.clear()
    yield
    registry.clear()
    registry.update(saved)


def declare(name: str, kind: str, fn, **options):
    fn.__module__ = "tests.fakeapp." + ("services" if kind == "command" else "queries")
    return operation(name, kind=kind, permission=options.pop("permission", None), input=Empty, output=Seen, **options)(fn)


def ctx(*permissions: str) -> OperationContext:
    return OperationContext(scope=SCOPE, actor="ana", permissions=frozenset(permissions))


def atomic_now() -> dict:
    return {"default_atomic": connections["default"].in_atomic_block, "other_atomic": connections["other"].in_atomic_block}


def test_an_operation_opens_its_transaction_by_default():
    op = declare("x.thing.read", "query", lambda ctx, data: atomic_now())
    assert op.database is True
    assert op(ctx(), Empty()).other_atomic is True


@pytest.mark.parametrize("kind", ["query", "command"])
def test_one_that_touches_no_database_runs_with_no_transaction_open(kind):
    op = declare("x.thing.wait", kind, lambda ctx, data: atomic_now(), database=False)
    assert op(ctx(), Empty()) == Seen(default_atomic=False, other_atomic=False)
    # The project's hook still runs around it: the hub of the context, the app's right.
    assert entered == [("x.thing.wait", "enter"), ("x.thing.wait", "exit")]


def test_its_permission_is_still_required():
    ran = []
    op = declare("x.thing.wait", "command", lambda ctx, data: ran.append(1) or {}, database=False, permission="x.wait")
    with pytest.raises(PermissionDenied):
        op(ctx(), Empty())
    assert ran == []
    assert op(ctx("x.wait"), Empty()) == Seen()


@pytest.mark.parametrize("alias", ["default", "other"])
def test_a_query_inside_it_is_a_misuse(alias):
    def fn(ctx, data):
        with connections[alias].cursor() as cursor:
            cursor.execute("SELECT 1")
        return {}

    op = declare("x.thing.wait", "query", fn, database=False)
    with pytest.raises(LiveMisuse, match=r"x\.thing\.wait touches no database"):
        op(ctx(), Empty())
    # Only while it runs: the connection works again after it.
    with connections[alias].cursor() as cursor:
        cursor.execute("SELECT 1")


def test_recording_an_event_inside_it_is_a_misuse():
    def fn(ctx, data):
        add_pending_event("x.thing.waited")
        return {}

    with pytest.raises(LiveMisuse, match="touches no database"):
        declare("x.thing.wait", "command", fn, database=False)(ctx(), Empty())


def test_on_commit_inside_it_is_a_misuse():
    def fn(ctx, data):
        operations.on_commit(lambda: None)
        return {}

    with pytest.raises(LiveMisuse, match="touches no database"):
        declare("x.thing.wait", "command", fn, database=False)(ctx(), Empty())


def test_the_same_function_declared_with_and_without_a_database_is_two_declarations():
    def fn(ctx, data):
        return {}

    fn.__module__ = "tests.fakeapp.services"
    operation("x.thing.wait", kind="command", permission=None, input=Empty, output=Seen)(fn)
    with pytest.raises(LiveMisuse, match="already declared"):
        operation("x.thing.wait", kind="command", permission=None, input=Empty, output=Seen, database=False)(fn)
