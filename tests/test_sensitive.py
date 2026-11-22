"""A field only whoever holds a permission sees: ``json_schema_extra={"requires": "<permission>"}`` on a schema's field.

Every door (a route, a live stream, the assistant, an API key) calls an operation, so the operation applies the mark
for its caller: its answer carries the field as null to whoever lacks the permission, at any depth (an object inside
another, a list or a map of them), and an input that fills such a field (a filter, a line of a write) with anything but
its default is refused with a 403, as an operation the caller may not run. Whoever holds the permission gets the field
as the operation wrote it.
"""

import json

import pytest
from django.utils import translation
from live.assistant import run_tool
from live.context import OperationContext, Scope
from live.errors import PermissionDenied
from live.operations import INTERNAL, operation, registry
from ninja import Field, Schema

SCOPE = Scope("hub", "a")
COSTS = "stock.view_costs"
CONTACT = "stock.view_contact"


class SupplierOut(Schema):
    name: str
    phone: str | None = Field(None, json_schema_extra={"requires": CONTACT})


class LineOut(Schema):
    sku: str
    cost: int | None = Field(None, json_schema_extra={"requires": COSTS})


class ProductOut(Schema):
    name: str
    cost: int | None = Field(None, json_schema_extra={"requires": COSTS})
    supplier: SupplierOut | None = None
    lines: list[LineOut] = []
    by_store: dict[str, LineOut] = {}
    pair: tuple[LineOut, ...] = ()


class ProductListIn(Schema):
    search: str = ""
    max_cost: int | None = Field(None, json_schema_extra={"requires": COSTS})


class ProductListOut(Schema):
    items: list[ProductOut]


class LineIn(Schema):
    sku: str
    unit_cost: int | None = Field(None, json_schema_extra={"requires": COSTS})


class ReceiveIn(Schema):
    lines: list[LineIn] = []
    by_store: dict[str, LineIn] = {}


class Done(Schema):
    ok: bool = True


ONE_PRODUCT = {
    "name": "Coffee",
    "cost": 120,
    "supplier": {"name": "Beans Co", "phone": "600111222"},
    "lines": [{"sku": "C-1", "cost": 100}, {"sku": "C-2", "cost": 140}],
    "by_store": {"centre": {"sku": "C-1", "cost": 110}},
    "pair": ({"sku": "P-1", "cost": 50},),
}


@pytest.fixture(autouse=True)
def isolated_registry():
    saved = dict(registry)
    yield
    registry.clear()
    registry.update(saved)


def as_person(*permissions):
    return OperationContext(scope=SCOPE, actor="ana", permissions=frozenset(("stock.view", *permissions)))


def declare(name="stock.product.list", *, kind="query", body=None, input=ProductListIn, output=ProductListOut,
            **options):
    """Register an ad-hoc operation of the ``stock`` app that answers ``body(ctx, data)`` (one product by default)."""

    def fn(ctx, data):
        return body(ctx, data) if body else {"items": [ONE_PRODUCT]}

    fn.__module__ = "stock.queries" if kind == "query" else "stock.services"
    return operation(name, kind=kind, permission="stock.view", input=input, output=output, ai=INTERNAL, **options)(fn)


# The answer


@pytest.mark.django_db
def test_whoever_lacks_the_permission_gets_the_marked_field_as_null():
    answer = declare()(as_person(), ProductListIn())

    product = answer.items[0]
    assert product.cost is None
    assert product.name == "Coffee"


@pytest.mark.django_db
def test_whoever_holds_the_permission_gets_the_field_as_written():
    answer = declare()(as_person(COSTS, CONTACT), ProductListIn())

    assert answer.model_dump() == {"items": [ONE_PRODUCT]}


@pytest.mark.django_db
def test_a_marked_field_is_null_at_any_depth():
    product = declare()(as_person(), ProductListIn()).items[0]

    assert product.supplier.phone is None
    assert [line.cost for line in product.lines] == [None, None]
    assert product.by_store["centre"].cost is None
    assert product.pair == (LineOut(sku="P-1"),)
    assert [line.sku for line in product.lines] == ["C-1", "C-2"]
    assert product.supplier.name == "Beans Co"


@pytest.mark.django_db
def test_each_mark_follows_its_own_permission():
    product = declare()(as_person(COSTS), ProductListIn()).items[0]

    assert product.cost == 120
    assert product.lines[1].cost == 140
    assert product.supplier.phone is None


@pytest.mark.django_db
def test_the_answer_is_still_the_operation_s_schema_and_serialises_the_field_as_null():
    answer = declare()(as_person(), ProductListIn())

    assert isinstance(answer, ProductListOut)
    assert answer.model_dump(mode="json")["items"][0]["cost"] is None


@pytest.mark.django_db
def test_the_objects_the_operation_answered_with_are_not_changed():
    """An operation may answer with an object it keeps (a cache, a constant): hiding a field for one person never
    takes it from the next one, who may see it."""
    kept = ProductListOut.model_validate({"items": [ONE_PRODUCT]})
    list_products = declare(body=lambda ctx, data: kept)

    assert list_products(as_person(), ProductListIn()).items[0].cost is None
    assert list_products(as_person(COSTS), ProductListIn()).items[0].cost == 120
    assert kept.items[0].lines[0].cost == 100


@pytest.mark.django_db
def test_a_command_answers_the_marked_field_as_null_too():
    receive = declare("stock.stock.receive", kind="command", input=ReceiveIn, output=ProductOut,
                      body=lambda ctx, data: ONE_PRODUCT)

    assert receive(as_person(), ReceiveIn(lines=[])).cost is None


def test_an_operation_that_touches_no_database_answers_the_marked_field_as_null_too():
    ask_supplier = declare(database=False)

    assert ask_supplier(as_person(), ProductListIn()).items[0].cost is None


@pytest.mark.django_db
def test_an_operation_run_by_another_answers_as_its_caller_may_see():
    """The assistant runs its tools inside its own turn: what a tool answers reaches the person as well."""
    list_products = declare()
    seen = []

    def turn(ctx, data):
        seen.append(list_products(ctx, ProductListIn()).items[0].cost)
        return {}

    declare("stock.assistant.turn", body=turn, output=Done)(as_person(), ProductListIn())

    assert seen == [None]


@pytest.mark.django_db
def test_the_assistant_s_tool_answers_the_marked_field_as_null():
    outcome = run_tool(as_person(), declare(), "{}")

    assert outcome.outcome == "ok"
    assert json.loads(outcome.content)["items"][0]["cost"] is None


# The input


def test_an_input_that_fills_a_marked_field_without_the_permission_is_refused():
    # No django_db mark: reaching the database would fail with a different error.
    with pytest.raises(PermissionDenied) as info:
        declare()(as_person(), ProductListIn(max_cost=500))

    assert info.value.status == 403
    assert info.value.envelope()["error"] == {
        "code": "permission_denied",
        "message": "Permission “stock.view_costs” is required.",
    }


def test_the_refusal_speaks_the_caller_s_language():
    with translation.override("es"), pytest.raises(PermissionDenied) as info:
        declare()(as_person(), ProductListIn(max_cost=500))

    assert info.value.envelope()["error"]["message"] == "Se necesita el permiso «stock.view_costs»."


@pytest.mark.parametrize(
    "data",
    [
        ReceiveIn(lines=[LineIn(sku="C-1"), LineIn(sku="C-2", unit_cost=90)]),
        ReceiveIn(by_store={"centre": LineIn(sku="C-1", unit_cost=90)}),
    ],
    ids=["a list", "a map"],
)
def test_a_marked_field_inside_the_input_is_refused_at_any_depth(data):
    received = []
    receive = declare("stock.stock.receive", kind="command", input=ReceiveIn, output=Done,
                      body=lambda ctx, data: received.append(data) or {})

    with pytest.raises(PermissionDenied):
        receive(as_person(), data)

    assert received == []


@pytest.mark.django_db
def test_an_input_that_leaves_the_marked_field_at_its_default_runs():
    list_products = declare()

    assert list_products(as_person(), ProductListIn(search="cof")).items[0].name == "Coffee"
    assert list_products(as_person(), ProductListIn(max_cost=None)).items[0].name == "Coffee"


@pytest.mark.django_db
def test_whoever_holds_the_permission_may_fill_the_marked_field():
    receive = declare("stock.stock.receive", kind="command", input=ReceiveIn, output=Done, body=lambda ctx, data: {})

    assert declare()(as_person(COSTS), ProductListIn(max_cost=500)).items[0].cost == 120
    assert receive(as_person(COSTS), ReceiveIn(lines=[LineIn(sku="C-1", unit_cost=90)])) == Done()


def test_the_operation_s_own_permission_is_asked_first():
    with pytest.raises(PermissionDenied) as info:
        declare()(OperationContext(scope=SCOPE, actor="ana"), ProductListIn(max_cost=500))

    assert info.value.envelope()["error"]["message"] == "Permission “stock.view” is required."


def test_the_assistant_hears_a_refused_filter_as_a_refusal():
    outcome = run_tool(as_person(), declare(), '{"max_cost": 500}')

    assert (outcome.outcome, outcome.code) == ("refused", "permission_denied")
