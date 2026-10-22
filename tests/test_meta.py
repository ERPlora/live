"""App metadata: navigation, permissions per role, module metadata and discovery of live apps."""

import dataclasses
from importlib import import_module
from types import SimpleNamespace

import pytest
from django.apps import apps
from django.utils import translation
from live.meta import (
    WIDGET_KINDS,
    WIDGET_SIZES,
    BellCounter,
    Category,
    LiveAppConfig,
    Nav,
    SetupCheck,
    SetupStep,
    Widget,
    all_live_app_configs,
    declared_events,
    module_configs,
    permissions_for_role,
)

CATEGORIES_EN = [
    ("sales", "Sales, payments and tax"),
    ("catalog", "Catalog and stock"),
    ("people", "Customers, schedule and team"),
    ("restaurant", "Restaurant"),
    ("organization", "Organization and communication"),
]
CATEGORIES_ES = [
    "Venta, cobro y fiscalidad",
    "Catálogo y existencias",
    "Clientes, agenda y equipo",
    "Restaurante",
    "Organización y comunicación",
]


def make_config(permissions, role_permissions):
    return SimpleNamespace(permissions=permissions, role_permissions=role_permissions)


def test_role_wildcard_expands_to_the_declared_permissions():
    config = make_config(["demo.view", "demo.manage"], {"admin": ["demo.*"]})

    assert permissions_for_role([config], "admin") == frozenset({"demo.view", "demo.manage"})


def test_role_permissions_are_the_union_across_apps():
    demo = make_config(["demo.view", "demo.manage"], {"employee": ["demo.view"]})
    stock = make_config(["stock.view", "stock.manage"], {"employee": ["stock.*"]})

    assert permissions_for_role([demo, stock], "employee") == frozenset(
        {"demo.view", "stock.view", "stock.manage"}
    )


def test_wildcard_expands_against_permissions_of_every_app():
    demo = make_config(["demo.view"], {"manager": ["stock.*"]})
    stock = make_config(["stock.view", "stock.manage"], {})

    assert permissions_for_role([demo, stock], "manager") == frozenset({"stock.view", "stock.manage"})


def test_unknown_entries_are_kept_literal():
    config = make_config(["demo.view"], {"admin": ["other.view", "ghost.*", "*"]})

    assert permissions_for_role([config], "admin") == frozenset({"other.view", "ghost.*", "*"})


def test_unknown_role_has_no_permissions():
    config = make_config(["demo.view"], {"admin": ["demo.*"]})

    assert permissions_for_role([config], "guest") == frozenset()


def test_wildcard_does_not_match_another_app_with_the_same_prefix():
    config = make_config(["demo.view", "demox.view"], {"admin": ["demo.*"]})

    assert permissions_for_role([config], "admin") == frozenset({"demo.view"})


def test_live_app_config_has_empty_metadata_by_default():
    assert LiveAppConfig.requires == []
    assert LiveAppConfig.navigation == []
    assert LiveAppConfig.permissions == []
    assert LiveAppConfig.role_permissions == {}


def test_live_app_config_is_a_platform_app_without_module_metadata_by_default():
    assert LiveAppConfig.kind == "platform"
    assert LiveAppConfig.icon == ""
    assert LiveAppConfig.category is None
    assert LiveAppConfig.premium is False


def test_testapp_config_is_detected_as_a_live_app_config_although_apps_py_imports_the_base():
    config = apps.get_app_config("testapp")

    assert isinstance(config, LiveAppConfig)
    assert type(config).__name__ == "TestAppConfig"
    assert config.permissions == ["testapp.view", "testapp.manage"]
    assert config.role_permissions == {"admin": ["testapp.*"]}


def test_testapp_is_a_module_with_its_metadata():
    config = apps.get_app_config("testapp")

    assert (config.kind, config.icon, config.category, config.premium) == (
        "app",
        "ion:cube-outline",
        Category.ORGANIZATION,
        False,
    )


def test_live_app_config_has_empty_store_metadata_by_default():
    """Round 16 (PLAN §21): the public store's fields, empty for a platform app.

    It replaces the round 15 test that the class had no ``description``: round 16 brings the
    description back for the public store; the Hub's apps page still shows icon and name only.
    """
    assert LiveAppConfig.summary == ""
    assert LiveAppConfig.description == ""
    assert LiveAppConfig.verticals == []
    assert LiveAppConfig.listed is True


def test_module_configs_keeps_only_the_apps_of_kind_app(monkeypatch):
    platform = SimpleNamespace(label="base", kind="platform")
    module = SimpleNamespace(label="stock", kind="app")
    monkeypatch.setattr("live.meta.all_live_app_configs", lambda: [platform, module])

    assert module_configs() == [module]


def test_module_configs_of_the_installed_apps_is_the_testapp():
    assert module_configs() == [apps.get_app_config("testapp")]


def test_categories_are_the_five_groups_of_the_apps_page():
    assert [(category.value, str(category.label)) for category in Category] == CATEGORIES_EN
    assert Category("people") is Category.PEOPLE


def test_category_labels_are_translated_to_spanish():
    with translation.override("es"):
        assert [str(category.label) for category in Category] == CATEGORIES_ES


def test_all_live_app_configs_finds_live_apps_only():
    configs = all_live_app_configs()

    assert apps.get_app_config("testapp") in configs
    assert apps.get_app_config("auth") not in configs
    assert apps.get_app_config("live") not in configs
    assert all(isinstance(config, LiveAppConfig) for config in configs)


def test_role_permissions_of_the_installed_apps():
    assert permissions_for_role(all_live_app_configs(), "admin") == frozenset(
        {"testapp.view", "testapp.manage"}
    )


def test_nav_is_an_immutable_menu_entry():
    nav = Nav(id="demo", label="Demo", icon="ion:cube-outline", path="/demo")

    assert (nav.id, nav.label, nav.icon, nav.path) == ("demo", "Demo", "ion:cube-outline", "/demo")
    with pytest.raises(dataclasses.FrozenInstanceError):
        nav.path = "/other"


# --- The Home's hooks (PLAN-HUB round 2026-10-21): setup, widgets and bell --------------------------


def test_live_app_config_declares_no_home_hooks_by_default():
    """A module's steps of «Finish setting up your business», panels of the dashboard and counters of
    the bell; empty unless the module declares them (a platform app never does: live.E006)."""
    assert LiveAppConfig.setup == []
    assert LiveAppConfig.widgets == []
    assert LiveAppConfig.bell == []


def test_a_setup_step_needs_key_operation_title_and_route():
    step = SetupStep(key="catalog", operation="stock.catalog.status", title="Your catalog", route="/stock")

    assert (step.key, step.operation, step.title, step.route) == (
        "catalog",
        "stock.catalog.status",
        "Your catalog",
        "/stock",
    )
    assert (step.description, step.icon, step.permission, step.order) == ("", "", None, None)
    assert (dict(step.params), tuple(step.configured_when), tuple(step.countries), tuple(step.refresh_on)) == (
        {},
        (),
        (),
        (),
    )


def test_a_setup_step_is_required_by_default():
    """As in the old manifest: required = functional; required=False = recommended."""
    assert SetupStep(key="catalog", operation="stock.catalog.status", title="Your catalog", route="/stock").required


def test_a_setup_check_is_one_condition_on_a_field_of_the_first_row():
    assert (SetupCheck(field="active").truthy, SetupCheck(field="active").equals) == (None, None)
    assert SetupCheck(field="active", truthy=False).truthy is False
    assert SetupCheck(field="state", equals="ready").equals == "ready"


def test_a_widget_defaults_to_a_medium_panel_off_by_default():
    widget = Widget(key="today", title="Today", kind="kpi", operation="stock.item.count")

    assert (widget.size, widget.default, widget.component, widget.icon, widget.category, widget.permission) == (
        "md",
        False,
        None,
        "",
        "",
        None,
    )
    assert (tuple(widget.verticals), tuple(widget.refresh_on), dict(widget.params), dict(widget.map)) == (
        (),
        (),
        {},
        {},
    )
    assert dict(widget.options) == {}


def test_a_component_widget_needs_no_kind_nor_operation():
    widget = Widget(key="chart", title="Sales", component="SalesChart")

    assert (widget.kind, widget.operation, widget.component) == (None, None, "SalesChart")


def test_a_bell_counter_needs_key_operation_route_and_label():
    counter = BellCounter(key="to_confirm", operation="stock.item.count", route="/stock", label="To confirm")

    assert (counter.key, counter.operation, counter.route, counter.label) == (
        "to_confirm",
        "stock.item.count",
        "/stock",
        "To confirm",
    )
    assert (counter.icon, counter.permission, tuple(counter.refresh_on), dict(counter.params)) == ("", None, (), {})


@pytest.mark.parametrize(
    "hook",
    [
        SetupCheck(field="active", truthy=True),
        SetupStep(key="catalog", operation="stock.catalog.status", title="Your catalog", route="/stock"),
        Widget(key="today", title="Today", kind="kpi", operation="stock.item.count"),
        BellCounter(key="to_confirm", operation="stock.item.count", route="/stock", label="To confirm"),
    ],
)
def test_the_hooks_are_immutable_like_nav(hook):
    with pytest.raises(dataclasses.FrozenInstanceError):
        hook.key = "other"


def test_widget_sizes_and_kinds_are_those_of_the_old_board():
    assert WIDGET_SIZES == ("sm", "md", "lg")
    assert WIDGET_KINDS == ("kpi", "stat", "sparkline", "bar-list", "timeline", "chart")


def test_testapp_declares_one_of_each_hook():
    """So that test_the_installed_apps_pass (test_checks.py) runs the checks over real declarations."""
    config = apps.get_app_config("testapp")

    assert [type(item) for item in (*config.setup, *config.widgets, *config.bell)] == [SetupStep, Widget, BellCounter]


def test_declared_events_is_the_all_list_of_every_events_module():
    assert declared_events() == frozenset({"testapp.thing.created"})


def test_declared_events_skips_apps_without_events_module_and_events_modules_without_all(monkeypatch):
    without_module = SimpleNamespace(name="tests.fakeapp", module=import_module("tests.fakeapp"))
    without_all = SimpleNamespace(name="tests.bareevents", module=import_module("tests.bareevents"))
    testapp = apps.get_app_config("testapp")
    monkeypatch.setattr("live.meta.all_live_app_configs", lambda: [without_module, without_all, testapp])

    assert declared_events() == frozenset({"testapp.thing.created"})
