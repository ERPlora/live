"""The assistant's QA, derived from its tools (docs plan 2026-10-31, the assistant's knowledge and QA).

Every tool says what a person would type to ask for it (``AI.asks``, by language). Two layers check that the assistant
knows what each person can do:

- **Layer 1** (``misses``, ``uncovered``, ``report``): no model and no network, in every pull request. Each ask of each
  tool of a catalogue goes through the same selection a turn makes (``live.assistant.relevant``), and the tool has to
  come among the first ``top`` offered. The asks are words of their own tool (``relevant`` weighs them as its
  description's): counted (``own_asks=True``), a phrase reaches its tool whatever it says, so an app's test ranks each
  phrase without itself (``own_asks=False``: the tool keeps its other asks and its description, as a person's new
  phrase would find it), which measures that the phrases generalise. This layer proves that what people say reaches the
  tool among the hundreds of others, not that the model then calls it.
- **Layer 2** (``export_catalog``): the catalogue a QA with the real model reads to write its own phrases, per role and
  language, and to check which tool the model calls.

The Hub and the SaaS run both with their real catalogue (``live.assistant.catalog``) as each role: what a role may not
run is not in its catalogue at all.
"""

from collections.abc import Callable, Iterable, Iterator
from typing import NamedTuple

from live.assistant import MAX_TOOLS, app_words as default_app_words
from live.assistant import _asks_stems, _relevant, _stems_of
from live.assistant import asks_of, description, input_schema, risk, tool_name
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


class Reach(NamedTuple):
    """Where the asks of one tool in a language bring it (``report``): each ask's position (from 1; ``None``, not
    offered) counting every ask of its tool (``own``) and all but itself (``unseen``), in the order of ``asks``, and how
    many of each come among the first ``top`` (``own_within``, ``unseen_within``)."""

    tool_name: str
    asks: tuple[str, ...]
    own: tuple[int | None, ...]
    unseen: tuple[int | None, ...]
    own_within: int
    unseen_within: int


def _checked(top: int) -> None:
    if not 1 <= top <= MAX_TOOLS:
        raise ValueError(f"top must be between 1 and {MAX_TOOLS} (what a turn offers at most), not {top}.")


def _positions(
    tools: dict[str, Operation],
    language: str,
    *,
    own_asks: bool,
    app_words: Callable[[str, str], frozenset[str]],
    always: Iterable[str],
    synonyms: Iterable[Iterable[str]],
    howto: Iterable[str],
) -> Iterator[tuple[Operation, str, int | None]]:
    """Each ask in ``language`` of each tool, with its tool's position as a turn ranks it (``relevant``, with the turn's
    ``always``, ``app_words``, ``synonyms`` and ``howto``): counting that phrase among its tool's asks or not
    (``own_asks``)."""
    language = base_language(language)
    always, synonyms, howto = tuple(always), tuple(tuple(group) for group in synonyms), tuple(howto)
    for op in tools.values():
        said = asks_of(op)
        for ask in said.get(language, ()):
            asks = _asks_stems
            if not own_asks:
                others = _stems_of(" ".join(one for phrases in said.values() for one in phrases if one != ask))
                asks = lambda one, op=op, others=others: others if one is op else _asks_stems(one)  # noqa: E731
            offered = [
                one.name
                for one in _relevant(tools, [ask], language, always=always, app_words=app_words, synonyms=synonyms,
                                     howto=howto, asks=asks)
            ]
            yield op, ask, offered.index(op.name) + 1 if op.name in offered else None


def misses(
    tools: dict[str, Operation],
    *,
    language: str,
    top: int = 10,
    app_words: Callable[[str, str], frozenset[str]] = default_app_words,
    always: Iterable[str] = (),
    synonyms: Iterable[Iterable[str]] = (),
    howto: Iterable[str] = (),
    own_asks: bool = True,
) -> list[Miss]:
    """The asks in ``language`` of the tools of ``tools`` whose tool a turn does not offer among its first ``top``
    (``relevant``, with the turn's ``always``, ``app_words``, ``synonyms`` and ``howto``), by tool name and phrase;
    ``language`` without its region (``base_language``). ``own_asks=False`` ranks each phrase without itself: its tool
    keeps its other asks and its description. An app's test ranks so: counted, any words reach their own tool."""
    _checked(top)
    found = [
        Miss(tool_name(op.name), ask, position)
        for op, ask, position in _positions(tools, language, own_asks=own_asks, app_words=app_words, always=always,
                                            synonyms=synonyms, howto=howto)
        if position is None or position > top
    ]
    return sorted(found, key=lambda miss: (miss.tool_name, miss.ask))


def report(
    tools: dict[str, Operation],
    language: str,
    top: int = 10,
    *,
    app_words: Callable[[str, str], frozenset[str]] = default_app_words,
    always: Iterable[str] = (),
    synonyms: Iterable[Iterable[str]] = (),
    howto: Iterable[str] = (),
) -> list[Reach]:
    """Where each ask in ``language`` brings its tool, counting its own phrase and without it (``Reach``), by tool
    name: the coverage an app's test prints. A tool with no ask in ``language`` is left out (``uncovered`` lists it)."""
    _checked(top)
    ranking = {"app_words": app_words, "always": tuple(always), "synonyms": tuple(tuple(g) for g in synonyms),
               "howto": tuple(howto)}
    own = list(_positions(tools, language, own_asks=True, **ranking))
    unseen = list(_positions(tools, language, own_asks=False, **ranking))
    by_tool: dict[str, list[tuple[str, int | None, int | None]]] = {}
    for (op, ask, counted), (_, _, without) in zip(own, unseen, strict=True):
        by_tool.setdefault(op.name, []).append((ask, counted, without))

    def within(positions: tuple[int | None, ...]) -> int:
        return sum(1 for position in positions if position is not None and position <= top)

    found = []
    for name, rows in by_tool.items():
        asks, counted, without = (tuple(column) for column in zip(*rows, strict=True))
        found.append(Reach(tool_name(name), asks, counted, without, within(counted), within(without)))
    return sorted(found, key=lambda reach: reach.tool_name)


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
