"""The assistant's mechanics that do not depend on a gateway (``live.assistant``; PLAN §30,
docs/plans/2026-10-30-asistente-saas.md §2): which operations are a person's tools, the few a turn offers, how a tool
is told to the model, what a write's card says before it runs and what the person types to confirm it, how a tool runs
as the person, what a dangerous write will do (its preview) and the rounds of tools of a request.

The Hub's ``base.assistant`` and the SaaS's panel both use them; the Hub's own words (its business's zone and currency,
the records its reads name) come in through ``Words``. These tests use the package's ``PlainWords``.
"""

import datetime as dt
import json
import uuid
from typing import Literal

import pytest
from django.apps import apps
from live import assistant
from live.context import OperationContext, Scope
from live.errors import Conflict, PermissionDenied
from live.operations import AI, INTERNAL, Operation, registry
from ninja import Field, Schema
from pydantic import SecretStr

SCOPE = Scope("hub", "a")


def ctx(*permissions, language="en"):
    return OperationContext(scope=SCOPE, actor="ana", permissions=frozenset(permissions), language=language)


class NoIn(Schema):
    pass


class Done(Schema):
    done: bool = True


class LineIn(Schema):
    label: str
    amount: int = Field(json_schema_extra={"money": True})


class ThingIn(Schema):
    name: str
    note: str | None = None
    price: int | None = Field(None, json_schema_extra={"money": True})
    counted: int | None = Field(None, title="Counted cash", json_schema_extra={"money": True, "signed": True})
    password: SecretStr | None = None
    idempotency_key: str | None = Field(None, json_schema_extra={"attempt_key": True})
    thing: uuid.UUID | None = None
    when: dt.datetime | None = None
    day: dt.date | None = None
    at: dt.time | None = None
    lines: list[LineIn] = []


class IdsIn(Schema):
    ids: list[str]


class SummaryIn(Schema):
    name: str


class SummaryOut(Schema):
    total: int = Field(json_schema_extra={"money": True})
    note: str
    empty: str = ""


class LongOut(Schema):
    text: str


def op(name, *, ai=None, kind="command", permission="testapp.manage", input=NoIn, output=Done, fn=None):
    return Operation(
        name=name,
        kind=kind,
        permission=permission,
        input=input,
        output=output,
        expose_api=False,
        ai=ai,
        fn=fn or (lambda ctx, data: {"done": True}),
        database=False,
    )


CREATE = AI(description="Creates a thing with its name.")
LIST = AI(description="Lists the things by name.")


@pytest.fixture
def probes(monkeypatch):
    """Operations of the test app registered for one test, every shape of ``ai=``."""
    declared = {
        "testapp.probe.list": op("testapp.probe.list", ai=LIST, kind="query", permission="testapp.view"),
        "testapp.probe.create": op("testapp.probe.create", ai=CREATE, input=ThingIn),
        "testapp.probe.reset": op("testapp.probe.reset", ai=AI(description="Empties every thing.", risk="high")),
        "testapp.probe.internal": op("testapp.probe.internal", ai=INTERNAL, permission="testapp.view"),
        "testapp.probe.legacy": op("testapp.probe.legacy", ai={"description": "Counts the things."}, permission="testapp.view"),
        "testapp.probe.platform": op(
            "testapp.probe.platform", ai={"description": "Platform reaction: forget a thing."}, permission="testapp.system"
        ),
        "testapp.probe.open": op("testapp.probe.open", ai=AI(description="Opens the catalogue."), permission=None),
        "testapp.probe.unsaid": op("testapp.probe.unsaid", ai=None, permission="testapp.view"),
    }
    for name, declared_op in declared.items():
        monkeypatch.setitem(registry, name, declared_op)
    return declared


def probe_names(tools):
    return [name for name in tools if name.startswith("testapp.probe.")]


# ── Tools ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_tool_is_named_without_dots_and_read_back_from_its_name(probes):
    assert assistant.tool_name("testapp.probe.create") == "testapp__probe__create"
    assert assistant.operation_of("testapp__probe__create", probes).name == "testapp.probe.create"
    assert assistant.operation_of("testapp__probe__nothing", probes) is None
    # Offered or not, a registered tool is named back (a receipt names what it refused).
    assert assistant.named("testapp__probe__platform") is probes["testapp.probe.platform"]


def test_what_a_declaration_says_of_the_tool(probes):
    assert assistant.description(probes["testapp.probe.create"]) == "Creates a thing with its name."
    assert assistant.description(probes["testapp.probe.legacy"]) == "Counts the things."
    assert assistant.description(probes["testapp.probe.internal"]) == ""
    assert assistant.description(probes["testapp.probe.unsaid"]) == ""
    assert assistant.risk(probes["testapp.probe.reset"]) == "high"
    assert assistant.risk(probes["testapp.probe.create"]) == "normal"
    assert assistant.risk(op("testapp.probe.x", ai={"description": "Voids.", "risk": "high"})) == "high"
    assert assistant.risk(probes["testapp.probe.internal"]) == "normal"


def test_a_tool_is_what_its_declaration_says_and_what_the_chat_may_do(probes):
    tools = {name for name, declared in probes.items() if assistant.is_tool(declared)}
    assert tools == {
        "testapp.probe.list",
        "testapp.probe.create",
        "testapp.probe.reset",
        "testapp.probe.legacy",
        "testapp.probe.open",
    }
    assert not assistant.is_tool(probes["testapp.probe.reset"], not_from_chat=frozenset({"testapp.probe.reset"}))


def test_the_catalogue_is_the_persons_tools_of_the_apps_on_in_name_order(probes):
    tools = assistant.catalog(ctx("testapp.view"), active_labels={"testapp"})
    assert probe_names(tools) == ["testapp.probe.legacy", "testapp.probe.list", "testapp.probe.open"]
    every = assistant.catalog(ctx("*"), active_labels={"testapp"}, not_from_chat=frozenset({"testapp.probe.reset"}))
    assert probe_names(every) == [
        "testapp.probe.create",
        "testapp.probe.legacy",
        "testapp.probe.list",
        "testapp.probe.open",
    ]
    assert assistant.catalog(ctx("*"), active_labels=set()) == {}


def test_a_write_a_manager_may_approve_is_in_the_catalogue_of_who_asks_for_it(probes):
    approvable = {"testapp.probe.create"}
    tools = assistant.catalog(ctx("testapp.view"), active_labels={"testapp"}, approvable=lambda op: op.name in approvable)
    assert "testapp.probe.create" in tools
    assert "testapp.probe.reset" not in tools


# ── By relevance ──────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_app_named_and_the_verb_asked_rank_first_after_what_is_always_at_hand(probes):
    other = op("demo.item.list", ai=AI(description="Lists the demo items."), kind="query")
    tools = {**{name: probes[name] for name in ("testapp.probe.create", "testapp.probe.list")}, "demo.item.list": other}
    offered = [o.name for o in assistant.relevant(tools, ["Show me my things"], "en")]
    assert offered == ["testapp.probe.list", "testapp.probe.create", "demo.item.list"]
    always = [o.name for o in assistant.relevant(tools, ["crea una cosa"], "es", always=("demo.item.list",))]
    assert always[:2] == ["demo.item.list", "testapp.probe.create"]


def test_a_turn_offers_at_most_its_share():
    tools = {f"testapp.many.n{i}": op(f"testapp.many.n{i}", ai=CREATE) for i in range(assistant.MAX_TOOLS + 5)}
    assert len(assistant.relevant(tools, ["hola"], "es")) == assistant.MAX_TOOLS


def test_the_words_of_an_app_are_its_label_its_name_and_its_menu():
    words = assistant.app_words("testapp", "en")
    assert {"testa", "thing"} <= words


def test_a_tool_is_offered_in_the_gateways_format(probes):
    spec = assistant.tool_spec(probes["testapp.probe.create"])
    assert (spec["type"], spec["name"], spec["description"]) == (
        "function",
        "testapp__probe__create",
        "Creates a thing with its name.",
    )
    assert spec["parameters"]["properties"]["name"]["type"] == "string"


# ── The card of a write ───────────────────────────────────────────────────────────────────────────────────────────


def fields(card):
    return {field["name"]: field for field in card["fields"]}


def test_a_normal_write_asks_a_click_and_shows_what_it_will_send(probes):
    card = assistant.card(probes["testapp.probe.create"], {"name": "Mesa 4", "note": None}, "en")
    assert {key: card[key] for key in ("operation", "app", "action", "risk", "count", "confirm_word", "blocked")} == {
        "operation": "testapp.probe.create",
        "app": "testapp",
        "action": "create",
        "risk": "normal",
        "count": None,
        "confirm_word": "",
        "blocked": False,
    }
    assert card["app_name"] == str(apps.get_app_config("testapp").verbose_name)
    shown = fields(card)
    # Named as the app's model names its field (``Thing.name``), never by its technical name.
    assert shown["name"] == {"name": "name", "label": "Name", "kind": "text", "value": "Mesa 4"}
    assert shown["note"]["kind"] == "empty"


def test_a_dangerous_write_asks_to_type_the_word_in_the_persons_language(probes):
    reset = probes["testapp.probe.reset"]
    assert assistant.card(reset, {}, "en")["confirm_word"] == "CONFIRM"
    card = assistant.card(reset, {}, "es")
    assert card["confirm_word"] == "CONFIRMAR"
    assert assistant.confirmed(card, "  confirmar ")
    assert not assistant.confirmed(card, "CONFIRMA")
    assert assistant.confirmed(assistant.card(probes["testapp.probe.create"], {"name": "x"}, "es"), "")


def test_one_over_records_asks_how_many_and_one_that_names_none_is_blocked():
    void = op("testapp.probe.void", ai=AI(description="Voids things.", risk="high"), input=IdsIn)
    card = assistant.card(void, {"ids": ["a", "b", "c"]}, "es")
    assert (card["count"], card["confirm_word"], card["blocked"]) == (3, "3", False)
    assert assistant.confirmed(card, "3") and not assistant.confirmed(card, "CONFIRMAR")
    blocked = assistant.card(void, {"ids": []}, "es")
    assert blocked["blocked"] and not assistant.confirmed(blocked, blocked["confirm_word"])


def test_an_amount_is_money_in_the_plain_currency_at_any_depth(probes):
    card = assistant.card(
        probes["testapp.probe.create"],
        {"name": "x", "price": 1500, "counted": -250, "lines": [{"label": "Corte", "amount": 1500}]},
        "en",
    )
    euros = {"currency": "EUR", "decimals": 2}
    shown = fields(card)
    assert shown["price"] == {**shown["price"], "kind": "money", "value": 1500, "money": euros}
    assert shown["counted"] == {**shown["counted"], "kind": "money", "signed": True, "titled": True, "label": "Counted cash"}
    assert shown["lines"]["value"] == [{"label": "Corte", "amount": {"kind": "money", "value": 1500, "money": euros}}]


def test_a_secret_is_hidden_and_what_nobody_can_judge_is_left_out(probes):
    arguments = {"name": "x", "password": "hunter2", "idempotency_key": "k-1", "thing": str(uuid.uuid4())}
    shown = fields(assistant.card(probes["testapp.probe.create"], arguments, "en"))
    assert shown["password"]["value"] == assistant.HIDDEN
    # An attempt key and a record the plain words cannot name (no read): never on the card, never by an id.
    assert "idempotency_key" not in shown and "thing" not in shown
    assert "hunter2" not in json.dumps(shown)


@pytest.mark.parametrize(
    "language, expected",
    [
        ("en", {"when": "Oct. 30, 2026, 12:05 p.m.", "day": "Oct. 30, 2026", "at": "2:05 p.m."}),
        ("es", {"when": "30 de octubre de 2026 a las 12:05", "day": "30 de octubre de 2026", "at": "14:05"}),
    ],
)
def test_a_moment_is_said_in_the_persons_language_at_utc(probes, language, expected):
    arguments = {"name": "x", "when": "2026-10-30T14:05:00+02:00", "day": "2026-10-30", "at": "14:05"}
    shown = fields(assistant.card(probes["testapp.probe.create"], arguments, language))
    assert {name: shown[name]["value"] for name in expected} == expected
    assert fields(assistant.card(probes["testapp.probe.create"], {"name": "x", "day": "soon"}, "en"))["day"]["value"] == "soon"


class SpokenWords(assistant.PlainWords):
    """A project's own words: a record by its name, a moment its way, its own name for the app, its own amounts."""

    def reference(self, value, prop):
        return "Table 5"

    def moment(self, value, kind):
        return f"{kind}:{value}"

    def amount(self, value):
        return f"{value / 100:.2f} $"

    def app_name(self):
        return "Things"


def test_the_card_says_each_datum_with_the_words_it_is_given(probes):
    create = probes["testapp.probe.create"]
    arguments = {"name": "x", "thing": str(uuid.uuid4()), "day": "2026-10-30", "lines": [{"label": "a", "amount": 250}]}
    card = assistant.card(create, arguments, "en", SpokenWords(create, "en"))
    shown = fields(card)
    assert card["app_name"] == "Things"
    assert (shown["thing"]["value"], shown["day"]["value"]) == ("Table 5", "date:2026-10-30")
    assert shown["lines"]["value"] == [{"label": "a", "amount": "2.50 $"}]


class ListsIn(Schema):
    tags: list[str] = []
    things: list[uuid.UUID] = []
    days: list[dt.date] = []
    sizes: list[Literal["s", "m"]] = []
    prices_cents: list[int] = []
    lines: list[LineIn] = []


LISTS = {
    "tags": ["sale.sale.create", "vip"],
    "things": [str(uuid.uuid4()), str(uuid.uuid4())],
    "days": ["2026-11-02", "2026-11-09"],
    "sizes": ["s", "m"],
    "prices_cents": [150, 1200],
    "lines": [{"label": "a", "amount": 250}],
}


@pytest.fixture
def lists(monkeypatch):
    """A write of every kind of list, and the labels its app gives a closed list: «s» and «m»."""
    monkeypatch.setattr(assistant, "choice_label", lambda app, entity, name, value: {"s": "Small", "m": "Medium"}.get(value))
    return op("testapp.probe.lists", ai=CREATE, input=ListsIn)


def named(card) -> dict:
    return {name: shown.get(assistant.NAMED, False) for name, shown in fields(card).items()}


def test_a_list_the_card_says_in_words_is_marked_named_one_as_sent_is_not(lists):
    """FIX-HUB-PRINTING-ASSISTANT-CARD-LEAVES-OUT-ITS-RECORDS: the screen says the items of a list only when the server
    said each one in words — a record by its name, a moment, a value of a closed list by its label, an amount —; a list
    of texts sent as they are (codes nobody names: «sale.sale.create») or of lines says how many it carries."""
    card = assistant.card(lists, LISTS, "en", SpokenWords(lists, "en"))
    assert named(card) == {"tags": False, "things": True, "days": True, "sizes": True, "prices_cents": True, "lines": False}
    shown = fields(card)
    assert shown["things"]["value"] == ["Table 5", "Table 5"]
    assert shown["sizes"]["value"] == ["Small", "Medium"]
    assert shown["tags"]["value"] == ["sale.sale.create", "vip"]


def test_records_the_card_leaves_out_are_still_said_in_words_never_by_their_id(lists):
    """No read names them (``PlainWords``): each is none, and the list still says how many, never an id."""
    shown = fields(assistant.card(lists, {"things": LISTS["things"]}, "en"))
    assert (shown["things"]["value"], shown["things"].get(assistant.NAMED)) == ([None, None], True)


def test_a_list_with_one_item_left_as_sent_is_not_named(lists, monkeypatch):
    """A value of a closed list its app gives no label, or a moment that is none: as sent, so the list is not named."""
    monkeypatch.setattr(assistant, "choice_label", lambda app, entity, name, value: {"s": "Small"}.get(value))
    card = assistant.card(lists, {"sizes": ["s", "m"], "days": ["2026-11-02", "soon"]}, "en")
    assert named(card) == {"sizes": False, "days": False}


# ── A tool, run as the person ─────────────────────────────────────────────────────────────────────────────────────


def test_a_tool_runs_by_its_own_operation_and_answers_its_result():
    ran = op("testapp.probe.run", input=SummaryIn, fn=lambda ctx, data: {"done": data.name == "x"})
    assert assistant.run_tool(ctx("testapp.manage"), ran, '{"name": "x"}') == assistant.ToolOutcome(
        "ok", "", '{"done":true}'
    )


@pytest.mark.parametrize("arguments", ["nope", "[1]", "3"])
def test_what_is_no_json_object_is_refused_as_invalid(arguments):
    outcome = assistant.run_tool(ctx("testapp.manage"), op("testapp.probe.run"), arguments)
    assert (outcome.outcome, outcome.code) == ("error", "invalid_payload")


def test_data_that_does_not_fit_says_which():
    outcome = assistant.run_tool(ctx("testapp.manage"), op("testapp.probe.run", input=SummaryIn), "{}")
    assert (outcome.outcome, outcome.code) == ("error", "invalid_payload")
    assert set(json.loads(outcome.content)["error"]["fields"]) == {"name"}


def test_what_the_person_may_not_do_is_refused_and_what_the_operation_refuses_is_an_error():
    refused = assistant.run_tool(ctx("testapp.view"), op("testapp.probe.run"), "{}")
    assert (refused.outcome, refused.code) == ("refused", PermissionDenied.code)

    def reject(ctx, data):
        raise Conflict("The thing was rejected.", code="testapp.thing_rejected")

    failed = assistant.run_tool(ctx("testapp.manage"), op("testapp.probe.run", fn=reject), "{}")
    assert (failed.outcome, failed.code) == ("error", "testapp.thing_rejected")
    assert json.loads(failed.content) == {"error": {"code": "testapp.thing_rejected", "message": "The thing was rejected."}}


def test_a_result_too_long_for_the_model_is_cut():
    long = op("testapp.probe.long", output=LongOut, fn=lambda ctx, data: {"text": "x" * assistant.MAX_RESULT_CHARS})
    outcome = assistant.run_tool(ctx("testapp.manage"), long, "")
    assert outcome.outcome == "ok"
    assert outcome.content.endswith(" …(cut)")
    assert len(outcome.content) == assistant.MAX_RESULT_CHARS + len(" …(cut)")


def test_an_error_is_told_back_as_one_json_object():
    assert json.loads(assistant.error_content("x.y", "No.", {"name": "Required."})) == {
        "error": {"code": "x.y", "message": "No.", "fields": {"name": "Required."}}
    }
    assert json.loads(assistant.error_content("x.y", "No.")) == {"error": {"code": "x.y", "message": "No."}}


# ── What a dangerous write will do ────────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def summary(monkeypatch):
    seen = {}

    def read(ctx, data):
        seen["name"] = data.name
        return {"total": 4200, "note": "Two things", "empty": ""}

    monkeypatch.setitem(
        registry,
        "testapp.probe.summary",
        op("testapp.probe.summary", ai=INTERNAL, kind="query", permission="testapp.view", input=SummaryIn, output=SummaryOut, fn=read),
    )
    return seen


def test_a_preview_is_the_read_its_declaration_names_run_as_the_person(summary):
    write = op(
        "testapp.probe.close",
        ai=AI(description="Closes.", risk="high", preview={"operation": "testapp.probe.summary", "fields": ["total", "note", "empty"]}),
        input=ThingIn,
    )
    failure, shown = assistant.preview(ctx("testapp.view", "testapp.manage"), write, {"name": "x", "note": "left out"})
    assert failure is None and summary == {"name": "x"}
    assert [(field["name"], field["kind"], field["value"]) for field in shown] == [
        ("total", "money", 4200),
        ("note", "text", "Two things"),
    ]
    assert shown[0]["money"] == {"currency": "EUR", "decimals": 2}

    failure, shown = assistant.preview(ctx("testapp.manage"), write, {"name": "x"})
    assert (failure.outcome, shown) == ("refused", None)
    assert assistant.preview(ctx("*"), op("testapp.probe.plain", ai=CREATE), {}) == (None, None)
    assert assistant.preview_of(write) == {"operation": "testapp.probe.summary", "fields": ["total", "note", "empty"]}


# ── Rounds of tools ───────────────────────────────────────────────────────────────────────────────────────────────


def test_the_rounds_are_the_models_tool_requests_since_the_persons_last_message():
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "tool_calls": [{"id": "1"}]},
        {"role": "tool", "content": "{}"},
        {"role": "user", "content": "and now?"},
        {"role": "assistant", "tool_calls": [{"id": "2"}]},
        {"role": "tool", "content": "{}"},
        {"role": "assistant", "content": "thinking", "tool_calls": [{"id": "3"}]},
        {"role": "assistant", "content": "done"},
    ]
    assert assistant.rounds(messages) == 2
    assert assistant.rounds([]) == 0
    assert assistant.MAX_ROUNDS == 6
