"""``live.E025``: every entry of a module's menu names the permission that opens it.

A person sees only the menu entries she may open, so each entry of a module (``kind = "app"``) carries one of the
permissions its own module declares. ``Nav`` outside a module's ``navigation`` (the SaaS's panel) may leave it out.
"""

from types import SimpleNamespace

import pytest
from django.core import checks
from django.core.checks.registry import registry
from live.checks_nav import check_menu_permissions
from live.meta import Nav

from tests.startup_checks import checks_registered_at_startup


def entry(permission=None, entry_id="items"):
    return Nav(id=entry_id, label="Items", icon="ion:cube-outline", path=f"/stock/{entry_id}", permission=permission)


def app(*navigation, label="stock", kind="app", permissions=("stock.view", "stock.manage")):
    return SimpleNamespace(
        label=label, kind=kind, navigation=list(navigation), permissions=dict.fromkeys(permissions, "A phrase")
    )


@pytest.fixture
def run(monkeypatch):
    """Run the check over the given stand-ins, as if they were the installed apps."""

    def run(*configs):
        monkeypatch.setattr("live.checks_nav.all_live_app_configs", lambda: list(configs))
        return check_menu_permissions(app_configs=None)

    return run


def test_a_menu_entry_needs_no_permission_outside_a_module():
    assert Nav(id="home", label="Home", icon="ion:home", path="/").permission is None


def test_the_check_is_registered_with_the_live_tag():
    assert check_menu_permissions in registry.get_checks()
    assert check_menu_permissions.tags == ("live",)


def test_django_setup_registers_the_check_without_anyone_importing_it():
    """A fresh process, where no test imported ``live.checks_nav`` first: the live app's startup does."""
    assert "live.checks_nav.check_menu_permissions" in checks_registered_at_startup()


def test_every_entry_with_a_permission_of_its_own_module_passes(run):
    assert run(app(entry("stock.view"), entry("stock.manage", "settings"))) == []


def test_a_module_without_a_menu_passes(run):
    assert run(app()) == []


def test_a_platform_app_is_not_checked(run):
    """A platform app has no menu (E006 says so): this check does not repeat it."""
    assert run(app(entry(None), label="base", kind="platform", permissions=())) == []


@pytest.mark.parametrize("permission", [None, ""])
def test_an_entry_of_a_module_without_a_permission_is_e025(run, permission):
    config = app(entry("stock.view"), entry(permission, "settings"))

    [message] = run(config)

    assert (message.id, message.obj, message.level) == ("live.E025", config, checks.ERROR)
    assert message.msg == "Module 'stock' menu entry 'settings' names no permission."


@pytest.mark.parametrize("permission", ["stock.export", "base.view_home", "*"])
def test_an_entry_with_a_permission_its_module_does_not_declare_is_e025(run, permission):
    config = app(entry(permission))

    [message] = run(config)

    assert (message.id, message.obj) == ("live.E025", config)
    assert message.msg == (
        f"Module 'stock' menu entry 'items' names the permission {permission!r}, which the module does not declare."
    )


def test_each_wrong_entry_is_its_own_error(run):
    config = app(entry(None, "items"), entry("stock.export", "settings"), entry("stock.view", "movements"))

    assert [message.msg for message in run(config)] == [
        "Module 'stock' menu entry 'items' names no permission.",
        "Module 'stock' menu entry 'settings' names the permission 'stock.export', which the module does not declare.",
    ]
