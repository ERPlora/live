"""System check of the permissions an app declares (tag ``live``).

Every app of ours, platform and modules alike, declares its permissions as ``{permission: phrase}``: the phrase says in
business words what the permission lets a person do, the text a business reads beside each switch of a role (E027).
"""

from collections.abc import Mapping
from typing import Any

from django.core import checks
from django.utils.functional import Promise

from live.meta import all_live_app_configs

HINT = (
    "Declare permissions = {'<app>.<action>': _('<what it lets a person do>')}: each permission with the phrase, in "
    "business words, a business reads beside its switch."
)


@checks.register("live")
def check_permission_phrases(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """E027: the phrase of every permission of every app of ours."""
    errors: list[checks.CheckMessage] = []
    for config in all_live_app_configs():
        if not isinstance(config.permissions, Mapping):
            errors.append(_error(config, f"App {config.label!r} declares its permissions without the phrase of each."))
            continue
        errors += [
            _error(config, f"App {config.label!r} permission {permission!r} has no phrase.")
            for permission, phrase in config.permissions.items()
            if not _is_phrase(phrase)
        ]
    return errors


def _error(config: Any, message: str) -> checks.Error:
    return checks.Error(message, hint=HINT, obj=config, id="live.E027")


def _is_phrase(phrase: object) -> bool:
    return isinstance(phrase, (str, Promise)) and bool(str(phrase).strip())
