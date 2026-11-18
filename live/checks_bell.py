"""System check of what a counter of a module's bell says of itself (tag ``live``).

Each counter may declare how grave it is (``severity``), its heading (``title``), one sentence with the consequence
(``body``) and the label of its button (``action_label``), each a text or a lazy translation, and the field of its
query's answer that holds its deadline (``due``) (E024). The rest of a counter, and a bell that is not a list of
counters, is ``live.checks``' (E007, E009–E013).
"""

from typing import Any

from django.core import checks
from django.utils.functional import Promise

from live import operations
from live.checks import FIELD_NAME_RE, _row_fields
from live.meta import BELL_SEVERITIES, BellCounter, all_live_app_configs

WORDS = ("title", "body", "action_label")
HINT = (
    f"severity is one of {', '.join(BELL_SEVERITIES)}; title, body and action_label are texts filled in with "
    "%(count)d; due names a field of the query's answer (of its rows, when it lists them) with an ISO date-time."
)


@checks.register("live")
def check_bell_counters(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """E024: the words and the deadline of every counter of a module's bell."""
    return [
        checks.Error(f"Module {config.label!r} bell {counter.key!r} {problem}.", hint=HINT, obj=config, id="live.E024")
        for config in all_live_app_configs()
        if config.kind == "app" and isinstance(config.bell, list | tuple)
        for counter in config.bell
        if isinstance(counter, BellCounter)
        for problem in _counter_problems(counter)
    ]


def _counter_problems(counter: BellCounter) -> list[str]:
    problems = []
    if counter.severity is not None and counter.severity not in BELL_SEVERITIES:
        problems.append(f"has severity {counter.severity!r}, which is not one of {', '.join(BELL_SEVERITIES)}")
    for name in WORDS:
        value = getattr(counter, name)
        if value is not None and not isinstance(value, str | Promise):
            problems.append(f"has {name} {value!r}; it must be a text")
    return problems + _due_problems(counter)


def _due_problems(counter: BellCounter) -> list[str]:
    due = counter.due
    if due is None:
        return []
    if not isinstance(due, str) or not FIELD_NAME_RE.fullmatch(due):
        return [f"has due {due!r}; it must name a field of its query's answer"]
    declared = operations.registry.get(counter.operation)
    if declared is None or due in _answer_fields(declared.output):
        return []
    return [f"has due {due!r}, which its query {counter.operation!r} does not answer"]


def _answer_fields(output: Any) -> frozenset[str]:
    """The fields of the row a counter reads: of its rows when the answer lists them, of the answer otherwise."""
    rows = _row_fields(output)
    return rows if rows is not None else frozenset(getattr(output, "model_fields", None) or {})
