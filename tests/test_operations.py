"""Operations: declaration rules, permission, transaction, output validation and pending events."""

import psycopg
import pytest
from django.db import connection, transaction
from django.db.utils import InternalError
from django.utils import translation
from live import operations
from live.context import OperationContext, Scope
from live.errors import Conflict, LiveMisuse, PermissionDenied
from live.operations import (
    Operation,
    UnknownOperation,
    add_pending_event,
    clear_registry,
    current_operation,
    get,
    operation,
    pending_events,
    registry,
)
from ninja import Schema

from tests.testapp.models import Thing
from tests.testapp.queries import list_things, sneaky_write
from tests.testapp.schemas import ThingIn, ThingListIn, ThingListOut, ThingOut
from tests.testapp.services import create_thing

SCOPE = Scope("hub", "a")


class Empty(Schema):
    pass


class SessionOut(Schema):
    statement_timeout: str
    read_only: str


@pytest.fixture(autouse=True)
def isolated_registry():
    saved = dict(registry)
    yield registry
    registry.clear()
    registry.update(saved)


@pytest.fixture
def notified(monkeypatch):
    calls = []
    monkeypatch.setattr(operations, "notify_hook", lambda scope, names: calls.append((scope, names)))
    return calls


def make_ctx(*permissions):
    return OperationContext(scope=SCOPE, actor="user", permissions=frozenset(permissions))


def echo(ctx, data):
    return {"id": 1, "name": data.name}


def declare(name="x.thing.do", *, kind="query", module=None, body=echo, permission=None,
            input=ThingIn, output=ThingOut, **options):
    """Register an ad-hoc operation whose function pretends to live in ``module``."""

    def fn(ctx, data):
        return body(ctx, data)

    fn.__module__ = module or ("x.queries" if kind == "query" else "x.services")
    return operation(name, kind=kind, permission=permission, input=input, output=output, **options)(fn)


def show_session(ctx, data):
    with connection.cursor() as cursor:
        cursor.execute("SHOW statement_timeout")
        (timeout,) = cursor.fetchone()
        cursor.execute("SHOW transaction_read_only")
        (read_only,) = cursor.fetchone()
    return {"statement_timeout": timeout, "read_only": read_only}


def session_setting(name):
    with connection.cursor() as cursor:
        cursor.execute(f"SHOW {name}")
        return cursor.fetchone()[0]


# Declaration rules (import time)


@pytest.mark.parametrize(
    "name",
    ["thing.list", "testapp.thing.list.extra", "Testapp.thing.list", "testapp.thing.", "testapp..list",
     "1app.thing.list", "testapp.thing-x.list", "testapp"],
)
def test_name_must_have_three_parts(name):
    with pytest.raises(LiveMisuse):
        declare(name)

    assert name not in registry


def test_duplicate_name_is_rejected():
    first = declare("x.thing.do")

    with pytest.raises(LiveMisuse):
        declare("x.thing.do")

    assert registry["x.thing.do"] is first


def test_registering_the_same_function_with_the_same_declaration_again_returns_the_same_operation():
    def fn(ctx, data):
        return echo(ctx, data)

    fn.__module__ = "x.queries"
    declaration = {"kind": "query", "permission": "x.view", "input": ThingIn, "output": ThingOut}
    first = operation("x.thing.do", **declaration)(fn)

    assert operation("x.thing.do", **declaration)(fn) is first
    with pytest.raises(LiveMisuse):
        operation("x.thing.do", **{**declaration, "permission": "x.manage"})(fn)
    assert registry["x.thing.do"] is first


@pytest.mark.parametrize("module", ["x.services", "x.views", "queries", "x.queries_extra"])
def test_query_outside_queries_module_is_rejected(module):
    with pytest.raises(LiveMisuse):
        declare(kind="query", module=module)

    assert "x.thing.do" not in registry


@pytest.mark.parametrize("module", ["x.queries", "x.api", "services", "x.services_extra"])
def test_command_outside_services_module_is_rejected(module):
    with pytest.raises(LiveMisuse):
        declare(kind="command", module=module)

    assert "x.thing.do" not in registry


def test_unknown_kind_is_rejected():
    with pytest.raises(LiveMisuse):
        declare(kind="mutation", module="x.services")


@pytest.mark.parametrize(("input_", "output"), [(dict, ThingOut), (ThingIn, dict), (ThingIn(name="a"), ThingOut)])
def test_input_and_output_must_be_schema_classes(input_, output):
    with pytest.raises(LiveMisuse):
        declare(input=input_, output=output)


def test_decorator_registers_and_returns_the_operation():
    op = declare("x.thing.do", permission="x.view", expose_api=True, ai={"description": "Do"})

    assert isinstance(op, Operation)
    assert registry["x.thing.do"] is op
    assert get("x.thing.do") is op
    assert (op.name, op.kind, op.permission, op.app_label) == ("x.thing.do", "query", "x.view", "x")
    assert (op.input, op.output, op.expose_api, op.ai) == (ThingIn, ThingOut, True, {"description": "Do"})
    assert op.fn.__module__ == "x.queries"


def test_operations_are_hashable_by_identity():
    op = declare()

    assert {op: 1}[op] == 1


def test_options_default_to_not_exposed_and_no_assistant():
    op = declare()

    assert op.expose_api is False
    assert op.ai is None


def test_testapp_operations_are_registered_from_their_modules():
    assert get("testapp.thing.list") is list_things
    assert get("testapp.thing.sneaky_write") is sneaky_write
    assert get("testapp.thing.create") is create_thing
    assert list_things.kind == "query"
    assert create_thing.kind == "command"
    assert create_thing.permission == "testapp.manage"


def test_get_unknown_operation_raises_unknown_operation():
    with pytest.raises(UnknownOperation):
        get("x.thing.missing")

    assert issubclass(UnknownOperation, LiveMisuse)


def test_clear_registry_empties_it():
    declare()

    clear_registry()

    assert registry == {}


# Permission (checked before touching the database)


def test_missing_permission_raises_permission_denied():
    # No django_db mark: reaching the database would fail with a different error.
    with pytest.raises(PermissionDenied) as info:
        create_thing(make_ctx("testapp.view"), ThingIn(name="a"))

    assert info.value.status == 403
    assert info.value.envelope()["error"]["code"] == "permission_denied"


@pytest.mark.parametrize(
    ("language", "message"),
    [
        ("en", "Permission “testapp.manage” is required."),
        ("es", "Se necesita el permiso «testapp.manage»."),
    ],
)
def test_the_permission_message_is_translated_when_raised(language, message):
    # create_thing was declared at import time; the message must follow the language active now.
    with translation.override(language), pytest.raises(PermissionDenied) as info:
        create_thing(make_ctx("testapp.view"), ThingIn(name="a"))

    assert info.value.envelope()["error"] == {"code": "permission_denied", "message": message}


@pytest.mark.django_db
def test_operation_without_permission_runs_for_anyone():
    assert declare(permission=None)(make_ctx(), ThingIn(name="a")) == ThingOut(id=1, name="a")


@pytest.mark.django_db
def test_wildcard_permission_grants_the_operation():
    assert create_thing(make_ctx("testapp.*"), ThingIn(name="a")).name == "a"


# Queries: READ ONLY transaction with a local statement_timeout


@pytest.mark.django_db(transaction=True)
def test_query_runs_read_only_and_an_insert_fails():
    with pytest.raises(InternalError) as info:
        sneaky_write(make_ctx("testapp.view"), ThingIn(name="sneaky"))

    assert isinstance(info.value.__cause__, psycopg.errors.ReadOnlySqlTransaction)
    assert not connection.in_atomic_block
    assert not Thing.objects.exists()


@pytest.mark.django_db
def test_query_inside_an_outer_transaction_is_read_only_and_the_outer_one_stays_writable():
    assert connection.in_atomic_block

    with pytest.raises(InternalError) as info:
        sneaky_write(make_ctx("testapp.view"), ThingIn(name="sneaky"))

    assert isinstance(info.value.__cause__, psycopg.errors.ReadOnlySqlTransaction)
    assert session_setting("transaction_read_only") == "off"
    Thing.objects.create(name="after")
    assert list(Thing.objects.values_list("name", flat=True)) == ["after"]


@pytest.mark.django_db
def test_query_nested_in_a_command_leaves_the_command_writable():
    def body(ctx, data):
        listed = list_things(ctx, ThingListIn())
        thing = Thing.objects.create(name=f"{data.name}-{len(listed.rows)}")
        return thing

    command = declare("x.thing.create", kind="command", body=body)

    result = command(make_ctx("testapp.view"), ThingIn(name="made"))

    assert result.name == "made-0"
    assert Thing.objects.filter(name="made-0").exists()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("nested", [False, True])
def test_query_sets_read_only_and_statement_timeout_only_for_itself(nested):
    query = declare("x.session.show", input=Empty, output=SessionOut, body=show_session)

    if nested:
        with transaction.atomic():
            seen = query(make_ctx(), Empty())
            after = (session_setting("statement_timeout"), session_setting("transaction_read_only"))
    else:
        seen = query(make_ctx(), Empty())
        after = (session_setting("statement_timeout"), session_setting("transaction_read_only"))

    assert seen == SessionOut(statement_timeout="5s", read_only="on")
    assert after == ("0", "off")


@pytest.mark.django_db
def test_query_result_is_built_from_model_instances():
    Thing.objects.create(name="first")
    Thing.objects.create(name="second")

    result = list_things(make_ctx("testapp.view"), ThingListIn(limit=1))

    assert isinstance(result, ThingListOut)
    assert [row.name for row in result.rows] == ["first"]


# Output validation


@pytest.mark.django_db
def test_output_is_validated_against_schema():
    from_dict = declare("x.thing.from_dict", body=lambda ctx, data: {"id": 7, "name": data.name})
    invalid = declare("x.thing.invalid", body=lambda ctx, data: {"id": "not-a-number"})
    ready = ThingOut(id=3, name="ready")
    passthrough = declare("x.thing.ready", body=lambda ctx, data: ready)

    assert from_dict(make_ctx(), ThingIn(name="a")) == ThingOut(id=7, name="a")
    assert passthrough(make_ctx(), ThingIn(name="a")) is ready
    with pytest.raises(LiveMisuse) as info:
        invalid(make_ctx(), ThingIn(name="a"))
    assert "x.thing.invalid" in str(info.value)


@pytest.mark.django_db(transaction=True)
def test_invalid_output_of_a_command_rolls_it_back(notified):
    def body(ctx, data):
        Thing.objects.create(name=data.name)
        add_pending_event("x.thing.created")
        return {"id": "not-a-number"}

    command = declare("x.thing.create", kind="command", body=body)

    with pytest.raises(LiveMisuse):
        command(make_ctx(), ThingIn(name="lost"))

    assert not Thing.objects.exists()
    assert notified == []


# Commands: pending events and the post-commit notify hook


@pytest.mark.django_db(transaction=True)
def test_command_collects_pending_events_and_calls_notify_hook_after_commit(notified):
    ctx = make_ctx("testapp.manage")

    with transaction.atomic():
        create_thing(ctx, ThingIn(name="inside"))
        assert notified == []

    assert notified == [(SCOPE, ["testapp.thing.created"])]

    create_thing(ctx, ThingIn(name="alone"))

    assert notified == [(SCOPE, ["testapp.thing.created"]), (SCOPE, ["testapp.thing.created"])]
    assert Thing.objects.count() == 2


@pytest.mark.django_db(transaction=True)
def test_notify_hook_is_not_called_when_the_outer_transaction_rolls_back(notified):
    with pytest.raises(RuntimeError), transaction.atomic():
        create_thing(make_ctx("testapp.manage"), ThingIn(name="rolled back"))
        raise RuntimeError("boom")

    assert notified == []
    assert not Thing.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_notify_hook_is_not_called_when_the_command_fails(notified):
    def body(ctx, data):
        Thing.objects.create(name=data.name)
        add_pending_event("x.thing.created")
        raise Conflict("Already done.", code="x.thing_done")

    command = declare("x.thing.create", kind="command", body=body)

    with pytest.raises(Conflict):
        command(make_ctx(), ThingIn(name="failed"))

    assert notified == []
    assert not Thing.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_command_without_events_does_not_notify(notified):
    command = declare("x.thing.touch", kind="command", body=echo)

    command(make_ctx(), ThingIn(name="quiet"))

    assert notified == []


@pytest.mark.django_db(transaction=True)
def test_pending_events_are_deduplicated_in_order(notified):
    seen = []

    def body(ctx, data):
        for name in ("x.thing.updated", "x.thing.line_added", "x.thing.updated"):
            add_pending_event(name)
        seen.append(pending_events())
        return echo(ctx, data)

    declare("x.thing.update", kind="command", body=body)(make_ctx(), ThingIn(name="a"))

    assert seen == [["x.thing.updated", "x.thing.line_added"]]
    assert notified == [(SCOPE, ["x.thing.updated", "x.thing.line_added"])]


@pytest.mark.django_db(transaction=True)
def test_commit_survives_a_failing_notify_hook(monkeypatch):
    def broken_hook(scope, names):
        raise RuntimeError("notify failed")

    monkeypatch.setattr(operations, "notify_hook", broken_hook)

    result = create_thing(make_ctx("testapp.manage"), ThingIn(name="kept"))

    assert result.name == "kept"
    assert Thing.objects.filter(name="kept").exists()


@pytest.mark.django_db(transaction=True)
def test_command_commits_without_a_notify_hook(monkeypatch):
    monkeypatch.setattr(operations, "notify_hook", None)

    create_thing(make_ctx("testapp.manage"), ThingIn(name="kept"))

    assert Thing.objects.filter(name="kept").exists()


def test_add_pending_event_outside_an_operation_is_misuse():
    with pytest.raises(LiveMisuse):
        add_pending_event("x.thing.created")


@pytest.mark.django_db
def test_add_pending_event_inside_a_query_is_misuse():
    def body(ctx, data):
        add_pending_event("x.thing.created")
        return echo(ctx, data)

    with pytest.raises(LiveMisuse):
        declare(body=body)(make_ctx(), ThingIn(name="a"))


# Context variables


@pytest.mark.django_db
def test_context_vars_are_reset_after_the_call():
    seen = {}

    def body(ctx, data):
        seen["operation"] = current_operation.get()
        add_pending_event("x.thing.created")
        seen["events"] = pending_events()
        if data.name == "fail":
            raise Conflict("Failed.", code="x.thing_failed")
        return echo(ctx, data)

    command = declare("x.thing.create", kind="command", body=body)

    command(make_ctx(), ThingIn(name="ok"))

    assert seen == {"operation": command, "events": ["x.thing.created"]}
    assert current_operation.get() is None
    assert pending_events() == []

    with pytest.raises(Conflict):
        command(make_ctx(), ThingIn(name="fail"))

    assert current_operation.get() is None
    assert pending_events() == []


@pytest.mark.django_db
def test_nested_operation_restores_the_outer_operation():
    seen = []

    def inner_body(ctx, data):
        seen.append(current_operation.get().name)
        return echo(ctx, data)

    inner = declare("x.thing.inner", body=inner_body)

    def outer_body(ctx, data):
        add_pending_event("x.thing.outer_done")
        inner(ctx, data)
        seen.append(current_operation.get().name)
        seen.append(pending_events())
        return echo(ctx, data)

    declare("x.thing.outer", kind="command", body=outer_body)(make_ctx(), ThingIn(name="a"))

    assert seen == ["x.thing.inner", "x.thing.outer", ["x.thing.outer_done"]]
