"""A tool's result cut to what the model is told at once, saying what it did not see and how to read on."""

import json
from typing import Any

from live.operations import Operation

#: Where a shortened result says how many of its rows it kept and how to read the rest.
CUT = "cut"


def within(op: Operation, data: dict, content: str, limit: int) -> str:
    """``content`` (``op``'s answer in JSON to the call's ``data``) in at most ``limit`` characters. Too long, its
    longest list keeps the first whole items that fit and ``cut`` says how many and how to read the rest: the next
    ``offset`` when ``op`` pages, else to narrow the request. With no list to shorten, the text is cut and says so."""
    if len(content) <= limit:
        return content
    answer = json.loads(content)
    key = _longest_list(answer)
    shortened = _shortened(op, data, answer, key, limit) if key is not None else None
    return shortened if shortened is not None else _cut_text(content, limit)


def _longest_list(answer: dict) -> str | None:
    lists = [key for key, value in answer.items() if isinstance(value, list)]
    return max(lists, key=lambda key: len(_json(answer[key])), default=None)


def _shortened(op: Operation, data: dict, answer: dict, key: str, limit: int) -> str | None:
    """The answer with the most items of ``key`` that fit in ``limit``, at least one; ``None`` when not even one does."""
    best, low, high = None, 1, len(answer[key]) - 1
    while low <= high:
        kept = (low + high) // 2
        written = _json({**answer, key: answer[key][:kept], CUT: _said(op, data, answer, key, kept)})
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


def _cut_text(content: str, limit: int) -> str:
    notice = f" …(cut: only the first {{}} of {len(content)} characters fit)"
    seen = limit - len(notice.format(limit))
    return content[:seen] + notice.format(seen)


def _json(value: Any) -> str:
    """``value`` written as pydantic writes an answer: compact, its letters as they are."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
