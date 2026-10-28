"""Live registry: which queries are subscribable and which events re-run them (plan §4.1)."""

import pytest
from live import live_registry as live_registry_module
from live.errors import LiveMisuse
from live.live_registry import LiveRegistry, live, live_registry, session_events
from live.operations import operation, registry

from tests.testapp import queries as _testapp_queries  # noqa: F401  (registers testapp operations)
from tests.testapp import services as _testapp_services  # noqa: F401
from tests.testapp.schemas import ThingIn, ThingOut


@pytest.fixture(autouse=True)
def isolated_registries():
    saved_ops = dict(registry)
    saved_live = dict(live_registry.subscribable)
    yield
    registry.clear()
    registry.update(saved_ops)
    live_registry.clear()
    live_registry.subscribable.update(saved_live)


def declare(name, *, kind="query", permission="x.view"):
    def fn(ctx, data):
        return {"id": 1, "name": data.name}

    fn.__module__ = "x.queries" if kind == "query" else "x.services"
    return operation(name, kind=kind, permission=permission, input=ThingIn, output=ThingOut)(fn)


@pytest.fixture
def reg():
    return LiveRegistry()


# Declaration


def test_live_declares_a_subscribable_query_on_the_module_registry():
    live_registry.clear()

    live("x.thing.list", on=["x.thing.created", "x.thing.deleted"])

    assert live_registry.subscribable == {"x.thing.list": ["x.thing.created", "x.thing.deleted"]}
    assert live_registry.is_subscribable("x.thing.list")
    assert not live_registry.is_subscribable("x.thing.detail")


def test_live_needs_at_least_one_event(reg):
    with pytest.raises(LiveMisuse):
        reg.register("x.thing.list", on=[])


@pytest.mark.parametrize("on", ["x.thing.created", [1], None])
def test_live_events_must_be_a_list_of_strings(reg, on):
    with pytest.raises(LiveMisuse):
        reg.register("x.thing.list", on=on)


def test_a_query_is_declared_live_only_once(reg):
    reg.register("x.thing.list", on=["x.thing.created"])

    with pytest.raises(LiveMisuse):
        reg.register("x.thing.list", on=["x.thing.deleted"])


def test_the_testapp_live_module_is_discovered_at_startup():
    """LiveConfig.ready() imports every app's live.py (P2); the testapp declares its list."""
    assert live_registry.subscribable["testapp.thing.list"] == ["testapp.thing.created"]


# affected()


def test_affected_resolves_events_to_queries(reg):
    reg.register("x.thing.list", on=["x.thing.created", "x.thing.deleted"])
    reg.register("x.thing.count", on=["x.thing.created"])
    reg.register("y.other.list", on=["y.other.changed"])

    assert reg.affected({"x.thing.deleted"}) == {"x.thing.list"}
    assert reg.affected({"x.thing.created"}) == {"x.thing.list", "x.thing.count"}
    assert reg.affected({"x.thing.created", "y.other.changed"}) == {
        "x.thing.list",
        "x.thing.count",
        "y.other.list",
    }
    assert reg.affected({"z.nobody.cares"}) == set()
    assert reg.affected(set()) == set()


def test_star_affects_everything(reg):
    reg.register("x.thing.list", on=["x.thing.created"])
    reg.register("y.other.list", on=["y.other.changed"])

    assert reg.affected({"*"}) == {"x.thing.list", "y.other.list"}
    assert reg.affected({"*", "x.thing.created"}) == {"x.thing.list", "y.other.list"}


def test_affected_sees_declarations_made_after_a_previous_lookup(reg):
    reg.register("x.thing.list", on=["x.thing.created"])
    assert reg.affected({"x.thing.created"}) == {"x.thing.list"}

    reg.register("x.thing.count", on=["x.thing.created"])

    assert reg.affected({"x.thing.created"}) == {"x.thing.list", "x.thing.count"}


def test_clear_forgets_everything(reg):
    reg.register("x.thing.list", on=["x.thing.created"])

    reg.clear()

    assert reg.subscribable == {}
    assert reg.affected({"*"}) == set()


# check()


def test_check_accepts_a_query_with_permission_and_valid_events(reg):
    declare("x.thing.list")
    reg.register("x.thing.list", on=["x.thing.created"])

    assert reg.check() == []


def test_check_rejects_an_unknown_operation(reg):
    reg.register("x.ghost.list", on=["x.ghost.created"])

    errors = reg.check()

    assert len(errors) == 1
    assert "x.ghost.list" in errors[0]
    assert "unknown" in errors[0]


def test_check_rejects_a_command(reg):
    declare("x.thing.create", kind="command")
    reg.register("x.thing.create", on=["x.thing.created"])

    errors = reg.check()

    assert len(errors) == 1
    assert "x.thing.create" in errors[0]
    assert "query" in errors[0]


def test_check_rejects_a_query_without_permission(reg):
    declare("x.thing.list", permission=None)
    reg.register("x.thing.list", on=["x.thing.created"])

    errors = reg.check()

    assert len(errors) == 1
    assert "x.thing.list" in errors[0]
    assert "permission" in errors[0]


@pytest.mark.parametrize("event", ["created", "x.thing", "X.thing.created", "x.thing.created.now", "*"])
def test_check_rejects_a_bad_event_name(reg, event):
    declare("x.thing.list")
    reg.register("x.thing.list", on=[event])

    errors = reg.check()

    assert len(errors) == 1
    assert repr(event) in errors[0]


def test_check_reports_every_problem(reg):
    declare("x.thing.create", kind="command", permission=None)
    reg.register("x.thing.create", on=["bad"])
    reg.register("x.ghost.list", on=["x.ghost.created"])

    assert len(reg.check()) == 4


def test_the_module_exposes_one_registry():
    assert isinstance(live_registry_module.live_registry, LiveRegistry)


# Session events (settings.LIVE["session_events"]): no live query declares them, every stream re-reads its context


def test_session_events_are_read_from_the_settings(settings):
    settings.LIVE = {**settings.LIVE, "session_events": ["accounts.session.closed"]}

    assert session_events() == frozenset({"accounts.session.closed"})


def test_without_the_setting_no_event_is_a_session_event(settings):
    settings.LIVE = {key: value for key, value in settings.LIVE.items() if key != "session_events"}

    assert session_events() == frozenset()


def test_a_session_event_affects_no_query_that_does_not_declare_it(reg, settings):
    # The stream re-reads its context instead (live.executor): nothing re-runs for it.
    settings.LIVE = {**settings.LIVE, "session_events": ["accounts.session.closed"]}
    reg.register("x.item.list", on=["x.item.created"])

    assert reg.affected(["accounts.session.closed"]) == set()
