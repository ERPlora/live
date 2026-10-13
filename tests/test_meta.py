"""App metadata: navigation, permissions per role, module metadata and discovery of live apps."""

import dataclasses
from types import SimpleNamespace

import pytest
from django.apps import apps
from django.utils import translation
from live.meta import Category, LiveAppConfig, Nav, all_live_app_configs, module_configs, permissions_for_role

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


def test_live_app_config_has_no_description():
    """Ioan, 2026-10-13: the Hub's apps page shows icon and name (``verbose_name``) only."""
    assert not hasattr(LiveAppConfig, "description")


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
