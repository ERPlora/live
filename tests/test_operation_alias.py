"""Where an operation's transaction runs: ``LIVE["operation_database"]`` (hub-next phase 2, S1).

A project may name a hook ``(operation, context) -> context manager`` that yields the alias the operation's
transaction opens on (hub-next: the hub of ``use_hub``). Without it the alias is ``default``, as the SaaS keeps it.
The query's ``READ ONLY`` and ``statement_timeout``, and the notification after the COMMIT, follow that alias's
transaction; the notification itself still goes to the control database (``LIVE["control_alias"]``).
"""

from contextlib import contextmanager

import pytest
from django.db import connections, transaction
from live import operations, outbox
from live.context import OperationContext, Scope
from live.operations import add_pending_event, operation, registry
from ninja import Schema

HOOK = "tests.test_operation_alias.on_other"
SCOPE = Scope("host", "a")
entered: list[tuple[str, Scope, str]] = []

pytestmark = pytest.mark.django_db(databases=["default", "other"], transaction=True)


@contextmanager
def on_other(op, ctx):
    """The test's hook: every operation runs on the ``other`` alias; it notes when it enters and leaves."""
    entered.append((op.name, ctx.scope, "enter"))
    try:
        yield "other"
    finally:
        entered.append((op.name, ctx.scope, "exit"))


class Empty(Schema):
    pass


class Seen(Schema):
    default_atomic: bool
    other_atomic: bool
    read_only: str = ""
    timeout: str = ""


@pytest.fixture(autouse=True)
def isolated_registry():
    saved = dict(registry)
    entered.clear()
    yield
    registry.clear()
    registry.update(saved)


@pytest.fixture
def hooked(settings):
    settings.LIVE = {**settings.LIVE, "operation_database": HOOK}


@pytest.fixture
def notified(monkeypatch):
    calls = []
    monkeypatch.setattr(operations, "notify_hook", lambda scope, names: calls.append((scope, names)))
    return calls


def declare(name: str, kind: str, fn):
    fn.__module__ = "tests.fakeapp." + ("services" if kind == "command" else "queries")
    return operation(name, kind=kind, permission=None, input=Empty, output=Seen)(fn)


def ctx() -> OperationContext:
    return OperationContext(scope=SCOPE, actor="system", permissions=frozenset({"*"}))


def _seen(alias_for_settings: str) -> dict:
    seen = {
        "default_atomic": connections["default"].in_atomic_block,
        "other_atomic": connections["other"].in_atomic_block,
    }
    with connections[alias_for_settings].cursor() as cursor:
        cursor.execute("SHOW transaction_read_only")
        seen["read_only"] = cursor.fetchone()[0]
        cursor.execute("SHOW statement_timeout")
        seen["timeout"] = cursor.fetchone()[0]
    return seen


def test_without_the_setting_an_operation_runs_on_default():
    op = declare("testapp.probe.default", "command", lambda ctx, data: _seen("default"))

    seen = op(ctx(), Empty())

    assert (seen.default_atomic, seen.other_atomic) == (True, False)


@pytest.mark.usefixtures("hooked")
def test_a_command_opens_its_transaction_on_the_hooks_alias():
    op = declare("testapp.probe.command", "command", lambda ctx, data: _seen("other"))

    seen = op(ctx(), Empty())

    assert (seen.default_atomic, seen.other_atomic, seen.read_only) == (False, True, "off")
    assert entered == [("testapp.probe.command", SCOPE, "enter"), ("testapp.probe.command", SCOPE, "exit")]


@pytest.mark.usefixtures("hooked")
def test_a_query_is_read_only_with_its_timeout_on_the_hooks_alias():
    op = declare("testapp.probe.query", "query", lambda ctx, data: _seen("other"))

    seen = op(ctx(), Empty())

    assert (seen.other_atomic, seen.read_only, seen.timeout) == (True, "on", operations.QUERY_STATEMENT_TIMEOUT)
    assert _seen("default")["read_only"] == "off"


@pytest.mark.usefixtures("hooked")
def test_the_notification_waits_for_the_commit_of_the_hooks_alias(notified):
    def record(ctx, data):
        add_pending_event("testapp.thing.created")
        return _seen("other")

    op = declare("testapp.probe.record", "command", record)

    with transaction.atomic(using="other"):
        op(ctx(), Empty())
        assert notified == []
    assert notified == [(SCOPE, ["testapp.thing.created"])]


@pytest.mark.usefixtures("hooked")
def test_an_operation_that_fails_leaves_the_hook_and_notifies_nothing(notified):
    def fail(ctx, data):
        add_pending_event("testapp.thing.created")
        raise ZeroDivisionError

    op = declare("testapp.probe.fail", "command", fail)

    with pytest.raises(ZeroDivisionError):
        op(ctx(), Empty())
    assert [step for *_, step in entered] == ["enter", "exit"]
    assert notified == []


@pytest.mark.usefixtures("hooked")
def test_the_notification_still_goes_to_the_control_database(monkeypatch):
    monkeypatch.setattr(operations, "notify_hook", outbox.notify)
    sent: dict[str, list[str]] = {"default": [], "other": []}

    def recorder(alias):
        def wrap(execute, sql, params, many, context):
            sent[alias].append(sql)
            return execute(sql, params, many, context)

        return wrap

    def record(ctx, data):
        add_pending_event("testapp.thing.created")
        return _seen("other")

    op = declare("testapp.probe.notify", "command", record)
    with connections["default"].execute_wrapper(recorder("default")), connections["other"].execute_wrapper(
        recorder("other")
    ):
        op(ctx(), Empty())

    assert any("pg_notify" in sql for sql in sent["default"])
    assert not any("pg_notify" in sql for sql in sent["other"])


# ``live.operations.on_commit``: after the COMMIT of the running operation's own transaction, on its alias.


@pytest.mark.usefixtures("hooked")
def test_on_commit_runs_after_the_commit_of_the_operations_alias():
    ran = []

    def later(ctx, data):
        operations.on_commit(lambda: ran.append("after"))
        assert ran == []  # not now: «other» is still in its transaction
        return _seen("other")

    op = declare("testapp.probe.later", "command", later)

    with transaction.atomic(using="other"):
        op(ctx(), Empty())
        assert ran == []
    assert ran == ["after"]


@pytest.mark.usefixtures("hooked")
def test_on_commit_never_runs_when_the_operation_fails():
    ran = []

    def fail(ctx, data):
        operations.on_commit(lambda: ran.append("after"))
        raise ZeroDivisionError

    op = declare("testapp.probe.later_fail", "command", fail)

    with pytest.raises(ZeroDivisionError):
        op(ctx(), Empty())
    assert ran == []


def test_on_commit_without_the_setting_waits_for_defaults_commit():
    ran = []

    def later(ctx, data):
        operations.on_commit(lambda: ran.append("after"))
        return _seen("default")

    op = declare("testapp.probe.later_default", "command", later)

    with transaction.atomic(using="default"):
        op(ctx(), Empty())
        assert ran == []
    assert ran == ["after"]


def test_on_commit_outside_an_operation_is_misuse():
    from live.errors import LiveMisuse

    with pytest.raises(LiveMisuse):
        operations.on_commit(lambda: None)


@pytest.mark.usefixtures("hooked")
def test_a_failing_callback_does_not_undo_the_commit(caplog):
    ran = []

    def later(ctx, data):
        operations.on_commit(lambda: 1 / 0)
        operations.on_commit(lambda: ran.append("after"))
        return _seen("other")

    declare("testapp.probe.later_robust", "command", later)(ctx(), Empty())

    assert ran == ["after"]
