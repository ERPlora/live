"""What a person would type to ask for a tool (``AI.asks``), how it is read (``live.assistant.asks_of``) and
``live.E020``, which requires it of every tool of the apps a project lists in ``LIVE_ASSISTANT_ASKS_REQUIRED``.

The asks are the assistant's knowledge of what a person can do, said as people say it («créame un producto», «what
did I sell today?»), in English and Spanish: the selection of tools weighs them (``relevant``) and the QA of the
assistant is derived from them (``live.assistant_qa``). The Hub has hundreds of tools: an app is listed once all of
its tools say them.
"""

import pytest
from django.core import checks
from django.core.checks.registry import registry as check_registry
from live.assistant import asks_of
from live.checks import check_assistant_asks
from live.operations import AI, INTERNAL, Operation, registry
from ninja import Schema

NAME = "testapp.probe.run"
GOOD = {
    "en": ("make me a probe", "run the probe again"),
    "es": ("créame una sonda", "vuelve a pasar la sonda"),
}


class NoIn(Schema):
    pass


class Done(Schema):
    done: bool = True


def op(name=NAME, *, ai=None, permission="testapp.manage", kind="command"):
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


def e020(monkeypatch, settings, declared, *, listed=("testapp",), name=NAME):
    """The E020 messages for one operation registered with ``ai=declared``, its app listed or not."""
    settings.LIVE_ASSISTANT_ASKS_REQUIRED = listed
    monkeypatch.setitem(registry, name, op(name, ai=declared))
    return [message for message in check_assistant_asks() if name in message.msg]


# ── The declaration and its reader ────────────────────────────────────────────────────────────────────────────────


def test_a_tool_says_no_asks_by_default():
    assert AI(description="Creates a thing.").asks == {}


def test_a_tool_declares_what_a_person_would_type_by_language():
    declared = AI(description="Creates a thing.", asks=GOOD)
    assert declared.asks == GOOD
    assert asks_of(op(ai=declared)) == GOOD


def test_a_dictionary_declares_them_too_and_its_spec_keeps_them():
    spec = op(ai={"description": "Creates a thing.", "asks": GOOD}).ai_spec()
    assert spec == AI(description="Creates a thing.", asks=GOOD)
    assert asks_of(op(ai={"description": "Creates a thing.", "asks": GOOD})) == GOOD


def test_the_reader_cleans_what_it_reads():
    """Spaces around a phrase, an empty one, a repeated one and a list instead of a tuple; a lone phrase is one."""
    declared = {"description": "Creates a thing.", "asks": {"es": [" créame una sonda ", "", "créame una sonda"],
                                                             "en": "make me a probe", "fr": 3}}
    assert asks_of(op(ai=declared)) == {"es": ("créame una sonda",), "en": ("make me a probe",)}


@pytest.mark.parametrize("declared", [None, INTERNAL, AI(description="Creates a thing."), {"description": "x"},
                                      {"description": "x", "asks": ["a", "b"]}])
def test_what_declares_no_asks_reads_none(declared):
    assert asks_of(op(ai=declared)) == {}


@pytest.mark.parametrize(
    ("ai", "permission"),
    [
        ({"description": "Not an assistant tool (a PIN is typed on the pad).", "asks": GOOD}, "testapp.manage"),
        ({"description": "Platform reaction: forget a probe.", "asks": GOOD}, None),
        ({"description": "Platform reaction: forget a probe.", "asks": GOOD}, "testapp.system"),
    ],
)
def test_a_dictionary_that_is_no_tool_says_no_asks(ai, permission):
    """What ``ai_spec()`` reads as ``INTERNAL`` is never offered, so nothing asks for it."""
    assert op(ai=ai, permission=permission).ai_spec() is INTERNAL
    assert asks_of(op(ai=ai, permission=permission)) == {}


# ── live.E020 ─────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_check_is_registered_with_the_live_tag():
    assert check_assistant_asks in check_registry.get_checks()
    assert check_assistant_asks.tags == ("live",)


def test_an_app_not_listed_needs_no_asks(monkeypatch, settings):
    assert e020(monkeypatch, settings, AI(description="Creates a thing."), listed=()) == []


def test_nothing_is_listed_by_default(monkeypatch, settings):
    del settings.LIVE_ASSISTANT_ASKS_REQUIRED
    monkeypatch.setitem(registry, NAME, op(ai=AI(description="Creates a thing.")))
    assert [message for message in check_assistant_asks() if NAME in message.msg] == []


def test_a_tool_of_a_listed_app_without_asks_fails(monkeypatch, settings):
    [message] = e020(monkeypatch, settings, AI(description="Creates a thing."))
    assert message.id == "live.E020"
    assert message.obj == NAME
    assert "declares no asks" in message.msg
    assert "asks=" in message.hint and "LIVE_ASSISTANT_ASKS_REQUIRED" in message.hint


@pytest.mark.parametrize(
    "declared",
    [
        AI(description="Creates a thing.", asks=GOOD),
        {"description": "Creates a thing.", "asks": GOOD},
        AI(description="Creates a thing.", asks={**GOOD, "ca": ("crea'm una sonda",)}),
        INTERNAL,
        {"description": "Not an assistant tool (the screen's)."},
    ],
)
def test_a_tool_with_its_asks_or_what_is_no_tool_passes(monkeypatch, settings, declared):
    assert e020(monkeypatch, settings, declared) == []


@pytest.mark.parametrize(
    ("asks", "problem"),
    [
        ({"en": GOOD["en"]}, "no asks in 'es'"),
        ({"es": GOOD["es"]}, "no asks in 'en'"),
        ({**GOOD, "es": ("créame una sonda",)}, "1 distinct ask in 'es'; it needs at least 2"),
        ({**GOOD, "es": ("Créame una sonda", " créame  una sonda ")}, "1 distinct ask in 'es'"),
        ({**GOOD, "en": ("make me a probe", NAME)}, f"an ask in 'en' that is its own name ({NAME!r})"),
        ({**GOOD, "en": ("make me a probe", "testapp__probe__RUN")}, "an ask in 'en' that is its own name"),
        ({**GOOD, "es": (*GOOD["es"], "x" * 121)}, "an ask in 'es' longer than 120 characters"),
        ({**GOOD, "es": (*GOOD["es"], "  ")}, "an empty ask in 'es'"),
        ({**GOOD, "es": "créame una sonda"}, "asks['es'] must be a tuple of phrases"),
        ({**GOOD, "es": (*GOOD["es"], 7)}, "asks['es'] has 7, which is not a phrase"),
        (["créame una sonda", "make me a probe"], "which is not a mapping of language → phrases"),
    ],
)
def test_asks_that_tell_little_fail(monkeypatch, settings, asks, problem):
    messages = e020(monkeypatch, settings, AI(description="Creates a thing.", asks=asks))
    assert [message.id for message in messages] == ["live.E020"]
    assert problem in messages[0].msg


def test_a_dictionary_tool_of_a_listed_app_is_checked_too(monkeypatch, settings):
    [message] = e020(monkeypatch, settings, {"description": "Creates a thing.", "asks": {"es": GOOD["es"]}})
    assert "no asks in 'en'" in message.msg


def test_each_problem_is_one_message(monkeypatch, settings):
    messages = e020(monkeypatch, settings, AI(description="Creates a thing.", asks={"es": ("créame una sonda",)}))
    assert sorted(message.msg for message in messages) == [
        f"Operation {NAME!r} has 1 distinct ask in 'es'; it needs at least 2.",
        f"Operation {NAME!r} has no asks in 'en'.",
    ]


def test_only_the_tools_of_the_listed_apps_are_checked(monkeypatch, settings):
    settings.LIVE_ASSISTANT_ASKS_REQUIRED = ("other",)
    monkeypatch.setitem(registry, NAME, op(ai=AI(description="Creates a thing.")))
    monkeypatch.setitem(registry, "other.thing.create", op("other.thing.create", ai=AI(description="Creates.")))
    names = [message.obj for message in check_assistant_asks()]
    assert names == ["other.thing.create"]


@pytest.mark.parametrize(
    ("listed", "problem"),
    [
        ("testapp", "LIVE_ASSISTANT_ASKS_REQUIRED is 'testapp'; it must be a tuple of app labels"),
        (("testapp", "nosuchapp"), "LIVE_ASSISTANT_ASKS_REQUIRED names 'nosuchapp', which has no operation"),
    ],
)
def test_a_list_that_would_check_nothing_fails(monkeypatch, settings, listed, problem):
    """A label as a bare string (its letters) or one with no operation (a typo) would pass every tool unchecked."""
    settings.LIVE_ASSISTANT_ASKS_REQUIRED = listed
    messages = [message for message in check_assistant_asks() if "LIVE_ASSISTANT_ASKS_REQUIRED" in message.msg]
    assert [(message.id, problem in message.msg) for message in messages] == [("live.E020", True)]


def test_the_installed_apps_pass():
    assert [message for message in checks.run_checks(tags=["live"]) if message.id == "live.E020"] == []
