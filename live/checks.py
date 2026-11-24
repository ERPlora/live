"""System checks of the app metadata (tag ``live``).

A module (``kind = "app"``) carries what the Hub's apps page shows next to its name (``icon``,
``category``) and only requires other modules, without cycles. A platform app (``kind =
"platform"``) is always on, so the module fields mean nothing for it. The metadata is one graph:
the checks always look at every app of ours, whatever ``app_configs`` ``manage.py check`` passes.
Registered when ``live`` is ready (``LiveConfig.ready`` imports this module).

A module also carries what the public store shows (``summary``,
``description``, E007) and the verticals it belongs to (``verticals``, E008). What needs to read
files (WORKBOOK, translations, baked icons, images) is not a check: ``register_apps`` validates it.

Only a module declares the Home's hooks (``setup``, ``widgets``, ``bell``), the device's notices (``notices``) and
the steps of the charge of Sales (``checkout``) (E006); what they declare is checked by ``live.checks_hooks``
(E009–E016, E018 and E028).

``settings.LIVE["session_events"]``, the events after which every
live stream of the channel re-reads its context, is a list of events that some ``events.py`` declares (E019).

Every operation tells the assistant what it is — a tool, ``ai=AI(description=…,
risk=…)``, or not one, ``ai=INTERNAL`` — never by omission, with a risk of ``RISKS``; a ``dict`` with its
``description`` is still accepted (E017). Like the metadata checks, it looks at every registered operation.

Every tool of the apps a project lists in
``LIVE_ASSISTANT_ASKS_REQUIRED`` says what a person would type to ask for it (``AI.asks``) in English and Spanish, at
least two distinct phrases each, none its own name nor longer than ``MAX_ASK_CHARS`` (E020). An app is listed once all
of its tools say them, so the apps take it on one at a time.

An app's ``services`` or ``queries`` may be a package; importing a module of it is what registers its operations, so
every module of the package is imported at startup, by the package's ``__init__.py`` (E021; test modules and
sub-packages are not operation modules). No module of the package is named ``services`` or ``queries``: an operation
in it would pass for one of an app's ``services.py`` or ``queries.py`` (E022).
"""

import pkgutil
import re
import sys
from collections.abc import Mapping
from typing import Any

from django.apps import apps
from django.conf import settings
from django.core import checks
from django.utils import translation

from live import operations
from live.assistant import tool_name
from live.checks_hooks import _hook_errors
from live.meta import (
    Category,
    LiveAppConfig,
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
    "checkout",
)
# The columns of shared.app they are written to.
SUMMARY_MAX_LENGTH = 120
NAME_MAX_LENGTH = 80
# A vertical id names a template database, hub_template_<vertical>, so it is a snake_case name
# (no "__") and fits in Postgres' 63 characters with that prefix; "test" is the tests' template.
VERTICAL_RE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")
VERTICAL_MAX_LENGTH = 63 - len("hub_template_")
RESERVED_VERTICALS = frozenset({"test"})


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
def check_ai_declared(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """E017: every registered operation declares ``ai=``: ``AI(...)``, ``INTERNAL`` or a ``dict`` with its
    ``description``, and a risk, when it says one, of ``RISKS``."""
    hint = (
        "Declare ai=AI(description=…, risk='normal'|'high') for an assistant tool (its description tells the model, in "
        "English, what it does; 'high' asks to type a word before it runs), or ai=INTERNAL for what is not one."
    )
    return [
        checks.Error(f"Operation {name!r} {problem}.", hint=hint, obj=name, id="live.E017")
        for name, op in sorted(operations.registry.items())
        if (problem := _ai_problem(op.ai)) is not None
    ]


def _ai_problem(declared: Any) -> str | None:
    """Why ``declared`` (an operation's ``ai=``) tells the assistant nothing, or ``None``."""
    if declared is None:
        return "declares no ai="
    if isinstance(declared, operations.Internal):
        return None
    if isinstance(declared, operations.AI):
        description, risk = declared.description, declared.risk
    elif isinstance(declared, dict):
        description, risk = declared.get("description"), declared.get("risk", "normal")
    else:
        return f"declares ai={declared!r}, which is neither AI(...), INTERNAL nor a dict"
    if not isinstance(description, str) or not description.strip():
        return "declares an assistant tool without a description"
    if risk not in operations.RISKS:
        return f"declares risk {risk!r}; it must be one of {', '.join(operations.RISKS)}"
    return None


@checks.register("live")
def check_assistant_asks(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """E020: every tool (``AI``, never ``INTERNAL``) of an app of ``LIVE_ASSISTANT_ASKS_REQUIRED`` says its asks in
    each language of ``ASK_LANGUAGES``: at least ``MIN_ASKS`` distinct phrases, none empty, its own name (the
    operation's or the tool's) nor longer than ``MAX_ASK_CHARS``; the setting is a tuple of labels that have
    operations."""
    hint = (
        "Declare in ai=AI(..., asks={'en': (...), 'es': (...)}) what a person would type to the chat to ask for this "
        "tool: natural and ambiguous, as people say it («créame un producto», «what did I sell today?»), never its "
        "name. LIVE_ASSISTANT_ASKS_REQUIRED lists the apps whose tools all say them."
    )
    listed = getattr(settings, "LIVE_ASSISTANT_ASKS_REQUIRED", ())
    if not isinstance(listed, list | tuple) or not all(isinstance(label, str) for label in listed):
        message = f"LIVE_ASSISTANT_ASKS_REQUIRED is {listed!r}; it must be a tuple of app labels."
        return [checks.Error(message, hint=hint, id="live.E020")]
    labels = {op.app_label for op in operations.registry.values()}
    errors = [
        checks.Error(
            f"LIVE_ASSISTANT_ASKS_REQUIRED names {label!r}, which has no operation.", hint=hint, id="live.E020"
        )
        for label in listed
        if label not in labels
    ]
    for name, op in sorted(operations.registry.items()):
        if op.app_label in listed and isinstance(op.ai_spec(), operations.AI):
            errors += [
                checks.Error(f"Operation {name!r} {problem}.", hint=hint, obj=name, id="live.E020")
                for problem in _asks_problems(op)
            ]
    return errors


def _asks_problems(op: operations.Operation) -> list[str]:  # noqa: C901
    """Why ``op``'s asks (its ``ai=``'s, as declared) do not tell what a person would type to ask for it."""
    declared = op.ai
    asks = declared.asks if isinstance(declared, operations.AI) else declared.get("asks")
    if not asks:
        return ["declares no asks"]
    if not isinstance(asks, Mapping):
        return [f"declares asks={asks!r}, which is not a mapping of language → phrases"]
    names = {op.name.casefold(), tool_name(op.name).casefold()}
    problems: list[str] = []
    for language in operations.ASK_LANGUAGES:
        phrases = asks.get(language)
        if phrases is None:
            problems.append(f"has no asks in {language!r}")
            continue
        if not isinstance(phrases, list | tuple):
            problems.append(f"asks[{language!r}] must be a tuple of phrases, not {type(phrases).__name__}")
            continue
        distinct = set()
        for phrase in phrases:
            if not isinstance(phrase, str):
                problems.append(f"asks[{language!r}] has {phrase!r}, which is not a phrase")
                continue
            said = " ".join(phrase.split()).casefold()
            if not said:
                problems.append(f"has an empty ask in {language!r}")
                continue
            distinct.add(said)
            if said in names:
                problems.append(
                    f"has an ask in {language!r} that is its own name ({op.name!r}): a person never types it"
                )
            if len(phrase.strip()) > operations.MAX_ASK_CHARS:
                limit = operations.MAX_ASK_CHARS
                problems.append(f"has an ask in {language!r} longer than {limit} characters: {phrase[:40]!r}…")
        if len(distinct) < operations.MIN_ASKS:
            counted = f"{len(distinct)} distinct {'ask' if len(distinct) == 1 else 'asks'}"
            problems.append(f"has {counted} in {language!r}; it needs at least {operations.MIN_ASKS}")
    return problems


@checks.register("live")
def check_door_packages(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """E021 and E022: the modules of an app's services or queries package."""
    errors: list[checks.CheckMessage] = []
    for config in apps.get_app_configs():
        for package in _door_packages(config):
            errors += _door_package_errors(config, package)
    return errors


def _door_packages(config: Any) -> list[Any]:
    found = (sys.modules.get(f"{config.name}.{door}") for door in operations.DOORS.values())
    return [module for module in found if module is not None and hasattr(module, "__path__")]


def _door_package_errors(config: Any, package: Any) -> list[checks.CheckMessage]:
    errors = []
    for info in pkgutil.iter_modules(package.__path__):
        module = f"{package.__name__}.{info.name}"
        if info.name in operations.DOORS.values():
            errors.append(
                checks.Error(
                    f"{module} is named like an app's {info.name}: an operation in it passes for one of {info.name}.py.",
                    hint="Name the module after the entity or use case it covers.",
                    obj=config,
                    id="live.E022",
                )
            )
        elif _declares_operations(info) and module not in sys.modules:
            errors.append(
                checks.Error(
                    f"{module} is never imported, so the operations it declares are not registered.",
                    hint=f"Import it in the __init__.py of {package.__name__}: from . import {info.name}",
                    obj=config,
                    id="live.E021",
                )
            )
    return errors


def _declares_operations(info: pkgutil.ModuleInfo) -> bool:
    """Whether a module of a package may declare operations: not a test module, nor a sub-package (@operation rejects
    an operation one level deeper)."""
    name = info.name
    return not (info.ispkg or name.startswith("test_") or name.endswith("_test") or name == "conftest")


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
