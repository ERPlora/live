"""The assistant's QA derived from its tools (``live.assistant_qa``): what a person would type to ask for each tool
(``AI.asks``) reaches it among the first offered (``misses``, layer 1: no model, no network, in every pull request),
which tools say nothing (``uncovered``), and the catalogue a QA with the real model derives its phrases from
(``export_catalog``, layer 2).

The Hub and the SaaS call them with their real catalogue (``live.assistant.catalog``) as each role: what a role may not
run is not in its catalogue at all.
"""

import json
from collections import Counter

import pytest
from ninja import Schema

from live import assistant, assistant_qa
from live.assistant_qa import Miss, export_catalog, misses, uncovered
from live.operations import Operation
from tests.test_assistant import Done, NoIn
from tests.test_assistant_relevance import NOISE, ProductIn, tool

PRODUCT_CREATE = tool(
    "inventory.product.create",
    "Create a product of the catalog with its tax category, its categories and, if given, its initial stock.",
    asks={"es": ("créame un producto", "añade un artículo al catálogo"), "en": ("add a product", "new item")},
)
PRODUCT_UPDATE = tool(
    "inventory.product.update",
    "Change a product, named by its id, SKU or name: its data, active or not, its stock control and its categories.",
    input=ProductIn,
    asks={"es": ("súbele el precio al café", "cambia el nombre del producto")},
)
#: A phrase that names another tool: a person who says it is offered the product's write, not this one.
WRONG = "cambia el precio del producto"
MEMBER_DELETE = tool(
    "staff.member.delete",
    "Removes a staff member from the team.",
    asks={"es": ("quita a Luis del equipo", WRONG), "en": ("remove Luis from the team",)},
)
SALE_TODAY = tool(
    "sale.sale.today",
    "What was sold today (business day) in cents, refunds taken off, and how many tickets.",
    "query",
    asks={"en": ("what did I sell today?", "today's takings")},
)
CATALOGUE = {op.name: op for op in [PRODUCT_CREATE, PRODUCT_UPDATE, MEMBER_DELETE, SALE_TODAY, *NOISE]}


def position(tools, ask, name, language="es", **kwargs):
    ranked = [op.name for op in assistant.relevant(tools, [ask], language, **kwargs)]
    return ranked.index(name) + 1 if name in ranked else None


# ── Layer 1: what is asked reaches its tool ───────────────────────────────────────────────────────────────────────


def test_an_ask_that_reaches_its_tool_among_the_first_is_no_miss():
    assert position(CATALOGUE, "créame un producto", "inventory.product.create") == 1
    found = [miss[:2] for miss in misses(CATALOGUE, language="es")]
    assert ("inventory__product__create", "créame un producto") not in found


def test_an_ask_that_names_another_tool_is_reported_with_its_position():
    found = position(CATALOGUE, WRONG, "staff.member.delete")
    assert found is not None and found > 1
    assert misses(CATALOGUE, language="es", top=1) == [Miss("staff__member__delete", WRONG, found)]
    # The first ``top`` offered pass: at its own position, it does.
    assert misses(CATALOGUE, language="es", top=found) == []
    assert misses(CATALOGUE, language="es", top=found - 1) == [Miss("staff__member__delete", WRONG, found)]


def test_an_ask_whose_tool_is_not_offered_at_all_has_no_position():
    """``relevant`` offers ``MAX_TOOLS`` at most: a tool behind them is never offered for that phrase."""
    drowning = [
        tool(f"noise.thing{i:02}.update", "Changes the price of a product.") for i in range(assistant.MAX_TOOLS + 5)
    ]
    lost = tool("zzz.member.delete", "Removes a member.", asks={"es": (WRONG, "quita a Luis del equipo")})
    tools = {op.name: op for op in [*drowning, lost]}
    assert misses(tools, language="es") == [Miss("zzz__member__delete", WRONG, None)]


def test_only_the_asks_of_the_language_are_tried():
    assert [miss.ask for miss in misses(CATALOGUE, language="en", top=1)] == []
    assert {miss.ask for miss in misses(CATALOGUE, language="es", top=1)} == {WRONG}


def test_what_is_always_at_hand_and_the_apps_words_are_the_turns():
    """``always`` and ``app_words`` are the ones the project's turn uses: the QA ranks as the chat does."""
    same = {"es": ("lo de siempre", "lo mismo de siempre")}
    tools = {op.name: op for op in (tool("a.thing.list", "Lists.", "query", asks=same),
                                    tool("b.thing.list", "Lists.", "query", asks=same))}
    behind = lambda name: [Miss(name, "lo de siempre", 2), Miss(name, "lo mismo de siempre", 2)]  # noqa: E731
    assert misses(tools, language="es", top=1) == behind("b__thing__list")
    assert misses(tools, language="es", top=1, always=["b.thing.list"]) == behind("a__thing__list")
    b_is_always = lambda label, language: assistant.stems("siempre") if label == "b" else frozenset()  # noqa: E731
    assert misses(tools, language="es", top=1, app_words=b_is_always) == behind("a__thing__list")


def test_the_misses_come_sorted_by_tool_and_phrase():
    bad = {"es": ("zz lista nada", "aa muestra nada"), "en": ("nothing at all",)}
    tools = {op.name: op for op in [tool(f"x.thing{i}.list", "Lists things.", "query") for i in range(3)]}
    tools |= {op.name: op for op in reversed([tool(f"y.other{i}.void", "Voids it.", asks=bad) for i in range(2)])}
    found = misses(tools, language="es", top=1)
    assert [(miss.tool_name, miss.ask) for miss in found] == [
        ("y__other0__void", "aa muestra nada"),
        ("y__other0__void", "zz lista nada"),
        ("y__other1__void", "aa muestra nada"),
        ("y__other1__void", "zz lista nada"),
    ]
    assert found == misses(tools, language="es", top=1)


def test_a_catalogue_of_the_hubs_size_is_ranked_reading_each_tool_once(monkeypatch):
    """~750 tools: every ask goes through ``relevant``, but what each tool says is read once for all of them."""
    read = Counter()
    real = assistant.asks_of
    monkeypatch.setattr(assistant, "asks_of", lambda op: read.update([op.name]) or real(op))
    tools = {op.name: op for op in (tool(f"app{i % 28}.thing{i}.create", f"Creates thing {i} of the business.")
                                    for i in range(730))}
    asked = [tool(f"zz.item{i}.create", "Creates an item.", asks={"es": (f"créame el item {i}", f"otro item {i}")})
             for i in range(20)]
    tools |= {op.name: op for op in asked}
    found = misses(tools, language="es", top=assistant.MAX_TOOLS)
    assert {miss.tool_name for miss in found} <= {assistant.tool_name(op.name) for op in asked}
    assert len(read) == len(tools) and set(read.values()) == {1}


@pytest.mark.parametrize("region", ["es-ES", "es_ES", "ES"])
def test_a_language_with_its_region_is_its_language(region):
    """``ctx.language`` may say the region (``es-ES``): the asks are by language, so it reads those of ``es``."""
    assert misses(CATALOGUE, language=region, top=1) == misses(CATALOGUE, language="es", top=1) != []
    assert uncovered(CATALOGUE, region) == uncovered(CATALOGUE, "es")
    assert export_catalog(CATALOGUE, region) == export_catalog(CATALOGUE, "es")


@pytest.mark.parametrize("top", [0, -1, assistant.MAX_TOOLS + 1])
def test_a_top_the_turn_never_offers_is_refused(top):
    with pytest.raises(ValueError, match="top"):
        misses(CATALOGUE, language="es", top=top)


def test_the_tools_that_say_nothing_in_a_language_are_uncovered():
    assert uncovered(CATALOGUE, "es")[:1] == ["appointment__thing00__create"]
    assert "sale__sale__today" in uncovered(CATALOGUE, "es")
    assert "sale__sale__today" not in uncovered(CATALOGUE, "en")
    assert "inventory__product__update" in uncovered(CATALOGUE, "en")
    covered = {"inventory__product__create", "inventory__product__update", "staff__member__delete"}
    assert set(uncovered(CATALOGUE, "es")) == {assistant.tool_name(name) for name in CATALOGUE} - covered
    assert uncovered(CATALOGUE, "es") == sorted(uncovered(CATALOGUE, "es"))


# ── Layer 2: the catalogue the real model's QA derives its phrases from ───────────────────────────────────────────


class Guarded(Schema):
    ids: list[str]


def test_the_catalogue_says_each_tool_as_the_qa_needs_it():
    void = Operation(
        name="sale.order.void",
        kind="command",
        permission="testapp.manage",
        input=Guarded,
        output=Done,
        expose_api=False,
        ai={"description": "Voids open checks.", "risk": "high", "asks": {"es": ("anula la cuenta de la mesa 3",)}},
        fn=lambda ctx, data: {"done": True},
        database=False,
    )
    tools = {op.name: op for op in (SALE_TODAY, void, PRODUCT_CREATE)}
    exported = export_catalog(tools, "es")
    assert [entry["name"] for entry in exported] == ["inventory.product.create", "sale.order.void", "sale.sale.today"]
    assert exported[1] == {
        "name": "sale.order.void",
        "tool_name": "sale__order__void",
        "app_label": "sale",
        "kind": "write",
        "permission": "testapp.manage",
        "risk": "high",
        "description": "Voids open checks.",
        "asks": ["anula la cuenta de la mesa 3"],
        "input_schema": Guarded.model_json_schema(),
    }
    assert (exported[2]["kind"], exported[2]["risk"], exported[2]["asks"]) == ("read", "normal", [])
    assert export_catalog(tools, "en")[2]["asks"] == ["what did I sell today?", "today's takings"]
    assert json.loads(json.dumps(exported)) == exported


def test_the_catalogue_of_no_tools_is_empty():
    assert export_catalog({}, "es") == []
    assert assistant_qa.misses({}, language="es") == [] and assistant_qa.uncovered({}, "es") == []


def test_an_operation_without_input_data_exports_its_empty_schema():
    [entry] = export_catalog({"x.thing.list": tool("x.thing.list", "Lists things.", "query")}, "es")
    assert entry["input_schema"] == NoIn.model_json_schema()
