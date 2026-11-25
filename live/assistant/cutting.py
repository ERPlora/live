"""A tool's result cut to what the model is told at once, saying what it did not see and how to read on."""

import json
from collections.abc import Callable
from typing import Any

from live.operations import Operation

#: Where a shortened result says how many of its rows it kept and how to read the rest.
CUT = "cut"


def within(op: Operation, data: dict, content: str, limit: int) -> str:
    """``content`` (``op``'s answer in JSON to the call's ``data``) in at most ``limit`` characters, always JSON. Too
    long, its longest list keeps the first whole items that fit and ``cut`` says how many and how to read the rest: the
    next ``offset`` when ``op`` pages, else to narrow the request. With no list to shorten, or not even one item that
    fits, every text longer than what fits keeps its first characters and says so; when even that is too long, the
    answer comes as its first characters, in a text."""
    if len(content) <= limit:
        return content
    answer = json.loads(content)
    key = _longest_list(answer)
    shortened = _shortened(op, data, answer, key, limit) if key is not None else None
    return shortened or _texts_cut(answer, limit) or _first_characters(content, limit)


def _longest_list(answer: dict) -> str | None:
    lists = [key for key, value in answer.items() if isinstance(value, list)]
    return max(lists, key=lambda key: len(_json(answer[key])), default=None)


def _shortened(op: Operation, data: dict, answer: dict, key: str, limit: int) -> str | None:
    """The answer with the most items of ``key`` that fit in ``limit``, at least one; ``None`` when not even one does."""
    return _most_that_fits(
        lambda kept: _json({**answer, key: answer[key][:kept], CUT: _said(op, data, answer, key, kept)}),
        1,
        len(answer[key]) - 1,
        limit,
    )


def _most_that_fits(write: Callable[[int], str], low: int, high: int, limit: int) -> str | None:
    """``write(kept)`` for the largest ``kept`` between ``low`` and ``high`` whose text fits in ``limit``; ``None``
    when none does. ``write`` grows with ``kept``."""
    best = None
    while low <= high:
        kept = (low + high) // 2
        written = write(kept)
        if len(written) <= limit:
            best, low = written, kept + 1
        else:
            high = kept - 1
    return best


def _said(op: Operation, data: dict, answer: dict, key: str, kept: int) -> str:
    shown = f"Only the first {kept} of the {len(answer[key])} {key} fit here"
    if "offset" not in op.input.model_fields:
        return f"{shown}: narrow the request to read the others."
    return f"{shown}: call again with offset {_skipped(answer, data) + kept} to read the next ones."


def _skipped(answer: dict, data: dict) -> int:
    """The rows before this page: as the page says it, else as the call asked."""
    for said in (answer.get("offset"), data.get("offset")):
        if isinstance(said, int):
            return said
    return 0


def _texts_cut(answer: dict, limit: int) -> str | None:
    """The answer with every text longer than the most that fits cut to its first characters, at any depth; ``None``
    when it does not fit even with every text cut."""
    return _most_that_fits(lambda kept: _json(_capped(answer, kept)), 0, limit, limit)


def _capped(value: Any, kept: int) -> Any:
    if isinstance(value, dict):
        return {key: _capped(item, kept) for key, item in value.items()}
    if isinstance(value, list):
        return [_capped(item, kept) for item in value]
    if not isinstance(value, str):
        return value
    cut = f"{value[:kept]} …(cut: only the first {kept} of {len(value)} characters fit)"
    return cut if len(cut) < len(value) else value


def _first_characters(content: str, limit: int) -> str:
    """``content``'s first characters that fit in ``limit``, as a text, and ``cut`` saying how many of how many."""
    said = f"of the {len(content)} characters of the answer fit here: narrow the request."
    found = _most_that_fits(
        lambda kept: _json({CUT: f"Only the first {kept} {said}", "answer": content[:kept]}), 0, limit, limit
    )
    return found or _json({CUT: f"Only the first 0 {said}", "answer": ""})


def _json(value: Any) -> str:
    """``value`` written as pydantic writes an answer: compact, its letters as they are."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
