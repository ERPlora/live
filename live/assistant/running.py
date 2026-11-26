"""A tool run as the person, what a dangerous write will do, and the rounds of a request."""

import datetime as dt
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


import pydantic
import pydantic_core
from django.utils import translation

from live.assistant.cards import (
    PlainWords,
    Words,
    blocked,
    field,
)
from live.assistant.cutting import within
from live.assistant.fields import (
    fitting,
    is_money,
    label,
)
from live.assistant.tools import (
    MAX_RESULT_CHARS,
    output_schema,
    preview_of,
)
from live.context import OperationContext
from live.errors import AppInactive, OperationError, PermissionDenied, Unauthorized
from live.operations import Operation, registry


# ── A tool, run as the person ────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ToolOutcome:
    """``outcome``: ``ok``, ``error`` (the operation refused the data or the state: the model tells it), ``refused``
    (the person may not: no permission, the app off, a manager's approval) or ``cancelled`` (the person said no)."""

    outcome: str
    code: str
    content: str


def error_content(code: str, message: str, fields: dict | None = None) -> str:
    error: dict[str, Any] = {"code": code, "message": message}
    if fields:
        error["fields"] = fields
    return json.dumps({"error": error}, ensure_ascii=False)


#: What the model hears of data its operation refuses: which, and that it may ask again with them corrected.
NOT_FITTING = "Some data does not fit: nothing was done. Correct it and call the tool again."


def _validated(op: Operation, data: dict) -> tuple[ToolOutcome | None, Any]:
    """``data`` as ``op``'s input takes it: ``(None, the input)``, or ``(invalid_payload, None)`` with each field's
    message, as the operation's own validation says it (the values a closed list takes, the countries served…)."""
    try:
        return None, op.input.model_validate(data)
    except pydantic.ValidationError as exc:
        fields = {".".join(str(part) for part in error["loc"]) or "__all__": error["msg"] for error in exc.errors()}
        return ToolOutcome("error", "invalid_payload", error_content("invalid_payload", NOT_FITTING, fields)), None


def invalid_arguments(op: Operation, arguments: dict) -> ToolOutcome | None:
    """Why ``op``'s input refuses the model's ``arguments`` (``invalid_payload``, field by field), or ``None`` when it
    takes them. Asked before a write's card is drawn: the person never confirms data its operation will refuse; the
    model hears which, as the tool's result, and asks again with them corrected — one card, one yes. A dangerous
    write that names no record is not refused here: its card says it is not done from the chat (``blocked``)."""
    if blocked(op, arguments):
        return None
    failure, _ = _validated(op, arguments)
    return failure


def run(ctx: OperationContext, op: Operation, data: dict) -> tuple[ToolOutcome | None, Any]:
    """``op`` run with ``data`` for ``ctx``'s person, by its own operation: ``(None, its result)``, or why it did not
    run (``(outcome, None)``)."""
    failure, validated = _validated(op, data)
    if failure is not None:
        return failure, None
    try:
        return None, op(ctx, validated)
    except (PermissionDenied, AppInactive, Unauthorized) as exc:
        return ToolOutcome("refused", exc.code, error_content(exc.code, str(exc))), None
    except OperationError as exc:
        return ToolOutcome("error", exc.code, error_content(exc.code, str(exc), getattr(exc, "fields", None))), None


#: How the project writes an amount for the model, given in the minor unit of the currency its object names (``None``:
#: it names none, so the business's): as its screens write it, since it knows its business's currency, the decimals
#: of every other and the person's language.
Money = Callable[[int, str | None], str]


def run_tool(
    ctx: OperationContext, op: Operation, arguments: str, *, zone: dt.tzinfo | None = None, money: Money | None = None
) -> ToolOutcome:
    """Run ``op`` with the model's ``arguments`` (JSON text) for ``ctx``'s person, by its own operation. Its result
    tells its moments on ``zone``'s clock, the one of whoever asks, and its amounts as the project writes them
    (``money``), since the model repeats an hour or an amount as it reads it; without them, as the operation gives
    them."""
    try:
        data = json.loads(arguments or "{}")
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return ToolOutcome("error", "invalid_payload", error_content("invalid_payload", "The arguments are not a JSON object."))
    failure, result = run(ctx, op, data)
    if failure is not None:
        return failure
    return ToolOutcome("ok", "", within(op, data, _told_to_the_model(op, result, zone, money), MAX_RESULT_CHARS))


def _told_to_the_model(op: Operation, result: pydantic.BaseModel, zone: dt.tzinfo | None, money: Money | None) -> str:
    """``result`` as ``model_dump_json`` writes it, with every moment that knows its zone told on ``zone``'s clock and
    every amount in its currency (``_in_currency``)."""
    if zone is None and money is None:
        return result.model_dump_json()
    written = result.model_dump(mode="json")
    if zone is not None:
        written = _told(result.model_dump(), written, zone)
    if money is not None:
        schema = output_schema(op)
        written = _in_currency(written, schema, schema.get("$defs", {}), money, None)
    return pydantic_core.to_json(written).decode()


_MOMENT = pydantic.TypeAdapter(dt.datetime)


def _told(value: Any, written: Any, zone: dt.tzinfo) -> Any:
    """``written`` (``value`` in JSON) with the moments of ``value`` on ``zone``'s clock, walked side by side; what the
    two do not say alike (a serializer of its own) stays as written."""
    if isinstance(value, dt.datetime) and value.tzinfo is not None:
        return _MOMENT.dump_python(value.astimezone(zone), mode="json")
    if isinstance(value, dict) and isinstance(written, dict) and len(value) == len(written):
        return {key: _told(item, said, zone) for item, (key, said) in zip(value.values(), written.items(), strict=True)}
    if isinstance(value, list | tuple) and isinstance(written, list) and len(value) == len(written):
        return [_told(item, said, zone) for item, said in zip(value, written, strict=True)]
    return written


def _in_currency(value: Any, prop: dict, defs: dict, money: Money, named: str | None) -> Any:
    """``value`` (JSON) with every amount its schema ``prop`` marks (``is_money``) as ``money`` writes it, in the
    currency of the nearest object that names one (``named``: its ``currency``), else in the business's, at any
    depth."""
    prop = fitting(value, prop, defs)
    if isinstance(value, int) and is_money(prop):
        return money(value, named)
    if isinstance(value, dict):
        props = prop.get("properties", {})
        currency = value.get("currency")
        if isinstance(currency, str) and currency:
            named = currency
        return {key: _in_currency(inner, props.get(key, {}), defs, money, named) for key, inner in value.items()}
    if isinstance(value, list):
        items = prop.get("items")
        items = items if isinstance(items, dict) else {}
        return [_in_currency(item, items, defs, money, named) for item in value]
    return value


# ── What a dangerous write will do, on its card ──────────────────────────────────────────────────────────────────


def preview(
    ctx: OperationContext,
    op: Operation,
    arguments: dict,
    *,
    words_of_answer: Callable[[Operation, OperationContext, dict], Words] = PlainWords.of_answer,
) -> tuple[ToolOutcome | None, list[dict] | None]:
    """What the dangerous write ``op`` will do with ``arguments``, as its app says it: the read its ``ai=`` names
    (``preview_of``: ``{"operation": <a query of its app>, "fields": [<data of its answer>]}``), run as ``ctx``'s
    person — their permissions, their business — with the data of the write its input takes. The card's data, by their
    names in the person's language and in the words of the answer (``words_of_answer``: its amounts in the currency it
    answers), in the order the app names them; what the read leaves empty or hides from this person is not there.
    ``(None, None)`` without a preview; ``(outcome, None)`` when it cannot be read: the write is not confirmed blind."""
    declared = preview_of(op)
    if declared is None:
        return None, None
    read = registry[declared["operation"]]
    failure, result = run(ctx, read, {name: value for name, value in arguments.items() if name in read.input.model_fields})
    if failure is not None:
        return failure, None
    answer = result.model_dump(mode="json")
    schema = output_schema(read)
    defs = schema.get("$defs", {})
    props = schema.get("properties", {})
    words = words_of_answer(read, ctx, answer)
    money = words.money()
    with translation.override(ctx.language):
        shown = [
            field(name, label(read, name, props[name].get("title")), props[name], defs, answer.get(name), money, words)
            for name in declared["fields"]
        ]
    return None, [one for one in shown if one is not None and one["kind"] != "empty"]


# ── The rounds of a request ──────────────────────────────────────────────────────────────────────────────────────


def rounds(messages: list[dict]) -> int:
    """The rounds of tools since the person's last message: the model's messages that asked for tools."""
    count = 0
    for message in reversed(messages):
        if message.get("role") == "user":
            break
        if message.get("role") == "assistant" and message.get("tool_calls"):
            count += 1
    return count
