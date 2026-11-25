"""What a card knows of each datum a write takes: its name, and whether it is money, a choice, a secret or a record."""

import uuid
from functools import cache
from typing import Any

from django.conf import settings
from django.core.exceptions import FieldDoesNotExist
from django.utils import translation
from django.utils.text import capfirst
from django.utils.translation import gettext

from live.assistant.tools import (
    config_of,
)
from live.operations import Operation


def resolved(prop: dict, defs: dict) -> dict:
    """``prop`` with the first branch of its union that is not ``null`` and the schema its ``$ref`` names."""
    for branch in prop.get("anyOf", []):
        if branch.get("type") != "null":
            return resolved({**branch, **{k: v for k, v in prop.items() if k != "anyOf"}}, defs)
    ref = prop.get("$ref")
    return {**defs.get(ref.rsplit("/", 1)[-1], {}), **prop} if ref else prop


#: The mark of an amount (``json_schema_extra={"money": True}``, on a whole number): in the minor unit of the currency
#: it is in — 1250 is 12.50 €, ¥1,250 has no cents. The card paints it as money and the model is told so by its tool,
#: whatever its description says: the words are for the model, the mark is the platform's.
MONEY = "money"


def is_money(prop: dict) -> bool:
    """Whether the schema ``prop`` declares an amount: its mark (``MONEY``), and only that — neither the datum's name
    (a ``…_cents`` without the mark is no amount), which it is not even given, nor a description's words."""
    return prop.get(MONEY) is True


def is_signed(prop: dict) -> bool:
    """Whether the schema declares the datum signed (``json_schema_extra={"signed": True}``): an amount (``MONEY``) that
    says over or short, as a cash count's difference, which the card writes with its sign («+» over)."""
    return prop.get("signed") is True


def sends_amount(value: Any, prop: dict, defs: dict, *, depth: int = 0) -> bool:
    """Whether ``value`` carries an amount (``MONEY``) as its schema ``prop`` declares it, at any depth."""
    prop = fitting(value, prop, defs)
    if depth > 8:  # a schema that names itself
        return False
    if isinstance(value, int) and not isinstance(value, bool):
        return is_money(prop)
    if isinstance(value, dict):
        props = prop.get("properties", {})
        return any(sends_amount(inner, props.get(key, {}), defs, depth=depth + 1) for key, inner in value.items())
    if isinstance(value, list):
        items = prop.get("items")
        items = items if isinstance(items, dict) else {}
        return any(sends_amount(item, items, defs, depth=depth + 1) for item in value)
    return False


def generated_title(name: str) -> str:
    """The title pydantic makes up for a field without one (``closing_balance`` → «Closing Balance»)."""
    return name.title().replace("_", " ").strip()


def _in_code_language() -> bool:
    """Whether the active language is the one the code's texts are written in (and fall back to): English."""
    return (translation.get_language() or settings.LANGUAGE_CODE).split("-")[0] == settings.LANGUAGE_CODE.split("-")[0]


@cache
def model_fields(app_label: str, entity: str, name: str) -> tuple:
    """The fields ``name`` of the models of the app ``app_label``, the model of the operation's ``entity`` first —
    another may mean something else by it. Their metadata only: no query."""
    config = config_of(app_label)
    if config is None:
        return ()
    own = entity.replace("_", "")
    found = []
    for model in sorted(config.get_models(), key=lambda model: not model._meta.model_name.endswith(own)):
        try:
            found.append(model._meta.get_field(name))
        except FieldDoesNotExist:
            continue
    return tuple(found)


def verbose_name(app_label: str, entity: str, name: str) -> Any:
    """The name the models of the app ``app_label`` give their field ``name`` (lazy: said in the active language), or
    ``None``."""
    named_ = (getattr(field, "verbose_name", None) for field in model_fields(app_label, entity, name))
    return next((verbose for verbose in named_ if verbose), None)


def choice_label(app_label: str, entity: str, name: str, value: Any) -> Any:
    """The label the models of the app ``app_label`` give the value ``value`` of their field ``name`` — its
    ``choices``, the ones its screens show (lazy: said in the active language) —, else the one the app declares for a
    closed list no field holds (``LiveAppConfig.choices``), or ``None``."""
    for field_ in model_fields(app_label, entity, name):
        labels = dict(getattr(field_, "flatchoices", None) or ())
        if value in labels:
            return labels[value]
    config = config_of(app_label)
    return dict(config.choices.get(name, ())).get(value) if config is not None else None


#: The mark of a datum whose values are those of a field of the models under another name
#: (``json_schema_extra={"choices_of": "<field>"}``, a field of its own app, or ``"<app>.<field>"``, one of an app it
#: requires): the card names each value by that field's ``choices`` (``choice_label``), the ones its screens show.
CHOICES_OF = "choices_of"


def choices_of(app_label: str, name: str, prop: dict) -> tuple[str, str]:
    """The app and the field of its models whose ``choices`` name the values of the datum ``name`` of an operation of
    ``app_label``: the ones its schema ``prop`` marks (``CHOICES_OF``), else its own name in its own app."""
    declared = prop.get(CHOICES_OF)
    if not isinstance(declared, str) or not declared:
        return app_label, name
    app, _, field_name = declared.rpartition(".")
    return app or app_label, field_name


def own_title(name: str, title: str | None) -> str | None:
    """The title the schema gives the datum ``name`` itself — not the one pydantic makes up from its name —, in the
    active language: as a catalog translates it, or as written when the person reads the code's language; else
    ``None`` (one nobody translated never reaches a Spanish card)."""
    if title and title != generated_title(name):
        translated = gettext(title)
        if translated != title or _in_code_language():
            return translated
    return None


def label(op: Operation, name: str, title: str | None) -> str:
    """How the card names the datum ``name``, in the active language and never by a technical name: by the title its
    schema gives it (``own_title``); else by the name its app's models give that field, the one its screens show; else
    by its title, through the catalogs. One way for every app: nothing to list here by hand."""
    own = own_title(name, title)
    if own is not None:
        return own
    verbose = verbose_name(op.app_label, op.name.split(".")[1], name)
    if verbose is not None:
        return capfirst(str(verbose))
    return gettext(title or generated_title(name))


#: What a card shows of a secret instead of its value: the same in every language.
HIDDEN = "••••••••"


def _is_secret(prop: dict) -> bool:
    """Whether the schema declares the datum secret: a password, a certificate, a key (pydantic's ``SecretStr``:
    ``format: password``, ``writeOnly``)."""
    return prop.get("format") == "password" or prop.get("writeOnly") is True


def hidden(value: Any, prop: dict, defs: dict) -> Any:
    """``value`` with each secret its schema ``prop`` declares, at any depth, as ``HIDDEN``; an empty one hides
    nothing. A card never carries a secret as typed: neither on the screen nor in what the browser receives."""
    if value is None or value == "":
        return value
    ref = prop.get("$ref")
    if ref:
        prop = {**defs.get(ref.rsplit("/", 1)[-1], {}), **{key: inner for key, inner in prop.items() if key != "$ref"}}
    if _is_secret(prop):
        return HIDDEN
    # Each branch of a union hides its own: what any of them declares secret is hidden.
    for branch in [*prop.get("anyOf", []), *prop.get("oneOf", []), *prop.get("allOf", [])]:
        value = hidden(value, branch, defs)
    if isinstance(value, dict):
        props = prop.get("properties", {})
        extra = prop.get("additionalProperties")
        extra = extra if isinstance(extra, dict) else {}
        return {key: hidden(inner, props.get(key, extra), defs) for key, inner in value.items()}
    if isinstance(value, list):
        items, prefix = prop.get("items"), prop.get("prefixItems", [])
        items = items if isinstance(items, dict) else {}
        return [hidden(item, prefix[i] if i < len(prefix) else items, defs) for i, item in enumerate(value)]
    return value


#: The mark of a datum that names a record (``json_schema_extra={"refers": {"read": "<a query>", "by": "<its input>",
#: "name": "<the datum of its answer that names it>"}}``): the project's words name it (``Words.reference``). A datum
#: the schema says is an id (``format: uuid``) is a record too: a card never shows it by its id.
REFERS = "refers"

#: The moments a schema declares (``format``), said as the person's language writes them (``Words.moment``).
MOMENTS = ("date-time", "date", "time")

#: The mark of a key of the caller's attempt (``json_schema_extra={"attempt_key": True}``, on a text): an idempotency
#: key, born once and the same on every retry so a retry never charges, sends or prints twice. Nobody can judge it:
#: the card and its preview leave it out, at any depth; the write gets it as sent.
ATTEMPT_KEY = "attempt_key"


def is_attempt_key(prop: dict) -> bool:
    return prop.get(ATTEMPT_KEY) is True


def refers_of(prop: dict) -> dict | None:
    """The read the schema ``prop`` marks to name its record (``REFERS``), or ``None``."""
    declared = prop.get(REFERS)
    return declared if isinstance(declared, dict) else None


def is_uuid(value: Any) -> bool:
    """Whether ``value`` is an id as a schema's ``format: uuid`` takes it."""
    try:
        uuid.UUID(value)
    except (TypeError, ValueError, AttributeError):
        return False
    return True


#: The mark of a text of an object that names, as a person says it, the record another datum of that object names by
#: its id, when the id is not known (``json_schema_extra={"name_of": "<that datum>"}``: a booking's service, «Tinte»,
#: beside ``service_id``). It is a name, never a code: a line that carries it is said by it. Beside its
#: record the write takes the id and ignores the name, so the card says the record and leaves the name out. A text
#: with neither it nor ``OWN_WORDS`` is sent as it is and never said one by one (a code nobody names), and so are
#: blanks or an id written where the name goes (``_is_said_name``). It marks a text of an object a write sends (a
#: line of a list); on a write's own data it does nothing: each of them shows under its own label.
NAME_OF = "name_of"


def _is_record(value: Any, prop: dict) -> bool:
    """Whether ``value`` names a record as its schema ``prop`` (the branch it fits, ``fitting``) declares it: marked
    ``REFERS``, or an id."""
    return REFERS in prop or (prop.get("format") == "uuid" and is_uuid(value))


def _name_of(prop: dict, defs: dict) -> str | None:
    """The datum whose record the text its schema ``prop`` declares names as a person says it (``NAME_OF``), or
    ``None``."""
    of = _referred(prop, defs).get(NAME_OF)
    return of if isinstance(of, str) else None


def _is_said_name(text: Any) -> bool:
    """Whether ``text``, a datum marked ``NAME_OF`` or ``OWN_WORDS``, is what a person said, judged by what it says: a
    text with more than blanks (blanks show nothing, as an empty name does) and no id (a card never says one), even
    padded."""
    words = text.strip() if isinstance(text, str) else ""
    return words != "" and not is_uuid(words)


def _name_beside_its_record(key: str, value: dict, props: dict, defs: dict) -> bool:
    """Whether the datum ``key`` of the object ``value`` is a name a person said (``NAME_OF``) of a record the object
    carries itself: not empty, of a datum its schema ``props`` declares a record (``_is_record``)."""
    of = _name_of(props.get(key, {}), defs)
    record = value.get(of) if of in props else None
    return record is not None and record != "" and _is_record(record, fitting(record, props[of], defs))


#: What a card leaves out: a record it cannot name, an attempt key.
LEFT_OUT = object()

#: The mark of a text that is the person's own words (``json_schema_extra={"own_words": True}``): an option of a select
#: field, the value of a custom field, what an invoice line bills, the name of a special day. The card says it as it
#: was written, so a list of them, or of lines that carry it, is said one by one (``NAMED``); blanks or an id say
#: nothing (``_is_said_name``). It marks a text of a list or of its lines; on a write's own data it does nothing: each
#: of them shows under its own label.
OWN_WORDS = "own_words"

#: The mark of a datum of a card that is a list whose every item ``said`` put in words — a record by its name (or left
#: out, none), a moment, a value of a closed list by its label, an amount, the name a person said of a record, the
#: person's own words, or a line of them and figures —, never one as sent: the screen says its items one after another,
#: a line by its words and then its figures («Vino tinto · 6», «12:00 · 23:30»). A list without it says how many it
#: carries: texts sent as they are (codes nobody names), a line with one of them, a yes or no or a list inside, or a
#: record the card leaves out beside what it says.
NAMED = "named"


#: The type of a value each JSON Schema type names.
_TYPES = {"object": dict, "array": list, "string": str, "integer": int, "number": int | float, "boolean": bool}


def _fits(value: Any, branch: dict) -> bool:
    """Whether ``value`` has the shape of ``branch``: its type and, an object, no key it does not take and its
    constants (a discriminator, as an automation's trigger ``kind``)."""
    expected = _TYPES.get(branch.get("type", ""))
    if expected is not None and not isinstance(value, expected):
        return False
    if not isinstance(value, dict):
        return True
    props = branch.get("properties", {})
    if branch.get("additionalProperties") is False and not set(value) <= set(props):
        return False
    return all(value[key] == inner["const"] for key, inner in props.items() if key in value and "const" in inner)


def _referred(prop: dict, defs: dict) -> dict:
    """``prop`` with the schema its ``$ref`` names, what it says itself on top."""
    ref = prop.get("$ref")
    if not ref:
        return prop
    return {**defs.get(ref.rsplit("/", 1)[-1], {}), **{key: inner for key, inner in prop.items() if key != "$ref"}}


def fitting(value: Any, prop: dict, defs: dict, depth: int = 0) -> dict:
    """The schema of ``value`` among the branches of the union ``prop`` declares (``anyOf``, ``oneOf``, one inside
    another as an optional automation's trigger): the first one it fits (``_fits``), with what ``prop`` itself says
    (its title, its marks); ``prop`` resolved when it is no union."""
    prop = _referred(prop, defs)
    branches = [*prop.get("anyOf", []), *prop.get("oneOf", [])]
    if not branches or depth > 8:
        return resolved(prop, defs)
    outer = {key: inner for key, inner in prop.items() if key not in ("anyOf", "oneOf", "discriminator")}
    for branch in branches:
        branch = _referred(branch, defs)
        if branch.get("type") != "null" and _fits(value, branch):
            return fitting(value, {**branch, **outer}, defs, depth + 1)
    return resolved(prop, defs)
