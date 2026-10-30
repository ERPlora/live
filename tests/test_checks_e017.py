"""``live.E017`` and the typed declaration it checks (PLAN §30, docs/plans/2026-10-30-asistente-saas.md §2).

Every operation tells the assistant what it is: a tool (``ai=AI(description=…, risk=…)``) or not one
(``ai=INTERNAL``), never by omission. The dictionaries the apps declared before ``AI`` existed are still accepted and
read as one of the two by ``Operation.ai_spec()``.
"""

import copy
import pickle

import pytest
from django.core import checks
from django.core.checks.registry import registry as check_registry
from live.checks import check_ai_declared
from live.context import OperationContext, Scope
from live.operations import AI, INTERNAL, Internal, Operation, operation, registry
from ninja import Schema


class NoIn(Schema):
    pass


class Done(Schema):
    done: bool = True


def op(name="testapp.probe.run", *, ai=None, permission="testapp.manage", kind="command"):
    return Operation(
        name=name,
        kind=kind,
        permission=permission,
        input=NoIn,
        output=Done,
        expose_api=False,
        ai=ai,
        fn=lambda ctx, data: {"done": True},
        database=False,
    )


def e017(monkeypatch, declared):
    """The E017 messages for one operation registered with ``ai=declared``."""
    monkeypatch.setitem(registry, "testapp.probe.run", op(ai=declared))
    return [message for message in check_ai_declared() if "testapp.probe.run" in message.msg]


# ── The typed declaration ─────────────────────────────────────────────────────────────────────────────────────────


def test_a_tool_is_declared_with_its_description_and_a_normal_risk_by_default():
    declared = AI(description="Creates a thing.")
    assert (declared.description, declared.risk, declared.preview) == ("Creates a thing.", "normal", None)


def test_internal_is_one_falsy_sentinel_that_says_what_it_is():
    """Falsy as no declaration is: the code that reads ``op.ai or {}`` reads it as nothing for the assistant."""
    assert Internal() is INTERNAL
    assert copy.deepcopy(INTERNAL) is INTERNAL and pickle.loads(pickle.dumps(INTERNAL)) is INTERNAL
    assert repr(INTERNAL) == "INTERNAL"
    assert not INTERNAL


def test_the_spec_of_a_typed_declaration_is_itself():
    tool = AI(description="Creates a thing.", risk="high")
    assert op(ai=tool).ai_spec() is tool
    assert op(ai=INTERNAL).ai_spec() is INTERNAL
    assert op(ai=None).ai_spec() is None


def test_a_dictionary_is_read_as_the_tool_it_describes():
    preview = {"operation": "testapp.thing.get", "fields": ["name"]}
    spec = op(ai={"description": " Creates a thing. ", "risk": "high", "preview": preview}).ai_spec()
    assert spec == AI(description="Creates a thing.", risk="high", preview=preview)
    assert op(ai={"description": "Lists the things."}, kind="query").ai_spec() == AI(description="Lists the things.")


@pytest.mark.parametrize("text", ["Not an assistant tool (a PIN is typed on the pad).", "System only: the relay."])
def test_a_dictionary_that_says_it_is_no_tool_is_internal(text):
    assert op(ai={"description": text, "risk": "high"}).ai_spec() is INTERNAL


@pytest.mark.parametrize("permission", [None, "testapp.system", "system.testapp"])
def test_a_dictionary_on_what_only_the_platform_runs_is_internal(permission):
    """The rule the Hub's assistant applied before ``AI`` existed: a permission no app declares (or none) is the
    platform's — its reactions and scheduled tasks —, whatever the dictionary says. An ``AI`` says it itself."""
    assert op(ai={"description": "Platform reaction: forget a product."}, permission=permission).ai_spec() is INTERNAL
    tool = AI(description="Lists the apps of the catalogue.")
    assert op(ai=tool, permission=permission).ai_spec() is tool


# ── live.E017 ─────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_check_is_registered_with_the_live_tag():
    assert check_ai_declared in check_registry.get_checks()
    assert check_ai_declared.tags == ("live",)


def test_an_operation_without_ai_fails(monkeypatch):
    [message] = e017(monkeypatch, None)
    assert message.id == "live.E017"
    assert "declares no ai=" in message.msg
    assert "ai=AI(description=" in message.hint and "ai=INTERNAL" in message.hint


@pytest.mark.parametrize(
    "declared",
    [
        AI(description="Creates a thing."),
        AI(description="Voids a thing.", risk="high"),
        INTERNAL,
        {"description": "Creates a thing.", "risk": "normal"},
        {"description": "Not an assistant tool (the screen's).", "in_person": True},
    ],
)
def test_a_tool_or_internal_passes(monkeypatch, declared):
    assert e017(monkeypatch, declared) == []


@pytest.mark.parametrize(
    "declared, problem",
    [
        (AI(description="Voids a thing.", risk="destructive"), "risk 'destructive'"),
        ({"description": "Voids a thing.", "risk": "bulk_destructive"}, "risk 'bulk_destructive'"),
        (AI(description="  "), "without a description"),
        ({"risk": "high"}, "without a description"),
        ({"description": ""}, "without a description"),
        ("Creates a thing.", "neither AI(...), INTERNAL nor a dict"),
    ],
)
def test_a_declaration_that_is_neither_fails(monkeypatch, declared, problem):
    [message] = e017(monkeypatch, declared)
    assert message.id == "live.E017"
    assert problem in message.msg


def test_every_operation_is_looked_at_not_only_the_apps_passed(monkeypatch):
    """As the metadata checks: one registry, whatever ``app_configs`` ``manage.py check`` passes."""
    monkeypatch.setitem(registry, "testapp.probe.run", op())
    assert [m.id for m in check_ai_declared(app_configs=[]) if "testapp.probe.run" in m.msg] == ["live.E017"]


def test_the_installed_apps_pass():
    assert [message for message in checks.run_checks(tags=["live"]) if message.id == "live.E017"] == []


def test_operation_takes_the_typed_declaration_and_runs_the_same():
    """``@operation(ai=AI(...))`` registers it as declared, and the same declaration twice is the same operation."""

    def probe(ctx: OperationContext, data: NoIn) -> dict:
        return {"done": True}

    probe.__module__ = "tests.testapp.services"
    tool = AI(description="Probes.", risk="high")
    try:
        declared = operation("testapp.probe.typed", kind="command", permission=None, input=NoIn, output=Done, ai=tool)(probe)
        again = operation("testapp.probe.typed", kind="command", permission=None, input=NoIn, output=Done, ai=tool)(probe)
        assert declared is again and declared.ai is tool
    finally:
        registry.pop("testapp.probe.typed", None)
    ctx = OperationContext(scope=Scope("hub", "a"), actor="ana", permissions=frozenset({"testapp.manage"}), language="en")
    assert op(ai=INTERNAL)(ctx, NoIn()).done is True
