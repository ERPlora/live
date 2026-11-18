"""A tool run as the person, what a dangerous write will do, and the rounds of a request."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pydantic
from django.utils import translation

from live.assistant.cards import (
    PlainWords,
    Words,
    blocked,
    field,
)
from live.assistant.fields import (
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


def run_tool(ctx: OperationContext, op: Operation, arguments: str) -> ToolOutcome:
    """Run ``op`` with the model's ``arguments`` (JSON text) for ``ctx``'s person, by its own operation."""
    try:
        data = json.loads(arguments or "{}")
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return ToolOutcome("error", "invalid_payload", error_content("invalid_payload", "The arguments are not a JSON object."))
    failure, result = run(ctx, op, data)
    if failure is not None:
        return failure
    content = result.model_dump_json()
    if len(content) > MAX_RESULT_CHARS:
        content = content[:MAX_RESULT_CHARS] + " …(cut)"
    return ToolOutcome("ok", "", content)


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
