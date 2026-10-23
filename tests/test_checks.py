"""System checks of the app metadata (tag ``live``): modules carry what the Hub's apps page needs.

Round 15 (PLAN §20): every app of ours extends ``LiveAppConfig``; ``kind = "app"`` marks a module
of ``apps/`` (turned on and off per hub), ``kind = "platform"`` an always-on app such as ``base``.
Round 16 (PLAN §21) adds the public store's metadata of a module: ``summary`` and ``description``
(E007), ``verticals`` (E008) and ``listed``, which a platform app leaves at their defaults (E006).
The PLAN-HUB round 2026-10-21 adds the Home's hooks of a module, ``setup``, ``widgets`` and ``bell``
(E006, E009–E016). The PLAN-HUB round 2026-10-23 adds the device's notices of a module, ``notices``
(E006, E009–E013 like the Home's hooks, and E018 for its texts). The checks run on ``manage.py check`` and
when the server starts.
"""

import datetime as dt

from types import SimpleNamespace

import pytest
from django.core import checks
from django.core.checks.registry import registry
from django.utils import translation
from django.utils.translation import gettext_lazy
from live.checks import check_app_metadata
from live.meta import BellCounter, Category, DeviceNotice, LiveAppConfig, Nav, SetupCheck, SetupStep, Widget
from live import operations
from live.operations import Operation
from ninja import Schema


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
        "permissions": [f"{label}.view", f"{label}.manage"],
        "setup": [],
        "widgets": [],
        "bell": [],
        "notices": [],
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
        "permissions": [],
        "setup": [],
        "widgets": [],
        "bell": [],
        "notices": [],
    }
    return SimpleNamespace(**{**fields, **overrides})


@pytest.fixture
def run(monkeypatch, known):
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
            "permissions",
            "setup",
            "widgets",
            "bell",
            "notices",
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


@pytest.mark.parametrize("field", ["setup", "widgets", "bell", "notices"])
def test_platform_app_declaring_a_home_hook_is_e006(run, field):
    """Only a module declares steps, panels, counters and notices; base's own steps live in base.setup.status."""
    hook = {"setup": step(), "widgets": widget(), "bell": counter(), "notices": notice()}[field]
    messages = run(platform(**{field: [hook]}), module("stock"))

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


# --- The Home's hooks (PLAN-HUB round 2026-10-21): setup, widgets and bell, E009–E016 -----------------


class ChangeOut(Schema):
    id: int
    at: dt.datetime
    kind: str
    name: str
    sku: str


class ChangesOut(Schema):
    rows: list[ChangeOut]


class CountOut(Schema):
    count: int


class UntimedOut(Schema):
    id: int
    name: str


class UntimedChangesOut(Schema):
    items: list[UntimedOut]


def query(name, kind="query", output=Schema):
    return Operation(
        name=name,
        kind=kind,
        permission="x.view",
        input=Schema,
        output=output,
        expose_api=False,
        ai=None,
        fn=lambda ctx, data: {},
    )


@pytest.fixture
def known(monkeypatch):
    """The operations and events the stand-ins name: stock's queries and command, and sale's query."""
    for op in (
        query("stock.catalog.status"),
        query("stock.item.count"),
        query("stock.item.archive", kind="command"),
        query("stock.item.changes", output=ChangesOut),
        query("stock.item.total", output=CountOut),
        query("stock.item.renamed", output=UntimedChangesOut),
        query("sale.sale.list"),
    ):
        monkeypatch.setitem(operations.registry, op.name, op)
    monkeypatch.setattr(
        "live.checks.declared_events", lambda: frozenset({"stock.item.created", "sale.sale.completed"})
    )


def step(key="catalog", **overrides):
    fields = {"key": key, "operation": "stock.catalog.status", "title": "Your catalog", "route": "/stock"}
    return SetupStep(**{**fields, **overrides})


def widget(key="today", **overrides):
    fields = {"key": key, "title": "Today", "kind": "kpi", "operation": "stock.item.count"}
    return Widget(**{**fields, **overrides})


def counter(key="low", **overrides):
    fields = {"key": key, "operation": "stock.item.count", "route": "/stock", "label": "Low stock"}
    return BellCounter(**{**fields, **overrides})


def notice(key="added", **overrides):
    fields = {
        "key": key,
        "operation": "stock.item.changes",
        "title": (gettext_lazy("New item · {name}"), gettext_lazy("New item")),
        "body": ("{sku}",),
        "route": "/stock?sku={sku}",
    }
    return DeviceNotice(**{**fields, **overrides})


#: One builder per hook, for the rules that the four share.
HOOKS = {"setup": step, "widgets": widget, "bell": counter, "notices": notice}


def test_a_module_with_well_declared_hooks_passes(run):
    stock = module(
        "stock",
        setup=[
            step(
                permission="stock.manage",
                refresh_on=["stock.item.created", "sale.sale.completed"],
                configured_when=[
                    SetupCheck(field="active", truthy=True),
                    SetupCheck(field="archived", truthy=False),
                    SetupCheck(field="state", equals="ready"),
                    SetupCheck(field="missing", equals=0),
                    SetupCheck(field="locked", equals=False),
                ],
            ),
            step("first_sale", required=False, countries=["ES"], order=20),
        ],
        widgets=[
            widget(size="lg", permission="stock.view", refresh_on=["stock.item.created"], map={"value": "total"}),
            widget("chart", kind=None, operation=None, component="StockChart", size="sm"),
            widget("trend", kind=None, component="StockTrend"),
        ],
        bell=[counter(permission="stock.view", refresh_on=("sale.sale.completed",))],
        notices=[
            notice(
                permission="stock.view",
                refresh_on=["stock.item.created"],
                when=[SetupCheck(field="kind", equals="added")],
                body=["{sku}", gettext_lazy("{name} at {at:%H:%M}"), "Plain text"],
                route="/stock?day={at:%Y-%m-%d}&sku={sku!s}",
            ),
            notice("removed", title=["Item removed"], route="/stock"),
        ],
    )

    assert run(platform(), stock) == []


@pytest.mark.parametrize("kind", ["kpi", "stat", "sparkline", "bar-list", "timeline", "chart"])
def test_every_widget_kind_is_accepted(run, kind):
    assert run(module("stock", widgets=[widget(kind=kind)])) == []


@pytest.mark.parametrize("size", ["sm", "md", "lg"])
def test_every_widget_size_is_accepted(run, size):
    assert run(module("stock", widgets=[widget(size=size)])) == []


def test_the_hooks_may_be_tuples(run):
    assert run(module("stock", setup=(step(),), widgets=(widget(),), bell=(counter(),), notices=(notice(),))) == []


# E009: each hook is a list of its own dataclass.


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("setup", "catalog"),
        ("setup", None),
        ("widgets", {"today": "kpi"}),
        ("setup", [widget()]),
        ("widgets", [step()]),
        ("bell", [widget()]),
        ("bell", [counter(), {"key": "low"}]),
        ("notices", [counter()]),
        ("notices", notice()),
    ],
)
def test_a_hook_that_is_not_a_list_of_its_dataclass_is_e009(run, field, value):
    [message] = run(module("stock", **{field: value}))

    assert message.id == "live.E009"
    assert "stock" in message.msg
    assert field in message.msg


def test_a_single_dataclass_instead_of_a_list_is_e009(run):
    [message] = run(module("stock", setup=step()))

    assert message.id == "live.E009"


# E010: operation is a query of the module itself.


@pytest.mark.parametrize("field", HOOKS)
@pytest.mark.parametrize(
    "operation",
    [
        "stock.catalog.ghost",  # no such operation
        "stock.item.archive",  # a command
        "sale.sale.list",  # a query of another app
    ],
)
def test_a_hook_whose_operation_is_not_a_query_of_its_app_is_e010(run, field, operation):
    [message] = run(module("stock", **{field: [HOOKS[field](operation=operation)]}))

    assert message.id == "live.E010"
    assert "stock" in message.msg
    assert field in message.msg
    assert repr(operation) in message.msg


@pytest.mark.parametrize("field", ["setup", "bell", "notices"])
@pytest.mark.parametrize("operation", ["", None, 3])
def test_a_step_or_counter_without_operation_is_e010(run, field, operation):
    """A widget may go without one when it renders a component; a kind without it is E014."""
    [message] = run(module("stock", **{field: [HOOKS[field](operation=operation)]}))

    assert message.id == "live.E010"
    assert repr(operation) in message.msg


def test_a_component_widget_with_an_operation_has_it_checked(run):
    [message] = run(module("stock", widgets=[widget(kind=None, component="StockChart", operation="sale.sale.list")]))

    assert message.id == "live.E010"


def test_an_operation_of_another_app_is_e010_even_if_the_prefix_only_starts_alike(run, monkeypatch):
    monkeypatch.setitem(operations.registry, "stockx.item.count", query("stockx.item.count"))

    [message] = run(module("stock", bell=[counter(operation="stockx.item.count")]))

    assert message.id == "live.E010"


def test_each_hook_with_a_wrong_operation_is_its_own_e010(run):
    messages = run(
        module(
            "stock",
            setup=[step(operation="stock.item.archive")],
            widgets=[widget(operation="sale.sale.list")],
            bell=[counter("a", operation="x"), counter("b", operation="stock.catalog.ghost")],
        )
    )

    assert ids(messages) == ["live.E010"] * 4


# E011: permission is one of the app's permissions.


@pytest.mark.parametrize("field", HOOKS)
@pytest.mark.parametrize("permission", ["stock.delete", "sale.view", "view"])
def test_a_hook_whose_permission_is_not_one_of_its_app_is_e011(run, field, permission):
    [message] = run(module("stock", **{field: [HOOKS[field](permission=permission)]}))

    assert message.id == "live.E011"
    assert "stock" in message.msg
    assert repr(permission) in message.msg


@pytest.mark.parametrize("field", HOOKS)
def test_a_hook_may_need_no_permission(run, field):
    assert run(module("stock", **{field: [HOOKS[field](permission=None)]})) == []


# E012: refresh_on names declared events only.


@pytest.mark.parametrize("field", HOOKS)
def test_a_hook_refreshed_on_an_undeclared_event_is_e012(run, field):
    [message] = run(module("stock", **{field: [HOOKS[field](refresh_on=["stock.item.vanished"])]}))

    assert message.id == "live.E012"
    assert "stock" in message.msg
    assert "'stock.item.vanished'" in message.msg


def test_each_undeclared_event_is_its_own_e012(run):
    messages = run(module("stock", setup=[step(refresh_on=["a.b.c", "stock.item.created", "d.e.f"])]))

    assert ids(messages) == ["live.E012", "live.E012"]
    assert ["'a.b.c'" in messages[0].msg, "'d.e.f'" in messages[1].msg] == [True, True]


@pytest.mark.parametrize("event", [["stock.item.created"], None, 3])
def test_an_event_that_is_not_a_name_is_e012(run, event):
    [message] = run(module("stock", bell=[counter(refresh_on=["stock.item.created", event])]))

    assert message.id == "live.E012"
    assert repr(event) in message.msg


@pytest.mark.parametrize("refresh_on", ["stock.item.created", None, {"stock.item.created": True}])
def test_refresh_on_that_is_not_a_list_is_one_e012(run, refresh_on):
    [message] = run(module("stock", widgets=[widget(refresh_on=refresh_on)]))

    assert message.id == "live.E012"
    assert "list" in message.msg


# E013: key, a snake_case name unique per app and hook.


@pytest.mark.parametrize("field", HOOKS)
def test_a_key_repeated_in_one_hook_is_e013_once(run, field):
    build = HOOKS[field]

    [message] = run(module("stock", **{field: [build("low"), build("high"), build("low"), build("low")]}))

    assert message.id == "live.E013"
    assert "'low'" in message.msg


def test_the_same_key_in_two_hooks_is_fine(run):
    assert run(module("stock", setup=[step("low")], widgets=[widget("low")], bell=[counter("low")])) == []


@pytest.mark.parametrize("key", ["", "Low", "low-stock", "1low", "low stock", "low.stock", None])
def test_a_malformed_key_is_e013(run, key):
    [message] = run(module("stock", bell=[counter(key=key)]))

    assert message.id == "live.E013"
    assert repr(key) in message.msg


# E014: a widget renders by kind (with its operation) or by component, never both.


@pytest.mark.parametrize(
    "overrides",
    [
        {"kind": "kpi", "component": "StockChart"},  # both
        {"kind": None, "component": None},  # neither
        {"kind": None, "component": ""},  # neither
        {"kind": "pie"},  # unknown kind
        {"kind": "Kpi"},  # unknown kind
        {"kind": "bar_list"},  # unknown kind
        {"kind": "kpi", "operation": None},  # kind without operation
        {"kind": "kpi", "operation": ""},  # kind without operation
    ],
)
def test_a_widget_that_does_not_render_one_way_is_e014(run, overrides):
    [message] = run(module("stock", widgets=[widget(**overrides)]))

    assert message.id == "live.E014"
    assert "'today'" in message.msg


# E015: size.


@pytest.mark.parametrize("size", ["xl", "", None, "MD", "medium"])
def test_a_widget_size_other_than_sm_md_lg_is_e015(run, size):
    [message] = run(module("stock", widgets=[widget(size=size)]))

    assert message.id == "live.E015"
    assert repr(size) in message.msg


# E016: configured_when, a list of SetupCheck with exactly one of truthy and equals.


@pytest.mark.parametrize(
    "configured_when",
    [
        [SetupCheck(field="active")],  # neither
        [SetupCheck(field="active", truthy=True, equals="x")],  # both
        [SetupCheck(field="", truthy=True)],  # no field
        [SetupCheck(field=None, truthy=True)],  # no field
        [{"field": "active", "truthy": True}],  # not a SetupCheck
        SetupCheck(field="active", truthy=True),  # not a list
        "active",  # not a list
    ],
)
def test_a_malformed_configured_when_is_e016(run, configured_when):
    [message] = run(module("stock", setup=[step(configured_when=configured_when)]))

    assert message.id == "live.E016"
    assert "'catalog'" in message.msg


def test_each_malformed_condition_is_its_own_e016(run):
    messages = run(
        module("stock", setup=[step(configured_when=[SetupCheck(field="a"), SetupCheck(field="b", truthy=True), SetupCheck(field="c")])])
    )

    assert ids(messages) == ["live.E016", "live.E016"]


# --- Registration and the installed apps ------------------------------------------------------------


def test_the_check_is_registered_with_the_live_tag():
    assert check_app_metadata in registry.get_checks()
    assert "live" in registry.tags_available()
    assert check_app_metadata.tags == ("live",)


def test_the_installed_apps_pass():
    assert checks.run_checks(tags=["live"]) == []


# E018: a notice's texts are templates on the fields of its query's rows, which say what happened and when.


@pytest.mark.parametrize(
    ("overrides", "problem"),
    [
        ({"title": ()}, "title"),  # nothing to say
        ({"title": "New item"}, "title"),  # a bare text, not a list of templates
        ({"title": ["New item", 3]}, "title"),  # not a text
        ({"body": "{sku}"}, "body"),  # a bare text, not a list of parts
        ({"body": [None]}, "body"),
        ({"route": "stock"}, "route"),  # not a screen of the hub
        ({"route": "//evil.example/stock"}, "route"),  # another address
        ({"route": "https://evil.example/stock"}, "route"),
        ({"route": None}, "route"),
        ({"title": ["New item · {colour}"]}, "'colour'"),  # not a field of the row
        ({"body": ["{name.upper}"]}, "'name.upper'"),  # an attribute of a field: only fields
        ({"route": "/stock?sku={sku[0]}"}, "'sku[0]'"),
        ({"title": ["New item · {}"]}, "positional"),  # a field without a name
        ({"title": ["New item · {0}"]}, "positional"),
        ({"title": ["New item · {name"]}, "template"),  # a broken template
        ({"body": ["{name:{sku}}"]}, "template"),  # a nested field
        ({"when": [SetupCheck(field="colour", equals="red")]}, "'colour'"),  # a condition on no field
        ({"when": [SetupCheck(field="kind")]}, "when"),  # a condition with nothing to compare
        ({"when": [{"field": "kind", "equals": "added"}]}, "when"),  # not a SetupCheck
        ({"when": SetupCheck(field="kind", equals="added")}, "when"),  # not a list
    ],
)
def test_a_notice_whose_texts_do_not_fit_its_rows_is_e018(run, overrides, problem):
    [message] = run(module("stock", notices=[notice(**overrides)]))

    assert message.id == "live.E018"
    assert "'added'" in message.msg
    assert problem in message.msg


def test_the_texts_are_read_in_english_whatever_the_language(run):
    """A lazy translation is measured by its source: the fields a translator writes are the .po's business."""
    with translation.override("es"):
        assert run(module("stock", notices=[notice()])) == []


@pytest.mark.parametrize(
    ("operation", "problem"),
    [
        ("stock.item.total", "rows"),  # one object, not a list of what happened
        ("stock.item.renamed", "'at'"),  # rows that do not say when
    ],
)
def test_a_notice_whose_query_does_not_list_what_happened_and_when_is_e018(run, operation, problem):
    [message] = run(module("stock", notices=[notice(operation=operation, title=["New item"], body=(), route="/stock")]))

    assert message.id == "live.E018"
    assert repr(operation) in message.msg
    assert problem in message.msg


def test_a_notice_with_a_wrong_operation_is_only_e010(run):
    """Its texts cannot be measured against a query that is not there: one error, the operation's."""
    [message] = run(module("stock", notices=[notice(operation="stock.item.ghost")]))

    assert message.id == "live.E010"


def test_each_misfit_text_of_a_notice_is_its_own_e018(run):
    messages = run(module("stock", notices=[notice(title=["{colour}"], body=["{size}"], route="/stock/{shape}")]))

    assert ids(messages) == ["live.E018"] * 3
