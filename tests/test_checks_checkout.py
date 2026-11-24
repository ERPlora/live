"""A module's steps of the charge of Sales (``checkout``): what Sales mounts between the amount and the tenders.

A step names the Vue component of its module that paints it and, if not everybody sees it, a permission of the
module; only a module declares one (E006), as a list of ``CheckoutStep`` (E009) with a permission of its own (E011),
a snake_case key unique in its list (E013) and the name of a component, never a path (E028).
"""

import dataclasses

import pytest
from django.apps import apps
from live.meta import CheckoutStep, LiveAppConfig, Widget
# known and run are the fixtures of the app metadata check: the stand-ins run through it as the installed apps.
from tests.test_checks import ids, known, module, platform, run


def step(key="tip", **overrides):
    return CheckoutStep(**{"key": key, "component": "TipStep", **overrides})


def test_a_module_adds_no_step_to_the_charge_by_default():
    assert LiveAppConfig.checkout == []


def test_a_checkout_step_names_its_component_and_needs_no_permission_by_default():
    declared = CheckoutStep(key="tip", component="TipStep")

    assert (declared.key, declared.component, declared.permission) == ("tip", "TipStep", None)


def test_a_checkout_step_is_immutable_like_the_other_hooks():
    with pytest.raises(dataclasses.FrozenInstanceError):
        step().component = "OtherStep"


def test_a_module_with_well_declared_checkout_steps_passes(run):
    tip = module("tip", checkout=[step(permission="tip.view"), step("round_up", component="RoundUp2")])

    assert run(platform(), tip) == []


def test_the_checkout_steps_may_be_a_tuple(run):
    assert run(module("tip", checkout=(step(),))) == []


def test_a_platform_app_declaring_a_checkout_step_is_e006(run):
    messages = run(platform(checkout=[step()]), module("tip"))

    assert ids(messages) == ["live.E006"]
    assert "base" in messages[0].msg
    assert "checkout" in messages[0].msg


@pytest.mark.parametrize(
    "value",
    [
        "TipStep",
        None,
        {"tip": "TipStep"},
        step(),
        [Widget(key="today", title="Today", component="TipStep")],
        [step(), {"key": "tip", "component": "TipStep"}],
    ],
)
def test_checkout_that_is_not_a_list_of_checkout_steps_is_e009(run, value):
    [message] = run(module("tip", checkout=value))

    assert message.id == "live.E009"
    assert "'tip'" in message.msg
    assert "checkout" in message.msg
    assert "CheckoutStep" in message.msg


@pytest.mark.parametrize("permission", ["tip.delete", "sale.view", "view"])
def test_a_checkout_step_whose_permission_is_not_one_of_its_module_is_e011(run, permission):
    [message] = run(module("tip", checkout=[step(permission=permission)]))

    assert message.id == "live.E011"
    assert "checkout" in message.msg
    assert repr(permission) in message.msg


def test_a_checkout_step_repeated_in_its_list_is_e013_once(run):
    [message] = run(module("tip", checkout=[step("tip"), step("tip"), step("tip")]))

    assert message.id == "live.E013"
    assert "'tip'" in message.msg


@pytest.mark.parametrize("key", ["", "Tip", "tip-step", "1tip", "tip.step", None])
def test_a_malformed_checkout_key_is_e013(run, key):
    [message] = run(module("tip", checkout=[step(key=key)]))

    assert message.id == "live.E013"
    assert repr(key) in message.msg


@pytest.mark.parametrize(
    "component",
    [None, "", "tipStep", "TipStep.vue", "components/TipStep", "../sale/Pay", "Tip Step", "Tip-Step", 3],
)
def test_a_checkout_step_that_names_no_component_is_e028(run, component):
    [message] = run(module("tip", checkout=[step(component=component)]))

    assert message.id == "live.E028"
    assert "'tip'" in message.msg
    assert repr(component) in message.msg
    assert "frontend/components/" in message.hint


def test_each_wrong_checkout_step_is_its_own_error(run):
    messages = run(module("tip", checkout=[step("a", component=""), step("b", permission="sale.view")]))

    assert sorted(ids(messages)) == ["live.E011", "live.E028"]


def test_the_testapp_adds_a_step_to_the_charge():
    """So that test_the_installed_apps_pass (test_checks.py) runs the checkout checks over a real declaration."""
    assert [type(item) for item in apps.get_app_config("testapp").checkout] == [CheckoutStep]
