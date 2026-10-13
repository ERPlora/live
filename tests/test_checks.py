"""System checks of the app metadata (tag ``live``): modules carry what the Hub's apps page needs.

Round 15 (PLAN §20): every app of ours extends ``LiveAppConfig``; ``kind = "app"`` marks a module
of ``apps/`` (turned on and off per hub), ``kind = "platform"`` an always-on app such as ``base``.
The checks run on ``manage.py check`` and when the server starts.
"""

from types import SimpleNamespace

import pytest
from django.core import checks
from django.core.checks.registry import registry
from live.checks import check_app_metadata
from live.meta import Category, LiveAppConfig, Nav


def module(label, **overrides):
    """A stand-in for a module's AppConfig with every metadata field filled."""
    fields = {
        "label": label,
        "kind": "app",
        "icon": "ion:cube-outline",
        "category": Category.ORGANIZATION,
        "premium": False,
        "requires": [],
        "navigation": [],
    }
    return SimpleNamespace(**{**fields, **overrides})


def platform(label="base", **overrides):
    """A stand-in for an always-on app: none of the module fields."""
    fields = {
        "label": label,
        "kind": "platform",
        "icon": "",
        "category": None,
        "premium": False,
        "requires": [],
        "navigation": [],
    }
    return SimpleNamespace(**{**fields, **overrides})


@pytest.fixture
def run(monkeypatch):
    """Run the check over the given stand-ins, as if they were the installed apps."""

    def run(*configs):
        monkeypatch.setattr("live.checks.all_live_app_configs", lambda: list(configs))
        return check_app_metadata(app_configs=None)

    return run


def ids(messages):
    return [message.id for message in messages]


# --- Clean ------------------------------------------------------------------------------------------


def test_a_platform_app_and_well_declared_modules_pass(run):
    customer = module("customer", premium=True)
    appointment = module("appointment", requires=["customer"], category=Category.PEOPLE)

    assert run(platform(), customer, appointment) == []


def test_a_platform_app_may_say_premium_false(run):
    assert run(platform(premium=False)) == []


def test_every_message_is_an_error_on_its_app(run):
    config = module("stock", icon="")

    [message] = run(config)

    assert isinstance(message, checks.Error)
    assert message.obj is config


# --- E001: kind -------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["plugin", "", None, "App"])
def test_unknown_kind_is_e001(run, kind):
    [message] = run(module("stock", kind=kind))

    assert message.id == "live.E001"
    assert repr(kind) in message.msg
    assert "stock" in message.msg


# --- E002: the icon of the apps page (it shows icon and name only) -------------------------------------


def test_module_without_icon_is_e002(run):
    [message] = run(module("stock", icon=""))

    assert message.id == "live.E002"
    assert "stock" in message.msg


def test_a_module_needs_no_description(run):
    """Ioan, 2026-10-13: the apps page shows icon and name only; there is no description field."""
    assert run(module("stock")) == []


def test_module_with_only_the_defaults_misses_icon_and_category(run):
    defaults = {
        field: getattr(LiveAppConfig, field)
        for field in (
            "icon",
            "category",
            "premium",
            "requires",
            "navigation",
        )
    }

    assert sorted(ids(run(SimpleNamespace(label="bare", kind="app", **defaults)))) == [
        "live.E002",
        "live.E003",
    ]


# --- E003: category ---------------------------------------------------------------------------------


@pytest.mark.parametrize("category", [None, "sales", "other", 3])
def test_module_category_must_be_a_category(run, category):
    [message] = run(module("stock", category=category))

    assert message.id == "live.E003"
    assert repr(category) in message.msg


@pytest.mark.parametrize("category", list(Category))
def test_every_category_is_accepted(run, category):
    assert run(module("stock", category=category)) == []


# --- E004: requires names modules -------------------------------------------------------------------


@pytest.mark.parametrize("required", ["ghost", "base", "auth"])
def test_requires_naming_anything_but_a_module_is_e004(run, required):
    [message] = run(platform(), module("stock", requires=[required]))

    assert message.id == "live.E004"
    assert "stock" in message.msg
    assert repr(required) in message.msg


def test_each_unknown_requirement_is_reported(run):
    assert ids(run(module("stock", requires=["ghost", "phantom"]))) == [
        "live.E004",
        "live.E004",
    ]


# --- E005: no cycles in requires --------------------------------------------------------------------


def test_cycle_in_requires_is_e005_and_names_the_cycle(run):
    a = module("a", requires=["b"])
    b = module("b", requires=["c"])
    c = module("c", requires=["a"])

    [message] = run(c, b, a)

    assert message.id == "live.E005"
    assert "a → b → c → a" in message.msg


def test_an_app_requiring_itself_is_a_cycle(run):
    [message] = run(module("a", requires=["a"]))

    assert message.id == "live.E005"
    assert "a → a" in message.msg


def test_each_cycle_is_reported_once(run):
    messages = run(
        module("a", requires=["b"]),
        module("b", requires=["a"]),
        module("c", requires=["d", "a"]),
        module("d", requires=["c"]),
    )

    assert sorted(message.msg for message in messages if message.id == "live.E005") == [
        "Cycle in requires: a → b → a.",
        "Cycle in requires: c → d → c.",
    ]
    assert ids(messages) == ["live.E005", "live.E005"]


def test_a_shared_requirement_is_not_a_cycle(run):
    base_module = module("customer")
    left = module("appointment", requires=["customer"])
    right = module("sale", requires=["customer"])
    top = module("report", requires=["appointment", "sale"])

    assert run(base_module, left, right, top) == []


# --- E006: platform apps declare no module fields ---------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("requires", ["stock"]),
        ("category", Category.SALES),
        ("premium", True),
        ("navigation", [Nav(id="base", label="Base", icon="ion:home", path="/")]),
    ],
)
def test_platform_app_declaring_a_module_field_is_e006(run, field, value):
    messages = run(platform(**{field: value}), module("stock"))

    assert ids(messages) == ["live.E006"]
    assert "base" in messages[0].msg
    assert field in messages[0].msg


def test_e006_names_every_module_field_in_one_error(run):
    [message] = run(platform(requires=["stock"], premium=True), module("stock"))

    assert message.id == "live.E006"
    assert "requires" in message.msg
    assert "premium" in message.msg


# --- Registration and the installed apps ------------------------------------------------------------


def test_the_check_is_registered_with_the_live_tag():
    assert check_app_metadata in registry.get_checks()
    assert "live" in registry.tags_available()
    assert check_app_metadata.tags == ("live",)


def test_the_installed_apps_pass():
    assert checks.run_checks(tags=["live"]) == []
