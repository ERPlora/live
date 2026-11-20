"""The checks of a module's hooks, used on their own: what the app metadata check and the bell's check call.

``live.checks.check_app_metadata`` runs ``_hook_errors`` on every module (its rules, E009–E016 and E018, are tested
through that check in ``test_checks.py``), and ``live.checks_bell`` reads a query's rows with ``_row_fields``.
"""

from types import SimpleNamespace

import pytest
from live.checks_hooks import _hook_errors, _row_fields
from ninja import Schema


class RowOut(Schema):
    id: int
    at: str


class RowsOut(Schema):
    rows: list[RowOut]


class ItemsOut(Schema):
    items: list[RowOut]


class CountOut(Schema):
    count: int


class NumbersOut(Schema):
    rows: list[int]


@pytest.mark.parametrize("output", [RowsOut, ItemsOut])
def test_the_rows_of_a_query_are_the_fields_of_its_listed_model(output):
    assert _row_fields(output) == frozenset({"id", "at"})


@pytest.mark.parametrize("output", [CountOut, NumbersOut, Schema, None])
def test_a_query_without_a_list_of_models_has_no_rows(output):
    assert _row_fields(output) is None


def hookless(**overrides):
    fields = {"label": "stock", "permissions": [], "setup": [], "widgets": [], "bell": [], "notices": []}
    return SimpleNamespace(**{**fields, **overrides})


def test_a_module_without_hooks_has_no_hook_errors():
    assert _hook_errors(hookless(), frozenset()) == []


def test_a_hook_that_is_not_a_list_is_one_e009_on_its_module():
    config = hookless(bell="low stock")

    [message] = _hook_errors(config, frozenset())

    assert (message.id, message.obj) == ("live.E009", config)
