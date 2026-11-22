"""``live.E027``: every permission an app declares comes with its phrase.

An app declares its permissions as ``{permission: phrase}``: the phrase says in business words what the permission lets a
person do, the text a business reads beside each switch of a role. A list, or a permission without its phrase, is an
error that names the app and the permission.
"""

from types import SimpleNamespace

import pytest
from django.core import checks
from django.core.checks.registry import registry
from django.utils.translation import gettext_lazy
from live.checks_permissions import check_permission_phrases

from tests.startup_checks import checks_registered_at_startup


def app(permissions, label="stock", kind="app"):
    return SimpleNamespace(label=label, kind=kind, permissions=permissions)


@pytest.fixture
def run(monkeypatch):
    """Run the check over the given stand-ins, as if they were the installed apps."""

    def run(*configs):
        monkeypatch.setattr("live.checks_permissions.all_live_app_configs", lambda: list(configs))
        return check_permission_phrases(app_configs=None)

    return run


def test_the_check_is_registered_with_the_live_tag():
    assert check_permission_phrases in registry.get_checks()
    assert check_permission_phrases.tags == ("live",)


def test_django_setup_registers_the_check_without_anyone_importing_it():
    """A fresh process, where no test imported ``live.checks_permissions`` first: the live app's startup does."""
    assert "live.checks_permissions.check_permission_phrases" in checks_registered_at_startup()


def test_the_installed_apps_pass():
    assert check_permission_phrases(app_configs=None) == []


def test_every_permission_with_its_phrase_passes(run):
    phrases = {"stock.view": gettext_lazy("See the stock"), "stock.manage": "Move the stock"}

    assert run(app(phrases), app({}, label="base", kind="platform")) == []


@pytest.mark.parametrize("phrase", [None, "", "   ", gettext_lazy(""), 3, ["See the stock"]])
def test_a_permission_without_a_phrase_is_e027(run, phrase):
    config = app({"stock.view": "See the stock", "stock.manage": phrase})

    [message] = run(config)

    assert (message.id, message.obj, message.level) == ("live.E027", config, checks.ERROR)
    assert message.msg == "App 'stock' permission 'stock.manage' has no phrase."


def test_a_platform_app_is_checked_too(run):
    config = app({"base.view_home": ""}, label="base", kind="platform")

    [message] = run(config)

    assert (message.id, message.msg) == ("live.E027", "App 'base' permission 'base.view_home' has no phrase.")


@pytest.mark.parametrize("permissions", [["stock.view", "stock.manage"], ("stock.view",), frozenset({"stock.view"})])
def test_permissions_declared_without_phrases_are_e027(run, permissions):
    config = app(permissions)

    [message] = run(config)

    assert (message.id, message.obj) == ("live.E027", config)
    assert message.msg == "App 'stock' declares its permissions without the phrase of each."


def test_each_permission_without_its_phrase_is_its_own_error(run):
    config = app({"stock.view": "", "stock.export": "Export the stock", "stock.manage": None})

    assert [message.msg for message in run(config)] == [
        "App 'stock' permission 'stock.view' has no phrase.",
        "App 'stock' permission 'stock.manage' has no phrase.",
    ]
