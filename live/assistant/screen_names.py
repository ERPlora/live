"""What the model reads of a value of a closed list in a tool's result: beside its code, the name its screens give it.

The model never sees a result's schema and repeats a code as it reads it: it wrote «lead» and «walk_in» for what a
customer's card calls «Contacto» and «En el local». A result that holds such values carries, once, the name of each
one in the person's language under the path of its datum (``SCREEN_NAMES``: ``{"rows.lifecycle_stage": {"lead":
"Contacto"}}``), so a list of a hundred rows names each value once. The name is the one the card of a write says
(``choice_label``): the label the app's models give the value — its field's ``choices``, else the closed list the app
declares — of the field a ``choices_of`` mark names, else of the datum's own name. A name that only changes the case of
its code says nothing more and is left out.
"""

from dataclasses import dataclass, field
from typing import Any

from django.utils import translation

from live.assistant.fields import CHOICES_OF, choice_label, choices_of, fitting, is_money
from live.assistant.tools import output_schema
from live.operations import Operation

#: Where a result carries the name of each value its screens name, by the path of its datum.
SCREEN_NAMES = "screen_names"


def screen_name(op: Operation, datum: str, mark: str | None, value: Any) -> str | None:
    """The name the screens give ``value`` of the datum ``datum`` of ``op``'s result (of the field ``mark`` names), in
    the active language, or ``None``."""
    app_label, field_name = choices_of(op.app_label, datum, {CHOICES_OF: mark} if mark else {})
    label = choice_label(app_label, op.name.split(".")[1], field_name, value)
    return None if label is None else str(label)


def screen_names(op: Operation, written: dict, language: str) -> dict[str, dict[str, str]]:
    """The names, in ``language``, of the values of ``written`` (``op``'s result in JSON) its screens name: by the path
    of their datum (its names from the top, joined by dots, a list's items under the list's), then by their code."""
    schema = output_schema(op)
    gathered = _Gathered(op, schema.get("$defs", {}))
    with translation.override(language):
        gathered.take(written, schema, "", None)
    named = {path: {code: name for code, name in names.items() if name is not None} for path, names in gathered.found.items()}
    return {path: names for path, names in named.items() if names}


@dataclass
class _Gathered:
    """The name of each code of ``op``'s result, by the path of its datum and then by the code (``None``: its screens
    name it nothing more than its code)."""

    op: Operation
    defs: dict
    found: dict[str, dict[str, str | None]] = field(default_factory=dict)

    def take(self, value: Any, prop: dict, path: str, mark: str | None) -> None:
        """Each code inside ``value``, whose schema is ``prop``, at ``path``; ``mark``: the ``choices_of`` mark that names
        its field, a list's for its items too."""
        prop = fitting(value, prop, self.defs)
        mark = prop.get(CHOICES_OF, mark)
        if isinstance(value, dict):
            props = prop.get("properties", {})
            for key, inner in value.items():
                self.take(inner, props.get(key, {}), f"{path}.{key}" if path else key, None)
        elif isinstance(value, list):
            items = prop.get("items")
            for item in value:
                self.take(item, items if isinstance(items, dict) else {}, path, mark)
        elif _is_code(value, prop):
            self.name(value, path, mark)

    def name(self, value: Any, path: str, mark: str | None) -> None:
        named = self.found.setdefault(path, {})
        code = str(value)
        if code not in named:
            name = screen_name(self.op, path.rpartition(".")[2], mark, value)
            named[code] = name if name is not None and name.casefold() != code.casefold() else None


def _is_code(value: Any, prop: dict) -> bool:
    """Whether ``value`` may be a code its screens name: a text or a whole number, never a moment, an id or an amount."""
    if isinstance(value, bool) or "format" in prop or is_money(prop):
        return False
    return (isinstance(value, str) and value != "") or isinstance(value, int)
