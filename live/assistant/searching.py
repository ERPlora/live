"""The search of the tools a turn did not offer. A turn offers only the tools its words name best (``relevant``), so a
project gives its model, last in every turn, a search tool of its own: an operation whose input takes the task as
``query`` and whose answer is what ``found`` finds. The model searches for the task it lacks a tool for, and the next
round of the same request offers what it found (``offered``, with what the model ``searched`` for).
"""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from pydantic import ValidationError

from live.assistant.ranking import relevant
from live.assistant.tools import tool_name
from live.operations import Operation

#: The tools a search finds at most.
FOUND = 10


@dataclass(frozen=True)
class ToolSearch:
    """A project's search of the tools a turn did not offer: its operation (``op``), and the places a turn gives the
    person's tools before it."""

    op: Operation
    places: int


def found(tools: dict[str, Operation], query: str, language: str, **ranking) -> list[Operation]:
    """The tools of ``tools`` that do the task ``query`` describes, best first, at most ``FOUND``: ranked as a turn
    ranks the person's words (``ranking``: what ``relevant`` takes), without what every turn offers anyway (its
    ``always``)."""
    always = set(ranking.get("always", ()))
    ranked = relevant(tools, [query], language, **{**ranking, "always": ()})
    return [op for op in ranked if op.name not in always][:FOUND]


def offered(
    tools: dict[str, Operation],
    texts: Iterable[str],
    language: str,
    *,
    search: ToolSearch,
    searched: Iterable[str] = (),
    **ranking,
) -> list[Operation]:
    """The tools of what ``texts`` ask, best first, in the ``places`` of the project's ``search`` (``relevant``, as
    ``ranking`` says), and its search last: it never ranks, so no tool loses its place to it. What the model
    ``searched`` for goes right after ``always``, the latest search first, so the tool it found is never left out."""
    always = set(ranking.get("always", ()))
    ranked = relevant(tools, texts, language, **ranking)
    searches = [op for query in reversed(list(searched)) for op in found(tools, query, language, **ranking)]
    first = [op for op in ranked if op.name in always]
    kept = list({op.name: op for op in [*first, *searches, *ranked]}.values())[: search.places]
    return [*kept, search.op]


def searched(messages: Iterable[dict], search: Operation) -> list[str]:
    """The tasks the model searched for with ``search`` in ``messages``, in order: the ``query`` its input takes. A call
    whose arguments that input refuses searched nothing."""
    queries = []
    for arguments in _arguments(messages, tool_name(search.name)):
        try:
            queries.append(search.input.model_validate_json(arguments).query)
        except ValidationError:
            continue
    return queries


def _arguments(messages: Iterable[dict], name: str) -> Iterator[str]:
    """The arguments of each call of the model to the tool ``name`` in ``messages``, as it wrote them; what the browser
    kept in another shape is no call."""
    for message in messages:
        calls = message.get("tool_calls") if message.get("role") == "assistant" else None
        for call in calls if isinstance(calls, list) else ():
            function = call.get("function") if isinstance(call, dict) else None
            if isinstance(function, dict) and function.get("name") == name:
                yield str(function.get("arguments") or "{}")
