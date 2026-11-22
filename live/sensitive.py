"""Data only whoever holds a permission sees: a field of a schema marked ``json_schema_extra={"requires":
"<permission>"}`` (in the Hub, a product's cost asks for ``base.view_costs``).

Every door calls the operation, so ``Operation.__call__`` applies the mark for its caller, at any depth (an object inside
another, a list or a map of them): the answer carries the field as null to whoever lacks the permission, and an input
that fills it (a filter, a line of a write) with anything but its default is refused, as an operation the caller may not
run. In an answer the field admits null (``live.E026``). The mark also shows beside the field in the OpenAPI.
"""

from collections.abc import Iterable, Iterator
from functools import cache
from typing import Any, NamedTuple, get_args

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from live.context import OperationContext

REQUIRES = "requires"


class Mark(NamedTuple):
    schema: type[BaseModel]
    name: str
    field: FieldInfo
    #: What the mark says: a permission, unless it is misdeclared (``live.E026`` tells).
    permission: Any


def required_permission(field: FieldInfo) -> Any:
    """What ``field``'s mark requires, or ``None`` when it has none."""
    extra = field.json_schema_extra
    return extra.get(REQUIRES) if isinstance(extra, dict) else None


def marked_fields(schema: type[BaseModel]) -> Iterator[Mark]:
    """Every marked field of ``schema`` and of the schemas inside it, at any depth, each once."""
    seen: set[type[BaseModel]] = set()
    pending = [schema]
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        for name, field in current.model_fields.items():
            permission = required_permission(field)
            if permission is not None:
                yield Mark(current, name, field, permission)
            pending.extend(_schemas_in(field.annotation))


def hidden(ctx: OperationContext, answer: Any) -> Any:
    """``answer`` as ``ctx`` may see it: every marked field whose permission it lacks, null. What changes is a copy: the
    objects the operation answered with (a cache, a constant) are never touched."""
    if isinstance(answer, BaseModel):
        return _hidden_fields(ctx, answer) if _carries_marks(type(answer)) else answer
    if isinstance(answer, list | tuple):
        shown = [hidden(ctx, item) for item in answer]
        if all(new is old for new, old in zip(shown, answer, strict=True)):
            return answer
        return shown if isinstance(answer, list) else tuple(shown)
    if isinstance(answer, dict):
        shown_values = {key: hidden(ctx, item) for key, item in answer.items()}
        return answer if all(shown_values[key] is item for key, item in answer.items()) else shown_values
    return answer


def unpermitted(ctx: OperationContext, data: Any) -> str | None:
    """The permission of a marked field ``data`` fills that ``ctx`` lacks, or ``None``. Filled is anything but the
    field's default: a filter left out (``None``) asks for nothing."""
    return next((permission for permission in _filled(data) if not ctx.has(permission)), None)


def _hidden_fields(ctx: OperationContext, model: BaseModel) -> BaseModel:
    changes = {}
    for name, field in type(model).model_fields.items():
        value = getattr(model, name)
        permission = required_permission(field)
        shown = None if permission is not None and not ctx.has(permission) else hidden(ctx, value)
        if shown is not value:
            changes[name] = shown
    return model.model_copy(update=changes) if changes else model


def _filled(data: Any) -> Iterator[str]:
    """The permission of each marked field ``data`` fills, at any depth."""
    if isinstance(data, BaseModel) and _carries_marks(type(data)):
        for name, field in type(data).model_fields.items():
            value = getattr(data, name)
            permission = required_permission(field)
            if permission is not None and value != field.get_default(call_default_factory=True):
                yield permission
            yield from _filled(value)
    for item in _held(data):
        yield from _filled(item)


def _held(value: Any) -> Iterable[Any]:
    """What a list, a tuple or a map holds; nothing for anything else."""
    if isinstance(value, list | tuple):
        return value
    if isinstance(value, dict):
        return value.values()
    return ()


@cache
def _carries_marks(schema: type[BaseModel]) -> bool:
    """Whether ``schema`` or a schema inside it has a marked field: one without any is answered as it is."""
    return next(marked_fields(schema), None) is not None


def _schemas_in(annotation: Any) -> Iterator[type[BaseModel]]:
    """The schemas a field's type names: itself, or inside ``X | None``, ``list[X]``, ``dict[str, X]``…"""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        yield annotation
        return
    for argument in get_args(annotation):
        yield from _schemas_in(argument)
