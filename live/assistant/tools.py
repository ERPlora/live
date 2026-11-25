"""The assistant's tools: which operations are tools, how they are named and described to the model."""

from collections.abc import Callable, Collection, Mapping
from functools import cache
from typing import Any

from django.utils.translation import pgettext_lazy

from live.context import OperationContext
from live.meta import LiveAppConfig, all_live_app_configs
from live.operations import AI, Operation, registry


#: The tools a turn offers at most: the gateway takes 256, but the model providers advise fewer than twenty at a time,
#: and each one offered travels whole with every call.
MAX_TOOLS = 20
#: Rounds of tools of one request of the person: a guard against a loop, not an allowance. A model may ask for several
#: tools in one round; asking for one at a time, a read and a change per day of the week take eight.
MAX_ROUNDS = 20
#: A tool's result told back to the model at once: it travels again with every later call, so a longer one keeps the
#: rows that fit and says how to read the rest (``cutting.within``). A default page of fifty short rows fits.
MAX_RESULT_CHARS = 16_000
SEPARATOR = "__"
#: What a dangerous write asks to type, in the person's language.
CONFIRM_WORD = pgettext_lazy("assistant", "CONFIRM")


# ── Tools ────────────────────────────────────────────────────────────────────────────────────────────────────────


def tool_name(operation_name: str) -> str:
    """The operation's name as a tool's (the gateway's function names take no dots)."""
    return operation_name.replace(".", SEPARATOR)


def operation_of(name: str, tools: dict[str, Operation]) -> Operation | None:
    """The operation of the tool ``name`` among ``tools``; ``None`` for one it was not offered."""
    for op in tools.values():
        if tool_name(op.name) == name:
            return op
    return None


def named(name: str) -> Operation | None:
    """The registered operation the tool ``name`` stands for, offered or not: only to name it in a receipt («Not done,
    not allowed: Create in Demo»); it never runs from here."""
    return operation_of(name, registry)


def description(op: Operation) -> str:
    """What ``op``'s ``ai=`` tells the model it does (a ``dict``'s as written, «Not an assistant tool…» too); ``""``
    when it declares none or ``INTERNAL``."""
    declared = op.ai
    if isinstance(declared, AI):
        return declared.description.strip()
    return str(declared.get("description", "")).strip() if isinstance(declared, dict) else ""


def risk(op: Operation) -> str:
    """``high`` when ``op``'s ``ai=`` says so (a ``dict``'s too, tool or not: an automation never runs it alone),
    ``normal`` otherwise."""
    declared = op.ai
    said = declared.risk if isinstance(declared, AI) else declared.get("risk") if isinstance(declared, dict) else None
    return "high" if said == "high" else "normal"


def preview_of(op: Operation) -> Any:
    """What ``op``'s ``ai=`` declares as its preview, or ``None``."""
    declared = op.ai
    if isinstance(declared, AI):
        return declared.preview
    return declared.get("preview") if isinstance(declared, dict) else None


def asks_of(op: Operation) -> dict[str, tuple[str, ...]]:
    """What a person would type to ask for ``op``, by language, as its ``ai=`` says it (an ``AI``'s or a ``dict``'s
    ``asks``): each phrase stripped, an empty or repeated one left out, a lone phrase read as one; a language with none
    left, anything that is not a mapping of language → phrases and what is no tool (``Operation.ai_spec``: never
    offered, so nothing asks for it) read as nothing."""
    spec = op.ai_spec()
    said = spec.asks if isinstance(spec, AI) else None
    if not isinstance(said, Mapping):
        return {}
    asks: dict[str, tuple[str, ...]] = {}
    for language, phrases in said.items():
        if isinstance(phrases, str):
            phrases = (phrases,)
        if not isinstance(language, str) or not isinstance(phrases, list | tuple):
            continue
        kept = tuple(dict.fromkeys(phrase.strip() for phrase in phrases if isinstance(phrase, str) and phrase.strip()))
        if kept:
            asks[language] = kept
    return asks


def is_tool(op: Operation, *, not_from_chat: Collection[str] = frozenset()) -> bool:
    """Whether ``op`` is an assistant tool: its ``ai=`` is one (``Operation.ai_spec``) and the project does not keep it
    out of the chat (``not_from_chat``: emptying the business, a file to download)."""
    return isinstance(op.ai_spec(), AI) and op.name not in not_from_chat


def catalog(
    ctx: OperationContext,
    *,
    active_labels: Collection[str],
    not_from_chat: Collection[str] = frozenset(),
    approvable: Callable[[Operation], bool] | None = None,
) -> dict[str, Operation]:
    """The tools of ``ctx``'s person among the apps ``active_labels``: by name, in name order. A write someone else may
    approve (``approvable``) is theirs too, as its button on the screen is: running it asks for the approval."""
    return {
        name: op
        for name, op in sorted(registry.items())
        if op.app_label in active_labels
        and is_tool(op, not_from_chat=not_from_chat)
        and (ctx.has(op.permission) or (approvable is not None and approvable(op)))
    }


@cache
def input_schema(op: Operation) -> dict:
    return op.input.model_json_schema()


@cache
def output_schema(op: Operation) -> dict:
    return op.output.model_json_schema()


#: Keywords whose value is data as the app wrote it (a default, an example): a «title» in them is no schema's.
DATA_KEYWORDS = frozenset({"default", "examples", "const", "enum"})
#: Keywords that hold schemas by their names: a datum or a definition may well be called «title».
NAMED_SCHEMAS = frozenset({"properties", "$defs", "patternProperties", "dependentSchemas"})


def _untitled(schema: Any) -> Any:
    if isinstance(schema, list):
        return [_untitled(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    return {key: _untitled_value(key, value) for key, value in schema.items() if key != "title"}


def _untitled_value(key: str, value: Any) -> Any:
    if key in DATA_KEYWORDS:
        return value
    if key in NAMED_SCHEMAS and isinstance(value, dict):
        return {name: _untitled(schema) for name, schema in value.items()}
    return _untitled(value)


@cache
def tool_parameters(op: Operation) -> dict:
    """``op``'s input schema as the model is told it: without the titles pydantic writes, which repeat each datum's
    name («Product Id») and weigh on every call. A write's card still reads them from ``input_schema``."""
    return _untitled(input_schema(op))


def tool_spec(op: Operation) -> dict:
    """``op`` as the gateway takes a tool (OpenAI's ``function``)."""
    return {"type": "function", "name": tool_name(op.name), "description": description(op), "parameters": tool_parameters(op)}


def config_of(label: str) -> LiveAppConfig | None:
    return next((config for config in all_live_app_configs() if config.label == label), None)
