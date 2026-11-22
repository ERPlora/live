"""System check of the menu a module declares (tag ``live``).

Every entry of a module's ``navigation`` names the permission that opens it, one its own module declares in
``permissions`` (E025): a person is shown only the entries she may open. Only a module has a menu (E006).
"""

from collections.abc import Collection
from typing import Any

from django.core import checks

from live.meta import all_live_app_configs

HINT = (
    "Declare Nav(..., permission='<app>.<action>') with a permission of the module's own permissions: the one a "
    "person needs to open that screen (a settings entry, the one that saves them)."
)


@checks.register("live")
def check_menu_permissions(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """E025: the permission of every entry of every module's menu."""
    return [
        checks.Error(f"Module {config.label!r} menu entry {nav.id!r} {problem}.", hint=HINT, obj=config, id="live.E025")
        for config in all_live_app_configs()
        if config.kind == "app"
        for nav in config.navigation
        if (problem := _permission_problem(nav.permission, config.permissions)) is not None
    ]


def _permission_problem(permission: str | None, declared: Collection[str]) -> str | None:
    if not permission:
        return "names no permission"
    if permission not in declared:
        return f"names the permission {permission!r}, which the module does not declare"
    return None
