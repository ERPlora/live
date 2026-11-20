"""What the app metadata check (``live.checks``, tag ``live``) checks of a module's hooks.

Only a module declares the Home's hooks (``setup``, ``widgets``, ``bell``;
E006), each a list of its dataclass (E009) whose ``operation`` is a query of the module itself
(E010), whose ``permission`` is one of the module's (E011), whose ``refresh_on`` names events that
some ``events.py`` declares (E012) and whose ``key`` is a snake_case name unique in its list (E013);
a widget renders by ``kind`` with its ``operation`` or by ``component`` (E014) at a known ``size``
(E015), and a step's ``configured_when`` is a list of ``SetupCheck`` with one condition each (E016).
They need the operations and the events registered, which ``LiveConfig.ready`` does before any check.

The device's notices of a module (``notices``) follow the same rules
(E006, E009–E013), and their texts are templates on the fields of the rows of their query, which
says what happened (``id``) and when (``at``) (E018).
"""

import re
import string
import typing
from typing import Any

from django.core import checks
from django.utils import translation
from django.utils.functional import Promise
from pydantic import BaseModel

from live import operations
from live.meta import (
    WIDGET_KINDS,
    WIDGET_SIZES,
    BellCounter,
    DeviceNotice,
    SetupCheck,
    SetupStep,
    Widget,
)

#: The hooks of a module (the Home's and the device's notices) and the dataclass of each item.
HOOKS = {"setup": SetupStep, "widgets": Widget, "bell": BellCounter, "notices": DeviceNotice}
HOOK_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
#: What every row of a notice's query says: what happened and when (the device remembers both).
NOTICE_ROW_FIELDS = ("id", "at")
FIELD_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _hook_errors(config: Any, events: frozenset[str]) -> list[checks.CheckMessage]:
    """E009–E016: the Home's hooks of a module."""
    errors = []
    for hook, item_class in HOOKS.items():
        items = getattr(config, hook)
        if not isinstance(items, list | tuple) or not all(isinstance(item, item_class) for item in items):
            errors.append(
                checks.Error(
                    f"Module {config.label!r} has {hook} {items!r}; it must be a list of live.meta.{item_class.__name__}.",
                    hint=f"e.g. {hook} = [{item_class.__name__}(key=..., ...)], or [] for none.",
                    obj=config,
                    id="live.E009",
                )
            )
            continue
        errors += _key_errors(config, hook, items)
        for item in items:
            errors += [
                checks.Error(
                    f"Module {config.label!r} {hook} {item.key!r} {problem}.", hint=hint, obj=config, id=check_id
                )
                for check_id, problem, hint in _item_problems(config, item, events)
            ]
    return errors


def _key_errors(config: Any, hook: str, items: list[Any] | tuple[Any, ...]) -> list[checks.CheckMessage]:
    """E013: every key is a snake_case name, and each appears once in its list."""
    keys = [item.key for item in items]
    problems = []
    seen: list[Any] = []  # a list, not a set: a wrong key may be unhashable
    for key in keys:
        if key in seen:
            continue
        seen.append(key)
        if not isinstance(key, str) or not HOOK_KEY_RE.fullmatch(key):
            problems.append(f"has key {key!r}, which must match {HOOK_KEY_RE.pattern}")
        elif keys.count(key) > 1:
            problems.append(f"repeats key {key!r}")
    return [
        checks.Error(
            f"Module {config.label!r} {hook} {problem}.",
            hint=f"A key is lowercase snake_case and names one item of {hook}; base shows it as <app>.<key>.",
            obj=config,
            id="live.E013",
        )
        for problem in problems
    ]


def _item_problems(config: Any, item: Any, events: frozenset[str]) -> list[tuple[str, str, str]]:
    """``(id, problem, hint)`` of each rule one item of a hook breaks."""
    problems = []
    if isinstance(item, Widget):
        problems += _widget_problems(item)
    # A widget that renders a component may go without an operation; one with a kind may not (E014).
    operation_problem = None if isinstance(item, Widget) and not item.operation else _operation_problem(config, item.operation)
    if operation_problem:
        problems.append(
            (
                "live.E010",
                operation_problem,
                f"Name a query (kind='query') of {config.label}'s queries.py or queries/ package,"
                f" e.g. '{config.label}.<entity>.status'.",
            )
        )
    if item.permission is not None and item.permission not in config.permissions:
        problems.append(
            (
                "live.E011",
                f"needs permission {item.permission!r}, which {config.label!r} does not declare",
                f"Use one of the module's permissions ({', '.join(config.permissions) or 'none declared'}), or None.",
            )
        )
    problems += _refresh_problems(item.refresh_on, events)
    if isinstance(item, SetupStep):
        problems += _configured_when_problems(item.configured_when)
    if isinstance(item, DeviceNotice) and operation_problem is None:
        problems += _notice_problems(item, operations.registry[item.operation].output)
    return problems


def _operation_problem(config: Any, name: Any) -> str | None:
    """Why ``name`` is not a query of the module itself (E010), or ``None``."""
    if not isinstance(name, str) or not name:
        return f"has operation {name!r}; it needs the name of a query of the module"
    if name.split(".", 1)[0] != config.label:
        return f"names operation {name!r} of another app; a module only uses its own queries"
    declared = operations.registry.get(name)
    if declared is None:
        return f"names operation {name!r}, which is not declared"
    if declared.kind != "query":
        return f"names operation {name!r}, which is a {declared.kind}; it must be a query"
    return None


def _refresh_problems(refresh_on: Any, events: frozenset[str]) -> list[tuple[str, str, str]]:
    """E012: refresh_on is a list of events that some events.py declares."""
    hint = "List the event in ALL of the events.py of the app that records it; names are <app>.<entity>.<fact>."
    if not isinstance(refresh_on, list | tuple):
        return [("live.E012", f"has refresh_on {refresh_on!r}; it must be a list of event names", hint)]
    return [
        ("live.E012", f"is refreshed on event {event!r}, which no events.py declares", hint)
        for event in refresh_on
        if not isinstance(event, str) or event not in events
    ]


def _widget_problems(widget: Widget) -> list[tuple[str, str, str]]:
    """E014 (render by kind with an operation, or by component, never both) and E015 (size)."""
    render_hint = f"Set kind (one of {', '.join(WIDGET_KINDS)}) with operation, or component, never both."
    problems = []
    if widget.kind is not None and widget.component:
        problems.append(("live.E014", "declares both kind and component", render_hint))
    elif widget.kind is None and not widget.component:
        problems.append(("live.E014", "declares neither kind nor component", render_hint))
    elif widget.kind is not None and widget.kind not in WIDGET_KINDS:
        problems.append(("live.E014", f"has kind {widget.kind!r}, which is not a widget kind", render_hint))
    elif widget.kind is not None and not widget.operation:
        problems.append(("live.E014", f"has kind {widget.kind!r} but no operation to feed it", render_hint))
    if widget.size not in WIDGET_SIZES:
        problems.append(
            ("live.E015", f"has size {widget.size!r}", f"Use one of {', '.join(WIDGET_SIZES)} (default 'md').")
        )
    return problems


def _row_fields(output: Any) -> frozenset[str] | None:
    """The fields of each row of a query's output (its ``rows`` or ``items``), or ``None`` without a list of them."""
    model_fields = getattr(output, "model_fields", None) or {}
    for name in ("rows", "items"):
        if name not in model_fields:
            continue
        annotation = model_fields[name].annotation
        if typing.get_origin(annotation) is list:
            [row] = typing.get_args(annotation) or (None,)
            if isinstance(row, type) and issubclass(row, BaseModel):
                return frozenset(row.model_fields)
    return None


def _notice_problems(notice: DeviceNotice, output: Any) -> list[tuple[str, str, str]]:
    """E018: the texts of a notice are templates on the fields of its query's rows, which say what happened and when."""
    fields = _row_fields(output)
    if fields is None:
        return [
            (
                "live.E018",
                f"names operation {notice.operation!r}, whose output has no rows list of what happened",
                "The query answers {rows: [...]} (or items), the newest first, one row per thing that happened.",
            )
        ]
    missing = [name for name in NOTICE_ROW_FIELDS if name not in fields]
    if missing:
        return [
            (
                "live.E018",
                f"names operation {notice.operation!r}, whose rows lack {', '.join(map(repr, missing))}",
                "Each row says what happened (id) and the instant it happened (at): the device tells each pair once.",
            )
        ]
    hint = (
        "e.g. title=[_('New booking · {customer_name}'), _('New booking')], body=['{service_names}'], "
        "route='/agenda?date={start:.10}': named fields of the rows of the query, nothing else."
    )
    problems = []
    with translation.override("en"):
        templates = _template_lists(notice, problems, hint)
        for template in templates:
            problems += [("live.E018", problem, hint) for problem in _template_problems(str(template), fields)]
    problems += _when_problems(notice.when, fields)
    return problems


def _template_lists(notice: DeviceNotice, problems: list[tuple[str, str, str]], hint: str) -> list[Any]:
    """The templates of the notice that are texts; each misshapen text field goes to ``problems``."""
    templates = []
    for name, value, required in (("title", notice.title, True), ("body", notice.body, False)):
        if not isinstance(value, list | tuple) or (required and not value):
            what = "a list of templates, the first one that fills in wins" if required else "a list of parts"
            problems.append(("live.E018", f"has {name} {value!r}; it must be {what}", hint))
        elif not all(isinstance(text, str | Promise) for text in value):
            problems.append(("live.E018", f"has {name} {list(value)!r}, whose templates must all be texts", hint))
        else:
            templates += value
    route = notice.route
    if not isinstance(route, str | Promise) or not str(route).startswith("/") or str(route).startswith("//"):
        problems.append(("live.E018", f"has route {route!r}; it must be a screen of the hub, '/…'", hint))
    else:
        templates.append(route)
    return templates


def _template_problems(template: str, fields: frozenset[str]) -> list[str]:
    """Why ``template`` is not a ``str.format`` template on ``fields``, one reason per field."""
    try:
        parts = list(string.Formatter().parse(template))
    except ValueError:
        return [f"has a broken template {template!r}"]
    problems = []
    for _literal, name, spec, _conversion in parts:
        if name is None:
            continue
        if name == "" or name.isdigit():
            problems.append(f"has a positional field in template {template!r}; name a field of the row")
        elif spec and "{" in spec:
            problems.append(f"has a nested field in template {template!r}")
        elif not FIELD_NAME_RE.fullmatch(name):
            problems.append(f"names {name!r} in template {template!r}; only a field of the row, as it is")
        elif name not in fields:
            problems.append(f"names field {name!r} in template {template!r}, which the rows of its query lack")
    return problems


def _when_problems(when: Any, fields: frozenset[str]) -> list[tuple[str, str, str]]:
    """E018: ``when`` is a list of SetupCheck, each on a field of the rows with exactly one of truthy and equals."""
    hint = "e.g. when=[SetupCheck(field='kind', equals='booked')]; [] = every row of the query."
    if not isinstance(when, list | tuple):
        return [("live.E018", f"has when {when!r}; it must be a list of SetupCheck", hint)]
    problems = []
    for check in when:
        if not isinstance(check, SetupCheck):
            problem = f"has a when condition {check!r}, which is not a live.meta.SetupCheck"
        elif (check.truthy is None) == (check.equals is None):
            problem = f"has a when condition {check!r}, which needs exactly one of truthy and equals"
        elif check.field not in fields:
            problem = f"has a when condition on {check.field!r}, which the rows of its query lack"
        else:
            continue
        problems.append(("live.E018", problem, hint))
    return problems


def _configured_when_problems(configured_when: Any) -> list[tuple[str, str, str]]:
    """E016: a list of SetupCheck, each on a field with exactly one of truthy and equals."""
    hint = "e.g. configured_when = [SetupCheck(field='active_products', truthy=True)]; [] = having a row is enough."
    if not isinstance(configured_when, list | tuple):
        return [("live.E016", f"has configured_when {configured_when!r}; it must be a list of SetupCheck", hint)]
    problems = []
    for check in configured_when:
        if not isinstance(check, SetupCheck):
            problem = f"has condition {check!r}, which is not a live.meta.SetupCheck"
        elif not isinstance(check.field, str) or not check.field:
            problem = f"has condition {check!r} without a field"
        elif (check.truthy is None) == (check.equals is None):
            problem = f"has condition {check!r}, which needs exactly one of truthy and equals"
        else:
            continue
        problems.append(("live.E016", problem, hint))
    return problems
