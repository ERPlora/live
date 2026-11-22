"""``live.E026``: a field marked ``json_schema_extra={"requires": "<permission>"}`` names a permission an app declares,
and in an operation's answer it admits null, the value whoever lacks that permission gets.

Without it, an answer would claim a number where it sends null, and a misspelt permission would hide the field from
everyone but whoever holds them all.
"""

from types import SimpleNamespace

import pytest
from django.core.checks.registry import registry as check_registry
from live.checks_sensitive import check_marked_fields
from ninja import Field, Schema

from tests.startup_checks import checks_registered_at_startup

COSTS = "stock.view_costs"


def requires(permission):
    return {"json_schema_extra": {"requires": permission}}


class Plain(Schema):
    name: str = ""


class NullableCost(Schema):
    cost: int | None = Field(None, **requires(COSTS))


class NumberCost(Schema):
    cost: int = Field(0, **requires(COSTS))


class Line(Schema):
    sku: str
    cost: int = Field(0, **requires(COSTS))


class Order(Schema):
    lines: list[Line] = []


class OtherOrder(Schema):
    first: Line | None = None


class Category(Schema):
    name: str
    margin: int | None = Field(None, **requires(COSTS))
    children: list["Category"] = []


class CostFilter(Schema):
    max_cost: int = Field(**requires(COSTS))


def op(name, *, input=Plain, output=Plain):
    return SimpleNamespace(name=name, input=input, output=output)


@pytest.fixture
def run(monkeypatch):
    """Run the check over the given operations, as if they were the registered ones, with ``stock``'s permissions."""

    def run(*operations, declared=(COSTS,)):
        monkeypatch.setattr("live.checks_sensitive.registry", {each.name: each for each in operations})
        monkeypatch.setattr("live.checks_sensitive.declared_permissions", lambda: frozenset(declared))
        return check_marked_fields(app_configs=None)

    return run


def messages(errors):
    assert {error.id for error in errors} <= {"live.E026"}
    return [error.msg for error in errors]


def test_the_check_is_registered_with_the_live_tag():
    assert check_marked_fields in check_registry.get_checks()
    assert check_marked_fields.tags == ("live",)


def test_django_setup_registers_the_check_without_anyone_importing_it():
    """A fresh process, where no test imported ``live.checks_sensitive`` first: the live app's startup does."""
    assert "live.checks_sensitive.check_marked_fields" in checks_registered_at_startup()


def test_operations_without_marks_pass(run):
    assert run(op("stock.product.list")) == []


def test_a_marked_field_of_an_answer_that_admits_null_passes(run):
    assert run(op("stock.product.get", output=NullableCost)) == []


def test_a_marked_field_of_an_answer_that_does_not_admit_null_fails(run):
    assert messages(run(op("stock.product.get", output=NumberCost))) == [
        "Field NumberCost.cost of the answer of 'stock.product.get' does not admit null, which is what whoever lacks"
        " 'stock.view_costs' gets."
    ]


def test_a_marked_field_deep_in_an_answer_is_checked(run):
    assert messages(run(op("stock.order.get", output=Order))) == [
        "Field Line.cost of the answer of 'stock.order.get' does not admit null, which is what whoever lacks"
        " 'stock.view_costs' gets."
    ]


def test_a_marked_field_of_an_input_need_not_admit_null(run):
    """An input's marked field is refused to whoever lacks the permission, never answered as null."""
    assert run(op("stock.product.list", input=CostFilter)) == []


def test_a_schema_that_holds_itself_is_checked_once(run):
    assert run(op("stock.category.tree", output=Category)) == []


def test_a_field_answered_by_two_operations_is_told_once(run):
    errors = run(op("stock.order.get", output=Order), op("stock.order.first", output=OtherOrder))

    assert messages(errors) == [
        "Field Line.cost of the answer of 'stock.order.first' does not admit null, which is what whoever lacks"
        " 'stock.view_costs' gets."
    ]


@pytest.mark.parametrize("schema_role", ["input", "output"])
def test_a_mark_with_a_permission_no_app_declares_fails(run, schema_role):
    errors = run(op("stock.product.get", **{schema_role: NullableCost}), declared=("stock.view",))

    role = "answer" if schema_role == "output" else "input"
    assert messages(errors) == [
        f"Field NullableCost.cost of the {role} of 'stock.product.get' requires 'stock.view_costs', which no app"
        " declares."
    ]


@pytest.mark.parametrize("permission", ["", 7])
def test_a_mark_that_names_no_permission_fails(run, permission):
    class Blank(Schema):
        cost: int | None = Field(None, json_schema_extra={"requires": permission})

    assert messages(run(op("stock.product.get", output=Blank))) == [
        "Field Blank.cost of the answer of 'stock.product.get' names no permission to require."
    ]
