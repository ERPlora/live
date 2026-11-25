"""What a project does when a command has run: ``LIVE["after_command"]``.

A project may name a hook ``(operation, context, data)`` that runs inside every command's own transaction, once its body
has answered and before its COMMIT: what it writes is applied with the command or not at all. It adds no transaction
around the command's, so what a cut of the database means for that command stays what it was. A query and a command that
touches no database have none.
"""

import pytest
from django.db import OperationalError, connections
from live import operations
from live.context import OperationContext, Scope
from live.database_cut import DatabaseCut
from live.errors import Conflict, LiveMisuse
from live.operations import current_operation, operation, pending_events, registry
from live.outbox import record_event
from ninja import Schema

from tests.testapp.models import Thing

HOOK = "tests.test_operation_after_command.after"
SCOPE = Scope("hub", "a")
ran: list[tuple] = []
doing: list = []

pytestmark = pytest.mark.django_db(databases=["default", "other"], transaction=True)


def after(op, ctx, data):
    ran.append((op.name, ctx, data, pending_events(), connections["default"].in_atomic_block))
    for step in doing:
        step(op, ctx)


class Named(Schema):
    name: str = "x"


class Counted(Schema):
    count: int = 0


@pytest.fixture(autouse=True)
def isolated(settings):
    saved = dict(registry)
    ran.clear()
    doing.clear()
    settings.LIVE = {**settings.LIVE, "after_command": HOOK}
    yield
    registry.clear()
    registry.update(saved)


@pytest.fixture
def notified(monkeypatch):
    calls = []
    monkeypatch.setattr(operations, "notify_hook", lambda scope, names: calls.append((scope, names)))
    return calls


def declare(name: str, fn, *, kind: str = "command", **declaration):
    fn.__module__ = "tests.fakeapp." + ("services" if kind == "command" else "queries")
    return operation(name, kind=kind, permission=None, input=Named, output=Counted, **declaration)(fn)


def ctx() -> OperationContext:
    return OperationContext(scope=SCOPE, actor="system", permissions=frozenset({"*"}))


def make(_ctx, data):
    Thing.objects.create(name=data.name)
    record_event(_ctx, "fakeapp.thing.made", {})
    return {"count": 1}


def test_it_runs_once_the_body_has_answered_inside_the_commands_transaction():
    make_thing = declare("fakeapp.thing.make", make)
    here, data = ctx(), Named(name="lamp")
    make_thing(here, data)
    assert ran == [("fakeapp.thing.make", here, data, ["fakeapp.thing.made"], True)]


def test_what_it_writes_and_records_is_applied_with_the_command_and_notified_once(notified):
    doing.append(lambda _op, _ctx: Thing.objects.create(name="noted"))
    doing.append(lambda _op, here: record_event(here, "fakeapp.thing.noted", {}))
    declare("fakeapp.thing.make", make)(ctx(), Named(name="lamp"))
    assert sorted(Thing.objects.values_list("name", flat=True)) == ["lamp", "noted"]
    assert notified == [(SCOPE, ["fakeapp.thing.made", "fakeapp.thing.noted"])]


def test_a_command_that_fails_never_gets_there():
    def refuse(_ctx, _data):
        Thing.objects.create(name="lamp")
        raise Conflict("Not now.", code="fakeapp.not_now")

    with pytest.raises(Conflict):
        declare("fakeapp.thing.refuse", refuse)(ctx(), Named())
    assert ran == []


def test_an_answer_that_is_no_valid_output_never_gets_there():
    with pytest.raises(LiveMisuse):
        declare("fakeapp.thing.lie", lambda _ctx, _data: {"count": "many"})(ctx(), Named())
    assert ran == []


def test_what_it_raises_rolls_the_command_back(notified):
    def refuse(_op, _ctx):
        raise Conflict("Not now.", code="fakeapp.not_now")

    doing.append(refuse)
    with pytest.raises(Conflict):
        declare("fakeapp.thing.make", make)(ctx(), Named(name="lamp"))
    assert not Thing.objects.exists()
    assert notified == []


def test_a_query_and_a_command_that_touches_no_database_have_none():
    declare("fakeapp.thing.read", lambda _ctx, _data: {"count": 1}, kind="query")(ctx(), Named())
    declare("fakeapp.thing.call", lambda _ctx, _data: {"count": 1}, database=False)(ctx(), Named())
    assert ran == []


def test_a_command_inside_another_has_its_own():
    inner = declare("fakeapp.thing.make", make)
    seen = []
    doing.append(lambda _op, _ctx: seen.append(current_operation.get().name))
    declare("fakeapp.thing.wrap", lambda here, data: inner(here, data))(ctx(), Named())
    assert [(name, events) for name, _, _, events, _ in ran] == [
        ("fakeapp.thing.make", ["fakeapp.thing.made"]),
        ("fakeapp.thing.wrap", []),
    ]
    assert seen == ["fakeapp.thing.make", "fakeapp.thing.wrap"]


@pytest.mark.parametrize("repeatable", [True, False])
def test_a_cut_of_the_database_in_it_is_the_commands_own_cut(settings, repeatable):
    def cut(_op, _ctx):
        raise OperationalError("the connection was lost")

    settings.LIVE = {**settings.LIVE, "database_cut": {"wait_seconds": 1}}
    doing.append(cut)
    with pytest.raises(DatabaseCut) as raised:
        declare("fakeapp.thing.make", make, repeatable=repeatable)(ctx(), Named(name="lamp"))
    assert raised.value.repeatable is repeatable
    assert not Thing.objects.exists()


def test_a_hook_that_cannot_be_imported_is_a_misuse(settings):
    settings.LIVE = {**settings.LIVE, "after_command": "tests.nowhere.at_all"}
    with pytest.raises(LiveMisuse, match=r'LIVE\["after_command"\]'):
        declare("fakeapp.thing.make", make)(ctx(), Named())


def test_a_project_that_names_none_runs_its_commands_as_always(settings):
    settings.LIVE = {key: value for key, value in settings.LIVE.items() if key != "after_command"}
    assert declare("fakeapp.thing.make", make)(ctx(), Named(name="lamp")).count == 1
    assert ran == []
