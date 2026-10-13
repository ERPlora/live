"""App metadata declared where Django already expects it: the AppConfig.

Every app of ours, platform and modules alike, extends ``LiveAppConfig`` and declares its
permissions (``<app>.<action>``) and the permissions each role gets (``"demo.*"`` grants every
``demo.`` permission). ``kind`` tells them apart (round 15, PLAN §20):

- ``"platform"`` (the default): always on, never turned on or off by a hub (``base``, ``control``…);
- ``"app"``: a module of ``apps/`` that a hub turns on and off. Only a module carries the metadata
  of the Hub's apps page, which shows icon and name (``verbose_name``) only (``icon``,
  ``category``, ``premium``), its ``requires`` (an acyclic graph of module labels) and its menu
  entries. ``live.checks`` enforces it.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import ClassVar, Literal

from django.apps import AppConfig, apps
from django.db import models
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


class LiveAppConfig(AppConfig):
    kind: ClassVar[Literal["platform", "app"]] = "platform"
    # Module metadata: an Iconify name with its set prefix, the apps page group, and whether
    # turning it on needs a right from the SaaS.
    icon: ClassVar[str] = ""
    category: ClassVar[Category | None] = None
    premium: ClassVar[bool] = False
    requires: ClassVar[list[str]] = []
    navigation: ClassVar[list[Nav]] = []
    permissions: ClassVar[list[str]] = []
    role_permissions: ClassVar[dict[str, list[str]]] = {}

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
