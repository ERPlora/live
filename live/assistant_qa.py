"""The assistant's QA, derived from its tools (docs plan 2026-10-31, the assistant's knowledge and QA).

Every tool says what a person would type to ask for it (``AI.asks``, by language). Two layers check that the assistant
knows what each person can do:

- **Layer 1** (``misses``, ``uncovered``): no model and no network, in every pull request. Each ask of each tool of a
  catalogue goes through the same selection a turn makes (``live.assistant.relevant``), and the tool has to come among
  the first ``top`` offered. The asks are words of their own tool (``relevant`` weighs them as its description's), so
  this layer proves that the phrases people use reach it among the hundreds of others, not that the model then calls it.
- **Layer 2** (``export_catalog``): the catalogue a QA with the real model reads to write its own phrases, per role and
  language, and to check which tool the model calls.

The Hub and the SaaS run both with their real catalogue (``live.assistant.catalog``) as each role: what a role may not
run is not in its catalogue at all.
"""

from collections.abc import Callable, Iterable
from typing import NamedTuple

from live.assistant import MAX_TOOLS, app_words as default_app_words
from live.assistant import asks_of, description, input_schema, relevant, risk, tool_name
from live.operations import Operation

#: An operation's kind as the QA says it: a query reads, a command writes.
KINDS = {"query": "read", "command": "write"}


def base_language(language: str) -> str:
    """The language of ``language`` without its region (``es-ES``, ``es_ES``, ``ES`` → ``es``): the asks are said by
    language, and a context may name the region."""
    return language.replace("_", "-").split("-")[0].lower()


class Miss(NamedTuple):
    """An ask whose tool is not among the first offered: at ``position`` (from 1), or ``None`` when not offered."""

    tool_name: str
    ask: str
    position: int | None


def misses(
    tools: dict[str, Operation],
    *,
    language: str,
    top: int = 10,
    app_words: Callable[[str, str], frozenset[str]] = default_app_words,
    always: Iterable[str] = (),
) -> list[Miss]:
    """The asks in ``language`` of the tools of ``tools`` whose tool a turn does not offer among its first ``top``
    (``relevant``, with the turn's ``always`` and ``app_words``), by tool name and phrase; ``language`` without its
    region (``base_language``)."""
    if not 1 <= top <= MAX_TOOLS:
        raise ValueError(f"top must be between 1 and {MAX_TOOLS} (what a turn offers at most), not {top}.")
    language = base_language(language)
    always = tuple(always)
    found: list[Miss] = []
    for op in tools.values():
        for ask in asks_of(op).get(language, ()):
            offered = [one.name for one in relevant(tools, [ask], language, always=always, app_words=app_words)]
            position = offered.index(op.name) + 1 if op.name in offered else None
            if position is None or position > top:
                found.append(Miss(tool_name(op.name), ask, position))
    return sorted(found, key=lambda miss: (miss.tool_name, miss.ask))


def uncovered(tools: dict[str, Operation], language: str) -> list[str]:
    """The tool names of ``tools`` that say no ask in ``language``, sorted."""
    language = base_language(language)
    return sorted(tool_name(op.name) for op in tools.values() if not asks_of(op).get(language))


def export_catalog(tools: dict[str, Operation], language: str) -> list[dict]:
    """``tools`` as the real model's QA reads them, by name: JSON-serialisable, each with its asks in ``language``."""
    language = base_language(language)
    return [
        {
            "name": op.name,
            "tool_name": tool_name(op.name),
            "app_label": op.app_label,
            "kind": KINDS[op.kind],
            "permission": op.permission,
            "risk": risk(op),
            "description": description(op),
            "asks": list(asks_of(op).get(language, ())),
            "input_schema": input_schema(op),
        }
        for _, op in sorted(tools.items())
    ]
