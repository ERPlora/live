"""System check of the fields only whoever holds a permission sees (tag ``live``, ``live.sensitive``).

A field marked ``json_schema_extra={"requires": "<permission>"}``, in any operation's input or answer and at any depth,
names a permission an app declares; in an answer it also admits null, what whoever lacks the permission gets (E026).
"""

from collections.abc import Iterator
from typing import Any

from django.core import checks
from pydantic import TypeAdapter, ValidationError

from live.meta import declared_permissions
from live.operations import registry
from live.sensitive import Mark, marked_fields

HINT = (
    "Mark the field with json_schema_extra={'requires': '<app>.<permission>'}, a permission one of the apps declares"
    " in its permissions, and in an answer type it to admit null (int | None)."
)


@checks.register("live")
def check_marked_fields(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """E026: every marked field of every operation's input and answer, each told once."""
    declared = declared_permissions()
    told: dict[tuple[type, str], str] = {}
    for operation_name, role, mark in _marks():
        problem = _problem(mark, declared, answer=role == "answer")
        if problem is not None:
            told.setdefault(
                (mark.schema, mark.name),
                f"Field {mark.schema.__name__}.{mark.name} of the {role} of {operation_name!r} {problem}.",
            )
    return [checks.Error(message, hint=HINT, id="live.E026") for message in told.values()]


def _marks() -> Iterator[tuple[str, str, Mark]]:
    for name, operation in sorted(registry.items()):
        for role, schema in (("input", operation.input), ("answer", operation.output)):
            for mark in marked_fields(schema):
                yield name, role, mark


def _problem(mark: Mark, declared: frozenset[str], *, answer: bool) -> str | None:
    if not isinstance(mark.permission, str) or not mark.permission:
        return "names no permission to require"
    if mark.permission not in declared:
        return f"requires {mark.permission!r}, which no app declares"
    if answer and not _admits_null(mark):
        return f"does not admit null, which is what whoever lacks {mark.permission!r} gets"
    return None


def _admits_null(mark: Mark) -> bool:
    try:
        TypeAdapter(mark.field.annotation).validate_python(None)
    except ValidationError:
        return False
    return True
