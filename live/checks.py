"""System checks of the app metadata (tag ``live``; round 15, PLAN §20).

A module (``kind = "app"``) carries what the Hub's apps page shows next to its name (``icon``,
``category``) and only requires other modules, without cycles. A platform app (``kind =
"platform"``) is always on, so the module fields mean nothing for it. The metadata is one graph:
the checks always look at every app of ours, whatever ``app_configs`` ``manage.py check`` passes.
Registered when ``live`` is ready (``LiveConfig.ready`` imports this module).

Round 16 (PLAN §21): a module also carries what the public store shows (``summary``,
``description``, E007) and the verticals it belongs to (``verticals``, E008). What needs to read
files (WORKBOOK, translations, baked icons, images) is not a check: ``register_apps`` validates it.

PLAN-HUB round 2026-10-21: only a module declares the Home's hooks (``setup``, ``widgets``, ``bell``;
E006), each a list of its dataclass (E009) whose ``operation`` is a query of the module itself
(E010), whose ``permission`` is one of the module's (E011), whose ``refresh_on`` names events that
some ``events.py`` declares (E012) and whose ``key`` is a snake_case name unique in its list (E013);
a widget renders by ``kind`` with its ``operation`` or by ``component`` (E014) at a known ``size``
(E015), and a step's ``configured_when`` is a list of ``SetupCheck`` with one condition each (E016).
They need the operations and the events registered, which ``LiveConfig.ready`` does before any check.

PLAN-HUB round 2026-10-23: the device's notices of a module (``notices``) follow the same rules
(E006, E009–E013), and their texts are templates on the fields of the rows of their query, which
says what happened (``id``) and when (``at``) (E018).

FIX-LIVE-SESSION-CLOSED-WAKES-ONLY-SESSION-LIST: ``settings.LIVE["session_events"]``, the events after which every
live stream of the channel re-reads its context, is a list of events that some ``events.py`` declares (E019).
"""

import re
import string
import typing
from typing import Any

from django.conf import settings
from django.core import checks
from django.utils import translation
from django.utils.functional import Promise
from pydantic import BaseModel

from live import operations
from live.meta import (
    WIDGET_KINDS,
    WIDGET_SIZES,
    BellCounter,
    Category,
    DeviceNotice,
    LiveAppConfig,
    SetupCheck,
    SetupStep,
    Widget,
    all_live_app_configs,
    declared_events,
)

KINDS = ("platform", "app")
# Fields that only a module may declare; a platform app leaves them at their defaults (compared with
# the default, not with truthiness: listed defaults to True).
MODULE_ONLY_FIELDS = (
    "requires",
    "category",
    "premium",
    "navigation",
    "summary",
    "description",
    "verticals",
    "listed",
    "setup",
    "widgets",
    "bell",
    "notices",
)
#: The hooks of a module (the Home's and the device's notices) and the dataclass of each item.
HOOKS = {"setup": SetupStep, "widgets": Widget, "bell": BellCounter, "notices": DeviceNotice}
HOOK_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
# The columns of shared.app they are written to (round 16, spec §3.1).
SUMMARY_MAX_LENGTH = 120
NAME_MAX_LENGTH = 80
# A vertical id names a template database, hub_template_<vertical>, so it has the shape of PLAN §15.2
# (no "__") and fits in Postgres' 63 characters with that prefix; "test" is the tests' template.
VERTICAL_RE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")
VERTICAL_MAX_LENGTH = 63 - len("hub_template_")
RESERVED_VERTICALS = frozenset({"test"})
#: What every row of a notice's query says: what happened and when (the device remembers both).
NOTICE_ROW_FIELDS = ("id", "at")
FIELD_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@checks.register("live")
def check_app_metadata(
    app_configs: Any = None, **kwargs: Any
) -> list[checks.CheckMessage]:
    configs = all_live_app_configs()
    modules = {config.label for config in configs if config.kind == "app"}
    events = declared_events()
    errors: list[checks.CheckMessage] = []
    for config in configs:
        if config.kind not in KINDS:
            errors.append(
                checks.Error(
                    f"App {config.label!r} has kind {config.kind!r}; it must be 'platform' or 'app'.",
                    hint="'app' for a module of apps/ that a hub turns on and off, 'platform' for an always-on app.",
                    obj=config,
                    id="live.E001",
                )
            )
        elif config.kind == "app":
            errors += _module_errors(config) + _hook_errors(config, events)
        else:
            errors += _platform_errors(config)
        errors += [
            checks.Error(
                f"App {config.label!r} requires {required!r}, which is not a module (kind = 'app').",
                hint="requires only names labels of modules of apps/, never a platform app such as base.",
                obj=config,
                id="live.E004",
            )
            for required in config.requires
            if required not in modules
        ]
    errors += _cycle_errors(configs, modules)
    return errors


@checks.register("live")
def check_session_events(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """E019: ``LIVE["session_events"]`` (optional) is a list of event names that some ``events.py`` declares."""
    value = getattr(settings, "LIVE", {}).get("session_events", [])
    hint = (
        'LIVE["session_events"] lists, by name, the events after which every live stream of the channel re-reads its '
        "context (its session may have ended); each one is in the ALL list of an events.py."
    )
    if not isinstance(value, list | tuple):
        message = f'LIVE["session_events"] is {value!r}; it must be a list of event names.'
        return [checks.Error(message, hint=hint, id="live.E019")]
    events = declared_events()
    return [
        checks.Error(f'LIVE["session_events"] names {event!r}, which no events.py declares.', hint=hint, id="live.E019")
        for event in value
        if not isinstance(event, str) or event not in events
    ]


def _module_errors(config: Any) -> list[checks.CheckMessage]:
    errors = []
    if not config.icon:
        errors.append(
            checks.Error(
                f"Module {config.label!r} has no icon.",
                hint="Set icon to an Iconify name with its set prefix, e.g. 'ion:people'.",
                obj=config,
                id="live.E002",
            )
        )
    if not isinstance(config.category, Category):
        errors.append(
            checks.Error(
                f"Module {config.label!r} has category {config.category!r}; it must be a live.meta.Category.",
                hint=f"Use one of {', '.join(f'Category.{category.name}' for category in Category)}.",
                obj=config,
                id="live.E003",
            )
        )
    return errors + _store_errors(config) + _vertical_errors(config)


def _store_errors(config: Any) -> list[checks.CheckMessage]:
    """E007: what the public store shows of a module fits its columns of shared.app.

    Lazy translations are measured by their English text; the Spanish one is checked by
    register_apps, which reads the catalogues.
    """
    with translation.override("en"):
        name = str(config.verbose_name)
        summary = str(config.summary)
        description = str(config.description)
    problems = []
    if not summary.strip():
        problems.append(("has no summary", "Set summary to one line that says what the module does."))
    elif len(summary.splitlines()) > 1:
        problems.append(("has a summary of more than one line", "Write the summary in one line."))
    if len(summary) > SUMMARY_MAX_LENGTH:
        problems.append(
            (
                f"has a summary of {len(summary)} characters; at most {SUMMARY_MAX_LENGTH} fit",
                "Shorten the summary; the description holds the paragraph.",
            )
        )
    if not description.strip():
        problems.append(("has no description", "Set description to one paragraph for the public store."))
    if len(name) > NAME_MAX_LENGTH:
        problems.append(
            (
                f"has a verbose_name of {len(name)} characters; at most {NAME_MAX_LENGTH} fit",
                "Shorten verbose_name.",
            )
        )
    return [
        checks.Error(f"Module {config.label!r} {problem}.", hint=hint, obj=config, id="live.E007")
        for problem, hint in problems
    ]


def _vertical_errors(config: Any) -> list[checks.CheckMessage]:
    """E008: every vertical id is well formed, not reserved and listed once."""
    verticals = config.verticals
    if not isinstance(verticals, list | tuple):
        return [
            checks.Error(
                f"Module {config.label!r} has verticals {verticals!r}; it must be a list of vertical ids.",
                hint="e.g. verticals = ['hair_salon', 'restaurant'], or [] for none.",
                obj=config,
                id="live.E008",
            )
        ]
    errors = []
    seen: list[Any] = []  # a list, not a set: a wrong entry may be unhashable
    for vertical in verticals:
        if vertical in seen:
            continue
        seen.append(vertical)
        if (
            not isinstance(vertical, str)
            or not VERTICAL_RE.fullmatch(vertical)
            or len(vertical) > VERTICAL_MAX_LENGTH
        ):
            problem = (
                f"must match {VERTICAL_RE.pattern} and have at most {VERTICAL_MAX_LENGTH} characters"
            )
        elif vertical in RESERVED_VERTICALS:
            problem = "is reserved for the test suites' template (hub_template_test)"
        elif verticals.count(vertical) > 1:
            problem = "is listed more than once"
        else:
            continue
        errors.append(
            checks.Error(
                f"Module {config.label!r} has vertical {vertical!r}, which {problem}.",
                hint="A vertical id is lowercase snake_case, e.g. 'hair_salon', and appears once.",
                obj=config,
                id="live.E008",
            )
        )
    return errors


def _hook_errors(config: Any, events: frozenset[str]) -> list[checks.CheckMessage]:
    """E009–E016: the Home's hooks of a module (PLAN-HUB round 2026-10-21)."""
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
                f"Name a query (kind='query') of {config.label}'s queries.py, e.g. '{config.label}.<entity>.status'.",
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


def _platform_errors(config: Any) -> list[checks.CheckMessage]:
    declared = [
        field for field in MODULE_ONLY_FIELDS if getattr(config, field) != getattr(LiveAppConfig, field)
    ]
    if not declared:
        return []
    return [
        checks.Error(
            f"Platform app {config.label!r} declares {', '.join(declared)}; only modules (kind = 'app') have them.",
            hint="Remove them, or set kind = 'app' if the app is a module of apps/.",
            obj=config,
            id="live.E006",
        )
    ]


def _cycle_errors(configs: list[Any], modules: set[str]) -> list[checks.CheckMessage]:
    """One error per cycle of ``requires`` (edges to modules only; the rest is E004)."""
    by_label = {config.label: config for config in configs}
    edges = {
        config.label: [required for required in config.requires if required in modules]
        for config in configs
    }
    done: set[str] = set()
    cycles: list[list[str]] = []

    def visit(label: str, path: list[str]) -> None:
        path.append(label)
        for required in edges[label]:
            if required in path:
                cycle = path[path.index(required) :]
                start = cycle.index(min(cycle))
                cycles.append(cycle[start:] + cycle[:start])
            elif required not in done:
                visit(required, path)
        path.pop()
        done.add(label)

    for config in configs:
        if config.label not in done:
            visit(config.label, [])
    return [
        checks.Error(
            f"Cycle in requires: {' → '.join([*cycle, cycle[0]])}.",
            hint="requires is an acyclic graph: one of these modules must not require the other.",
            obj=by_label[cycle[0]],
            id="live.E005",
        )
        for cycle in cycles
    ]
