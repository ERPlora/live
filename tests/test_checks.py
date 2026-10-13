"""System checks of the app metadata (tag ``live``): modules carry what the Hub's apps page needs.

Round 15 (PLAN §20): every app of ours extends ``LiveAppConfig``; ``kind = "app"`` marks a module
of ``apps/`` (turned on and off per hub), ``kind = "platform"`` an always-on app such as ``base``.
Round 16 (PLAN §21) adds the public store's metadata of a module: ``summary`` and ``description``
(E007), ``verticals`` (E008) and ``listed``, which a platform app leaves at their defaults (E006).
The checks run on ``manage.py check`` and when the server starts.
"""

from types import SimpleNamespace

import pytest
from django.core import checks
from django.core.checks.registry import registry
from django.utils.translation import gettext_lazy
from live.checks import check_app_metadata
from live.meta import Category, LiveAppConfig, Nav


def module(label, **overrides):
    """A stand-in for a module's AppConfig with every metadata field filled."""
    fields = {
        "label": label,
        "kind": "app",
        "verbose_name": label.capitalize(),
        "icon": "ion:cube-outline",
        "category": Category.ORGANIZATION,
        "premium": False,
        "summary": "Products, categories, stock and movements.",
        "description": "Keep your products and their stock in one place.",
        "verticals": ["hair_salon", "restaurant"],
        "listed": True,
        "requires": [],
        "navigation": [],
    }
    return SimpleNamespace(**{**fields, **overrides})


def platform(label="base", **overrides):
    """A stand-in for an always-on app: none of the module fields."""
    fields = {
        "label": label,
        "kind": "platform",
        "verbose_name": label.capitalize(),
        "icon": "",
        "category": None,
        "premium": False,
        "summary": "",
        "description": "",
        "verticals": [],
        "listed": True,
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


def test_module_with_only_the_defaults_misses_icon_category_summary_and_description(run):
    """Round 16 replaces the round 15 test that a module needed no description: the Hub's apps page
    still shows icon and name only, but the public store shows the summary and the description."""
    defaults = {
        field: getattr(LiveAppConfig, field)
        for field in (
            "icon",
            "category",
            "premium",
            "summary",
            "description",
            "verticals",
            "listed",
            "requires",
            "navigation",
        )
    }

    assert sorted(ids(run(SimpleNamespace(label="bare", kind="app", verbose_name="Bare", **defaults)))) == [
        "live.E002",
        "live.E003",
        "live.E007",
        "live.E007",
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


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("summary", "Products, categories, stock and movements."),
        ("description", "Keep your products and their stock in one place."),
        ("verticals", ["restaurant"]),
        ("listed", False),
    ],
)
def test_platform_app_declaring_a_store_field_is_e006(run, field, value):
    messages = run(platform(**{field: value}), module("stock"))

    assert ids(messages) == ["live.E006"]
    assert "base" in messages[0].msg
    assert field in messages[0].msg


def test_a_platform_app_may_say_listed_true(run):
    """listed defaults to True: E006 compares with the default, not with truthiness."""
    assert run(platform(listed=True)) == []


def test_a_platform_app_may_leave_a_lazy_empty_summary(run):
    assert run(platform(summary=gettext_lazy(""), description=gettext_lazy(""))) == []


def test_e006_names_store_and_module_fields_in_one_error(run):
    [message] = run(platform(premium=True, listed=False, verticals=["restaurant"]))

    assert message.id == "live.E006"
    for field in ("premium", "listed", "verticals"):
        assert field in message.msg


# --- E007: summary, description and name of the public store (round 16) -----------------------------


@pytest.mark.parametrize("summary", ["", "   "])
def test_module_without_summary_is_e007(run, summary):
    [message] = run(module("stock", summary=summary))

    assert message.id == "live.E007"
    assert "stock" in message.msg
    assert "summary" in message.msg


def test_module_with_a_summary_of_121_characters_is_e007(run):
    [message] = run(module("stock", summary="x" * 121))

    assert message.id == "live.E007"
    assert "summary" in message.msg
    assert "120" in message.msg


def test_a_summary_of_120_characters_is_accepted(run):
    assert run(module("stock", summary="x" * 120)) == []


@pytest.mark.parametrize("summary", ["First line.\nSecond line.", "First line.\r\nSecond line."])
def test_module_with_a_summary_of_two_lines_is_e007(run, summary):
    [message] = run(module("stock", summary=summary))

    assert message.id == "live.E007"
    assert "one line" in message.msg


@pytest.mark.parametrize("description", ["", "  \n "])
def test_module_without_description_is_e007(run, description):
    [message] = run(module("stock", description=description))

    assert message.id == "live.E007"
    assert "stock" in message.msg
    assert "description" in message.msg


def test_module_with_a_name_of_81_characters_is_e007(run):
    [message] = run(module("stock", verbose_name="N" * 81))

    assert message.id == "live.E007"
    assert "verbose_name" in message.msg
    assert "80" in message.msg


def test_a_name_of_80_characters_is_accepted(run):
    assert run(module("stock", verbose_name="N" * 80)) == []


def test_lazy_translations_are_measured_by_their_english_text(run):
    assert run(
        module(
            "stock",
            verbose_name=gettext_lazy("Stock"),
            summary=gettext_lazy("x" * 120),
            description=gettext_lazy("A paragraph."),
        )
    ) == []
    [message] = run(module("stock", summary=gettext_lazy("x" * 121)))

    assert message.id == "live.E007"


def test_each_store_problem_of_a_module_is_its_own_e007(run):
    messages = run(module("stock", summary="", description="", verbose_name="N" * 81))

    assert ids(messages) == ["live.E007", "live.E007", "live.E007"]


# --- E008: verticals (round 16; PLAN §15.2) ---------------------------------------------------------


@pytest.mark.parametrize("verticals", [[], ["restaurant"], ["hair_salon", "retail2", "a"], ["x" * 50]])
def test_well_formed_verticals_are_accepted(run, verticals):
    assert run(module("stock", verticals=verticals)) == []


@pytest.mark.parametrize(
    "vertical",
    ["Hair", "hair-salon", "hair__salon", "_hair", "hair_", "2hair", "", "hair salon", "x" * 51, None, 3, ["hair"]],
)
def test_a_malformed_vertical_is_e008(run, vertical):
    [message] = run(module("stock", verticals=["restaurant", vertical]))

    assert message.id == "live.E008"
    assert "stock" in message.msg
    assert repr(vertical) in message.msg


def test_the_test_vertical_is_reserved(run):
    """hub_template_test is the template of the test suites (PLAN §15.2)."""
    [message] = run(module("stock", verticals=["test"]))

    assert message.id == "live.E008"
    assert "'test'" in message.msg
    assert "reserved" in message.msg


def test_a_repeated_vertical_is_e008_once(run):
    [message] = run(module("stock", verticals=["restaurant", "retail", "restaurant", "restaurant"]))

    assert message.id == "live.E008"
    assert "'restaurant'" in message.msg
    assert "more than once" in message.msg


@pytest.mark.parametrize("verticals", [["test", "test"], ["Hair", "Hair"], [["hair"], ["hair"]]])
def test_a_wrong_vertical_listed_twice_is_reported_once(run, verticals):
    assert ids(run(module("stock", verticals=verticals))) == ["live.E008"]


@pytest.mark.parametrize("verticals", ["restaurant", None, {"restaurant": True}])
def test_verticals_that_are_not_a_list_is_e008(run, verticals):
    [message] = run(module("stock", verticals=verticals))

    assert message.id == "live.E008"
    assert "list" in message.msg


# --- Registration and the installed apps ------------------------------------------------------------


def test_the_check_is_registered_with_the_live_tag():
    assert check_app_metadata in registry.get_checks()
    assert "live" in registry.tags_available()
    assert check_app_metadata.tags == ("live",)


def test_the_installed_apps_pass():
    assert checks.run_checks(tags=["live"]) == []
