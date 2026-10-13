"""System checks of the app metadata (tag ``live``; round 15, PLAN §20).

A module (``kind = "app"``) carries what the Hub's apps page shows next to its name (``icon``,
``category``) and only requires other modules, without cycles. A platform app (``kind =
"platform"``) is always on, so the module fields mean nothing for it. The metadata is one graph:
the checks always look at every app of ours, whatever ``app_configs`` ``manage.py check`` passes.
Registered when ``live`` is ready (``LiveConfig.ready`` imports this module).
"""

from typing import Any

from django.core import checks

from live.meta import Category, all_live_app_configs

KINDS = ("platform", "app")
# Fields that only a module may declare; a platform app leaves them at their defaults.
MODULE_ONLY_FIELDS = ("requires", "category", "premium", "navigation")


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
    return errors


def _platform_errors(config: Any) -> list[checks.CheckMessage]:
    declared = [field for field in MODULE_ONLY_FIELDS if getattr(config, field)]
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
