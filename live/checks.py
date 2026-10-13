"""System checks of the app metadata (tag ``live``; round 15, PLAN §20).

A module (``kind = "app"``) carries what the Hub's apps page shows next to its name (``icon``,
``category``) and only requires other modules, without cycles. A platform app (``kind =
"platform"``) is always on, so the module fields mean nothing for it. The metadata is one graph:
the checks always look at every app of ours, whatever ``app_configs`` ``manage.py check`` passes.
Registered when ``live`` is ready (``LiveConfig.ready`` imports this module).

Round 16 (PLAN §21): a module also carries what the public store shows (``summary``,
``description``, E007) and the verticals it belongs to (``verticals``, E008). What needs to read
files (WORKBOOK, translations, baked icons, images) is not a check: ``register_apps`` validates it.
"""

import re
from typing import Any

from django.core import checks
from django.utils import translation

from live.meta import Category, LiveAppConfig, all_live_app_configs

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
)
# The columns of shared.app they are written to (round 16, spec §3.1).
SUMMARY_MAX_LENGTH = 120
NAME_MAX_LENGTH = 80
# A vertical id names a template database, hub_template_<vertical>, so it has the shape of PLAN §15.2
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
            errors += _module_errors(config)
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
