"""App metadata declared where Django already expects it: the AppConfig.

Every app of ours, platform and modules alike, extends ``LiveAppConfig`` and declares its
permissions (``<app>.<action>``) and the permissions each role gets (``"demo.*"`` grants every
``demo.`` permission). ``kind`` tells them apart (round 15, PLAN §20):

- ``"platform"`` (the default): always on, never turned on or off by a hub (``base``, ``control``…);
- ``"app"``: a module of ``apps/`` that a hub turns on and off. Only a module carries the metadata
  of the Hub's apps page, which shows icon and name (``verbose_name``) only (``icon``,
  ``category``, ``premium``), its ``requires`` (an acyclic graph of module labels) and its menu
  entries. ``live.checks`` enforces it.

Round 16 (PLAN §21) adds the public store's metadata of a module (``summary``, ``description``,
``verticals``, ``listed``), which ``register_apps`` writes to ``shared.app``; the Hub's apps page
still shows icon and name only.

The PLAN-HUB round 2026-10-21 adds the Home's hooks of a module, the old manifest's ``setup``,
``widgets`` and ``bell`` without a manifest: its steps of «Finish setting up your business»
(``SetupStep``), its panels of the dashboard (``Widget``) and its counters of the bell
(``BellCounter``). Each names a query of the module's own ``queries.py``; the Hub's ``base`` runs them
as the person of the request and aggregates them (``base.setup.status``, ``base.widget.list``,
``base.bell.counters``).

The PLAN-HUB round 2026-10-23 adds the device's notices of a module (``DeviceNotice``): what it tells
the device with a system notice, the old shell's notices of a booking or a kitchen order without the
shell knowing the module. Base runs its query as the person of the request (``base.notice.list``),
fills in its texts, and the shell tells each new row once on the device.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from importlib import import_module
from typing import Any, ClassVar, Literal, get_args

from django.apps import AppConfig, apps
from django.db import models
from django.utils.module_loading import module_has_submodule
from django.utils.translation import gettext_lazy as _


class Category(models.TextChoices):
    """The closed set of groups of the Hub's apps page; each module belongs to one."""

    SALES = "sales", _("Sales, payments and tax")
    CATALOG = "catalog", _("Catalog and stock")
    PEOPLE = "people", _("Customers, schedule and team")
    RESTAURANT = "restaurant", _("Restaurant")
    ORGANIZATION = "organization", _("Organization and communication")


@dataclass(frozen=True)
class Nav:
    """A menu entry; ``label`` is usually a lazy translation and ``icon`` an Iconify name."""

    id: str
    label: str
    icon: str
    path: str


WidgetSize = Literal["sm", "md", "lg"]
#: How a panel renders without a component of its own: the old board's kinds.
WidgetKind = Literal["kpi", "stat", "sparkline", "bar-list", "timeline", "chart"]
WIDGET_SIZES: tuple[str, ...] = get_args(WidgetSize)
WIDGET_KINDS: tuple[str, ...] = get_args(WidgetKind)


@dataclass(frozen=True)
class SetupCheck:
    """One condition of ``SetupStep.configured_when`` on a field of the first row of the step's query.

    Exactly one of ``truthy`` (the field is truthy; ``False`` inverts it) and ``equals`` (the field
    equals this value); ``live.checks`` rejects neither and both (E016).
    """

    field: str
    truthy: bool | None = None
    equals: Any = None


@dataclass(frozen=True)
class SetupStep:
    """A step of «Finish setting up your business», answered by a query of the module itself.

    The step is done when every ``configured_when`` passes on the first row of ``operation`` run with
    ``params`` (no conditions: having a row is enough); no row, not done. ``required`` makes it
    functional, otherwise recommended (the legal level is base's to give). ``permission`` is the one
    needed to configure it; ``countries`` (ISO 3166-1 alpha-2, empty = all) limit it to hubs of those
    countries; ``order`` places it in the list (``None``: after the placed ones); ``refresh_on`` names
    the events that may change it. ``title`` and ``description`` are usually lazy translations.
    """

    key: str
    operation: str
    title: str
    route: str
    description: str = ""
    icon: str = ""
    params: Mapping[str, Any] = field(default_factory=dict)
    configured_when: Sequence[SetupCheck] = ()
    permission: str | None = None
    countries: Sequence[str] = ()
    order: int | None = None
    required: bool = True
    refresh_on: Sequence[str] = ()


@dataclass(frozen=True)
class Widget:
    """A panel of the Home's dashboard, which each person turns on, removes and reorders.

    It renders either by ``kind`` (one of ``WIDGET_KINDS``) with the data of ``operation`` run with
    ``params`` (``map``: prop → field of the result; ``options``: literal props), or by ``component``,
    the name of a Vue component of the module's ``frontend/components/`` (without ``.vue``), never
    both. ``verticals`` limit it to hubs of those verticals (empty = all) and ``default`` turns it on
    for a hub that has not chosen yet; ``size`` is its width on the board; ``refresh_on`` names the
    events that re-run its operation.
    """

    key: str
    title: str
    icon: str = ""
    category: str = ""
    size: WidgetSize = "md"
    permission: str | None = None
    verticals: Sequence[str] = ()
    default: bool = False
    refresh_on: Sequence[str] = ()
    kind: WidgetKind | None = None
    operation: str | None = None
    params: Mapping[str, Any] = field(default_factory=dict)
    map: Mapping[str, str] = field(default_factory=dict)
    options: Mapping[str, Any] = field(default_factory=dict)
    component: str | None = None


@dataclass(frozen=True)
class BellCounter:
    """A counter of the bell: the ``count`` of the first row of ``operation`` run with ``params``.

    Shown with ``label`` and ``icon`` while above zero, to whoever has ``permission``; ``route`` is
    where it leads and ``refresh_on`` names the events that may change it.
    """

    key: str
    operation: str
    route: str
    label: str
    icon: str = ""
    params: Mapping[str, Any] = field(default_factory=dict)
    permission: str | None = None
    refresh_on: Sequence[str] = ()


@dataclass(frozen=True)
class DeviceNotice:
    """A system notice of the device for each new row of ``operation``, the query of what happened.

    The query lists what happened, the newest first, each row with its ``id`` and the instant it
    happened, ``at``; only the rows that pass every ``when`` (``SetupCheck``) are this notice's. Its
    texts are ``str.format`` templates on the row's fields, usually lazy translations: the title is
    the first of ``title`` whose fields are all filled, the body joins with « · » the parts of ``body``
    whose fields are all filled, and ``route`` is the screen a tap opens. Shown to whoever has
    ``permission``; ``refresh_on`` names the events that may add a row.
    """

    key: str
    operation: str
    title: Sequence[str]
    route: str
    body: Sequence[str] = ()
    when: Sequence[SetupCheck] = ()
    params: Mapping[str, Any] = field(default_factory=dict)
    permission: str | None = None
    refresh_on: Sequence[str] = ()


class LiveAppConfig(AppConfig):
    kind: ClassVar[Literal["platform", "app"]] = "platform"
    # Module metadata, round 15: the Hub's apps page (icon and name) and the right from the SaaS.
    # icon is an Iconify name with its set prefix; premium = turning it on needs a right.
    icon: ClassVar[str] = ""
    category: ClassVar[Category | None] = None
    premium: ClassVar[bool] = False
    # Module metadata, round 16: the public store, registered in shared.app by register_apps.
    summary: ClassVar[str] = ""  # one line, at most 120 characters, gettext_lazy
    description: ClassVar[str] = ""  # one paragraph, gettext_lazy
    verticals: ClassVar[list[str]] = []  # vertical ids; also derives HUB_TEMPLATE_APPS
    listed: ClassVar[bool] = True  # False keeps the module out of the public store
    requires: ClassVar[list[str]] = []
    navigation: ClassVar[list[Nav]] = []
    permissions: ClassVar[list[str]] = []
    role_permissions: ClassVar[dict[str, list[str]]] = {}
    # Module metadata, PLAN-HUB round 2026-10-21: the Home's hooks, which base aggregates.
    setup: ClassVar[list[SetupStep]] = []
    widgets: ClassVar[list[Widget]] = []
    bell: ClassVar[list[BellCounter]] = []
    # Module metadata, PLAN-HUB round 2026-10-23: the device's notices, which base fills in.
    notices: ClassVar[list[DeviceNotice]] = []

    # An apps.py that imports LiveAppConfig holds two AppConfig subclasses, and Django then
    # silently falls back to a plain AppConfig. The base opts out of auto-detection and every
    # subclass opts in, unless it says otherwise.
    default = False

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        if "default" not in cls.__dict__:
            cls.default = True


def permissions_for_role(configs: Iterable[LiveAppConfig], role: str) -> frozenset[str]:
    """Union of the role's permissions across apps, with ``<app>.*`` expanded.

    A wildcard expands against the permissions declared by every given app; an entry that matches
    nothing (an unknown permission, a wildcard of an app not given, ``"*"``) is kept literal, which
    ``OperationContext.has`` still understands.
    """
    configs = list(configs)
    declared = {permission for config in configs for permission in config.permissions}
    granted: set[str] = set()
    for config in configs:
        for entry in config.role_permissions.get(role, []):
            expanded = {p for p in declared if p.startswith(entry[:-1])} if entry.endswith(".*") else set()
            granted |= expanded or {entry}
    return frozenset(granted)


def all_live_app_configs() -> list[LiveAppConfig]:
    """Every installed app of ours: platform apps and modules."""
    return [config for config in apps.get_app_configs() if isinstance(config, LiveAppConfig)]


def module_configs() -> list[LiveAppConfig]:
    """The installed modules: the apps of ``kind == "app"``, which a hub turns on and off."""
    return [config for config in all_live_app_configs() if config.kind == "app"]


def declared_events() -> frozenset[str]:
    """Every event an app of ours declares: the ``ALL`` list of its ``events.py``.

    An app without ``events.py``, or whose ``events.py`` has no ``ALL``, declares none.
    """
    names: set[str] = set()
    for config in all_live_app_configs():
        if module_has_submodule(config.module, "events"):
            names.update(getattr(import_module(f"{config.name}.events"), "ALL", ()))
    return frozenset(names)
