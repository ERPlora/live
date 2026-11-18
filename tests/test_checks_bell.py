"""``live.E024``: what a counter of a module's bell says of itself.

Each counter may say how grave it is (``severity``: danger, warning or info), the heading it shows (``title``), one
sentence with the consequence (``body``) and the label of its button (``action_label``), each a text or a lazy
translation, and which field of its query's answer holds its deadline (``due``). Each one is optional.
"""

from types import SimpleNamespace

import pytest
from django.core.checks.registry import registry
from django.utils.translation import gettext_lazy, ngettext_lazy
from live import operations
from live.checks_bell import check_bell_counters
from live.meta import BellCounter
from live.operations import Operation
from ninja import Schema
from pydantic import Field

from tests.startup_checks import checks_registered_at_startup


class CountOut(Schema):
    count: int
    earliest: str | None = Field(default=None)


class RowOut(Schema):
    count: int
    oldest: str | None = Field(default=None)


class RowsOut(Schema):
    rows: list[RowOut]


def query(name, output):
    return Operation(
        name=name,
        kind="query",
        permission="x.view",
        input=Schema,
        output=output,
        expose_api=False,
        ai=None,
        fn=lambda ctx, data: {},
    )


def counter(**overrides):
    fields = {"key": "low", "operation": "stock.item.count", "route": "/stock", "label": "Low stock"}
    return BellCounter(**{**fields, **overrides})


def module(*bell, kind="app"):
    return SimpleNamespace(label="stock", kind=kind, bell=list(bell))


@pytest.fixture
def run(monkeypatch):
    """Run the check over the given stand-ins, as if they were the installed apps."""
    monkeypatch.setitem(operations.registry, "stock.item.count", query("stock.item.count", CountOut))
    monkeypatch.setitem(operations.registry, "stock.item.waiting", query("stock.item.waiting", RowsOut))

    def run(*configs):
        monkeypatch.setattr("live.checks_bell.all_live_app_configs", lambda: list(configs))
        return check_bell_counters(app_configs=None)

    return run


def test_the_check_is_registered_with_the_live_tag():
    assert check_bell_counters in registry.get_checks()
    assert check_bell_counters.tags == ("live",)


def test_django_setup_registers_the_check_without_anyone_importing_it():
    """A fresh process, where no test imported ``live.checks_bell`` first: the live app's startup does."""
    assert "live.checks_bell.check_bell_counters" in checks_registered_at_startup()


def test_a_counter_that_declares_none_of_its_words_passes(run):
    assert run(module(counter())) == []


def test_a_counter_that_declares_all_of_them_passes(run):
    full = counter(
        severity="danger",
        title=ngettext_lazy("%(count)d item low", "%(count)d items low", "count"),
        body=gettext_lazy("Sales may stop."),
        action_label="Order more",
        due="earliest",
    )

    assert run(module(full)) == []


@pytest.mark.parametrize("severity", ["warning", "info"])
def test_every_severity_passes(run, severity):
    assert run(module(counter(severity=severity))) == []


@pytest.mark.parametrize("severity", ["error", "urgent", "", "Danger"])
def test_an_unknown_severity_is_e024(run, severity):
    [message] = run(module(counter(severity=severity)))

    assert message.id == "live.E024"
    assert repr(severity) in message.msg
    assert "'low'" in message.msg


@pytest.mark.parametrize("name", ["title", "body", "action_label"])
def test_a_word_that_is_not_a_text_is_e024(run, name):
    [message] = run(module(counter(**{name: ["Order more"]})))

    assert message.id == "live.E024"
    assert name in message.msg


def test_a_due_must_name_a_field_of_the_answer(run):
    [message] = run(module(counter(due="soonest")))

    assert message.id == "live.E024"
    assert "'soonest'" in message.msg
    assert "stock.item.count" in message.msg


def test_a_due_of_a_list_answer_names_a_field_of_its_rows(run):
    assert run(module(counter(operation="stock.item.waiting", due="oldest"))) == []
    [message] = run(module(counter(operation="stock.item.waiting", due="rows")))

    assert message.id == "live.E024"


@pytest.mark.parametrize("due", ["", "the start", 3])
def test_a_due_that_is_not_a_field_name_is_e024(run, due):
    [message] = run(module(counter(due=due)))

    assert message.id == "live.E024"


def test_a_due_on_an_unknown_operation_is_left_to_the_operation_check(run):
    """E010 already says the operation is not declared."""
    assert run(module(counter(operation="stock.item.gone", due="earliest"))) == []


def test_every_problem_of_a_counter_is_told(run):
    messages = run(module(counter(severity="error", title=1, due="soonest")))

    assert [message.id for message in messages] == ["live.E024"] * 3


def test_a_platform_app_and_a_misshapen_bell_are_left_to_the_metadata_check(run):
    """Only a module has a bell (E007), and a bell that is not a list of BellCounter is E009."""
    assert run(module(counter(severity="error"), kind="platform")) == []
    assert run(SimpleNamespace(label="stock", kind="app", bell="low")) == []
    assert run(module(SimpleNamespace(key="low", severity="error"))) == []
