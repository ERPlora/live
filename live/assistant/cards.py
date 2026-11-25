"""The card of a write: what it will send, said in words, and whether the person's yes lets it run."""

import datetime as dt
import re
from dataclasses import dataclass
from typing import Any, Protocol

from django.utils import formats, translation

from live.assistant.fields import (
    CHOICES_OF,
    LEFT_OUT,
    MOMENTS,
    NAMED,
    OWN_WORDS,
    _is_record,
    _is_said_name,
    _name_beside_its_record,
    _name_of,
    _referred,
    choice_label,
    choices_of,
    fitting,
    hidden,
    is_attempt_key,
    is_money,
    is_signed,
    label,
    own_title,
    resolved,
)
from live.assistant.tools import (
    CONFIRM_WORD,
    config_of,
    input_schema,
    risk,
)
from live.context import OperationContext
from live.operations import Operation


# ── The card of a write ──────────────────────────────────────────────────────────────────────────────────────────


class Words(Protocol):
    """How a project says a card's data in words, for the person (``language``) and the write (``op``) of the card.

    ``within`` gives the words of the data of an object it sends (the Hub: in the currency that object names);
    ``money`` the currency of the card's top-level amounts as its screen takes it (``{"currency", "decimals"}``, or
    ``None`` for the project's own); ``amount`` an amount nested in an object or a list; ``priced`` false when the
    amounts are to go as sent (a currency that is none); ``moment`` a moment (``MOMENTS``) or ``None`` when it is
    none; ``reference`` the name of the record a datum names, or ``LEFT_OUT``; ``app_name`` where the write happens,
    as the person knows it."""

    op: Operation
    language: str
    priced: bool

    def within(self, value: Any, props: dict, defs: dict) -> Words: ...

    def money(self) -> dict | None: ...

    def amount(self, value: int) -> Any: ...

    def moment(self, value: str, kind: str) -> str | None: ...

    def reference(self, value: Any, prop: dict) -> Any: ...

    def app_name(self) -> str: ...


#: How JSON writes a moment of each kind its schema declares (``MOMENTS``).
_MOMENT_OF = {"date": dt.date.fromisoformat, "time": dt.time.fromisoformat, "date-time": dt.datetime.fromisoformat}


def _moment(value: Any, kind: str) -> dt.date | dt.time | dt.datetime | None:
    """The moment of its schema's ``kind`` that ``value`` writes as JSON does, or ``None`` when it writes none."""
    try:
        return _MOMENT_OF.get(kind, dt.datetime.fromisoformat)(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class PlainWords:
    """Words that read nothing: amounts in ``currency`` with ``decimals`` (euros with two by default), a moment at UTC as
    Django's formats of the active language write it, a record left out (no read to name it) and the app by its
    name."""

    op: Operation
    language: str
    currency: str = "EUR"
    decimals: int = 2
    priced: bool = True

    def within(self, value: Any, props: dict, defs: dict) -> PlainWords:
        return self

    def money(self) -> dict | None:
        return {"currency": self.currency, "decimals": self.decimals}

    def amount(self, value: int) -> Any:
        return {"kind": "money", "value": value, "money": self.money()}

    def moment(self, value: str, kind: str) -> str | None:
        moment = _moment(value, kind)
        if moment is None:
            return None
        if kind == "date":
            return formats.date_format(moment, "DATE_FORMAT")
        if kind == "time":
            return formats.time_format(moment.replace(tzinfo=None), "TIME_FORMAT")
        if moment.tzinfo is not None:
            moment = moment.astimezone(dt.UTC).replace(tzinfo=None)
        return formats.date_format(moment, "DATETIME_FORMAT")

    def reference(self, value: Any, prop: dict) -> Any:
        return LEFT_OUT

    def app_name(self) -> str:
        config = config_of(self.op.app_label)
        return str(config.verbose_name) if config is not None else self.op.app_label

    @classmethod
    def of_answer(cls, read: Operation, ctx: OperationContext, answer: dict) -> PlainWords:
        """The words of a preview's read: in the currency it answers (``currency``, ``currency_decimals``), else euros."""
        currency = answer.get("currency")
        decimals = answer.get("currency_decimals")
        return cls(
            read,
            ctx.language,
            currency if isinstance(currency, str) and currency else cls.currency,
            decimals if isinstance(decimals, int) and not isinstance(decimals, bool) else cls.decimals,
        )


def said(value: Any, prop: dict, defs: dict, name: str, words: Words, inner: bool = False) -> Any:  # noqa: PLR0911, PLR0913, PLR0917
    """``value`` in words as its schema ``prop`` declares it, at any depth: a moment as the person's language writes it
    (``Words.moment``), a value of a closed list by the label its app's models give it (``choice_label``; of the field
    its schema marks, ``CHOICES_OF``), a record by
    its name (``Words.reference``) or else ``LEFT_OUT`` — left out of an object, none in a list (which still says how
    many it carries), as an attempt key (``ATTEMPT_KEY``) is, even empty, and as the name a person said beside the
    record it names (``NAME_OF``) is; an amount (``MONEY``) inside an object or a list as the screen writes one on top
    (``Words.amount``), in the words of the object it is in (``Words.within``); what is none of them, or not what its
    schema declares (the write refuses it), as sent."""
    prop = fitting(value, prop, defs)
    if is_attempt_key(prop):
        return LEFT_OUT
    if value is None or value == "":
        return value
    if inner and is_money(prop) and isinstance(value, int) and not isinstance(value, bool):
        return words.amount(value)
    if _is_record(value, prop):
        return words.reference(value, prop)
    if prop.get("format") in MOMENTS and isinstance(value, str):
        spoken = words.moment(value, prop["format"])
        return value if spoken is None else spoken
    if "enum" in prop and isinstance(value, str | int) and not isinstance(value, bool):
        app_label, field_name = choices_of(words.op.app_label, name, prop)
        choice = choice_label(app_label, words.op.name.split(".")[1], field_name, value)
        return value if choice is None else str(choice)
    if isinstance(value, dict):
        props = prop.get("properties", {})
        extra = prop.get("additionalProperties")
        extra = extra if isinstance(extra, dict) else {}
        own = words.within(value, props, defs)
        spoken_items = {
            key: LEFT_OUT
            if _name_beside_its_record(key, value, props, defs)
            else said(item, props.get(key, extra), defs, key if key in props else name, own, inner=True)
            for key, item in value.items()
        }
        return {key: item for key, item in spoken_items.items() if item is not LEFT_OUT}
    if isinstance(value, list):
        items, prefix = prop.get("items"), prop.get("prefixItems", [])
        items = items if isinstance(items, dict) else {}
        if CHOICES_OF in prop:  # a list's mark names the values of its items, as its name does
            items, prefix = {CHOICES_OF: prop[CHOICES_OF], **items}, [{CHOICES_OF: prop[CHOICES_OF], **p} for p in prefix]
        spoken_list = [
            said(item, prefix[i] if i < len(prefix) else items, defs, name, words, inner=True) for i, item in enumerate(value)
        ]
        return [None if item is LEFT_OUT else item for item in spoken_list]
    return value


#: A figure as JSON and the text of a decimal write one («6», «-1.250»): never an exponent, a blank or a word.
_FIGURE = re.compile(r"-?\d+(?:\.\d+)?")


def _is_figure(value: Any, prop: dict, defs: dict) -> bool:
    """Whether ``value`` is a figure its schema ``prop`` takes: a number (a quantity, sessions, an amount) or the text
    of one where its schema takes a number too (a decimal, which Pydantic declares a number or a text) — never a yes
    or no, nor a text whose schema takes no number, though it reads as one."""
    prop = _referred(prop, defs)
    branches = [_referred(branch, defs) for branch in (*prop.get("anyOf", []), *prop.get("oneOf", []))] or [prop]
    if isinstance(value, bool) or not any(branch.get("type") in ("integer", "number") for branch in branches):
        return False
    return isinstance(value, int | float) or (isinstance(value, str) and _FIGURE.fullmatch(value) is not None)


def _is_empty(value: Any) -> bool:
    """Whether a datum of a line shows nothing: none, an empty text or an empty list (the hours of a closed day)."""
    return value is None or value == "" or value == []


def _figure_beside_words(value: Any, prop: dict, defs: dict) -> bool:
    """Whether ``value`` is a figure of its line (``_is_figure``: a quantity, sessions, an amount), not a record by its
    number nor a value of a closed list, which are said by their names."""
    fitted = fitting(value, prop, defs)
    return not _is_record(value, fitted) and "enum" not in fitted and _is_figure(value, prop, defs)


def _line_in_words(line: dict, spoken: dict, prop: dict, defs: dict) -> bool:
    """Whether ``said`` put the line ``line`` of a list in words (``spoken``): each datum it carries in words
    (``_in_words``) or a figure beside them (``_figure_beside_words``), one at least in words; and, when the card
    leaves out a record of it, all of it is left out — the screen counts it among the more, never by what is beside
    a record it cannot name (a bare quantity, a field's value without its field). An empty datum (``_is_empty``) does
    not show, so it does not count; nor does a name beside its record, which the card leaves out."""
    props = prop.get("properties", {})
    carried = {
        key: item
        for key, item in line.items()
        if not _is_empty(item) and not _name_beside_its_record(key, line, props, defs)
    }
    if not set(carried) <= set(props):
        return False
    words = {key: item for key, item in carried.items() if not _figure_beside_words(item, props[key], defs)}
    shown = set(carried) & set(spoken)
    return (
        bool(words)
        and shown in (set(), set(carried))
        and all(_in_words(item, spoken.get(key), props[key], defs) for key, item in words.items())
    )


def _in_words(value: Any, spoken: Any, prop: dict, defs: dict) -> bool:
    """Whether ``said`` put the item ``value`` of a list in words (``spoken``) as its schema ``prop`` declares it — a
    record (``REFERS`` or an id), a moment, a value of a closed list, an amount, the name a person said of a record
    (``NAME_OF``: ``[{"service": "Tinte"}]``), the person's own words (``OWN_WORDS``: a select field's options), or a
    line of them and figures beside them (``_line_in_words``: a booking's services, ``[{"service_id": …}]``, a
    reception's products and quantities) —, not as sent (``NAMED``)."""
    prop = fitting(value, prop, defs)
    if _is_record(value, prop):
        return True
    if _name_of(prop, defs) is not None or prop.get(OWN_WORDS) is True:
        return _is_said_name(value)
    if isinstance(value, dict):
        return _line_in_words(value, spoken if isinstance(spoken, dict) else {}, prop, defs)
    if prop.get("format") in MOMENTS:  # its words may write it as it was sent: «12:00» in Spanish
        return spoken != value or _moment(value, prop["format"]) is not None
    return ("enum" in prop or is_money(prop)) and spoken != value


def _said_in_words(value: list, spoken: list, prop: dict, defs: dict) -> bool:
    """Whether ``said`` put every item of the list ``value`` in words (``spoken``, item by item)."""
    prop = fitting(value, prop, defs)
    items, prefix = prop.get("items"), prop.get("prefixItems", [])
    items = items if isinstance(items, dict) else {}
    return all(
        _in_words(item, said_item, prefix[i] if i < len(prefix) else items, defs)
        for i, (item, said_item) in enumerate(zip(value, spoken, strict=True))
    )


def field(  # noqa: C901, PLR0913, PLR0917
    name: str, label: str, prop: dict, defs: dict, value: Any, money: dict | None = None, words: Words | None = None
) -> dict | None:
    """One datum of a card, as its schema ``prop`` declares it: a secret hidden (``hidden``) and, with the ``words``
    of its card, the rest in words (``said``); ``None`` when it names a record the card cannot name or is an attempt
    key. An amount carries ``signed`` when its schema declares it so and ``money`` when its currency is given (without
    it, the card paints it in the project's own); with words that price nothing, it is no amount but as sent.
    ``titled`` when ``label`` is the title its app wrote (``own_title``): the screen calls it so over its own word for
    a datum it knows by its name; a list, ``named`` when each of its items is said in words (``NAMED``)."""
    # The title of the property itself, as its caller's ``label``: a ``$ref``'s own is its schema class's name.
    titled = own_title(name, prop.get("title")) is not None
    sent = value = hidden(value, prop, defs)
    if words is not None:
        value = said(value, prop, defs, name, words)
    if value is LEFT_OUT:
        return None
    prop = resolved(prop, defs)
    if value is None or value == "" or value == []:
        kind = "empty"
    elif isinstance(value, bool):
        kind = "bool"
    elif isinstance(value, int) and is_money(prop) and (words is None or words.priced):
        kind = "money"
    elif isinstance(value, list):
        kind = "list"
    elif isinstance(value, dict):
        kind = "object"
    else:
        kind = "text"
    shown = {"name": name, "label": label, "kind": kind, "value": value}
    if titled:
        shown["titled"] = True
    if kind == "list" and words is not None and isinstance(sent, list) and _said_in_words(sent, value, prop, defs):
        shown[NAMED] = True
    if kind == "money" and is_signed(prop):
        shown["signed"] = True
    if kind == "money" and money is not None:
        shown["money"] = money
    return shown


def _over_records(op: Operation) -> bool:
    """Whether ``op`` is a dangerous write over the records its ``ids`` name."""
    schema = input_schema(op)
    ids = resolved(schema.get("properties", {}).get("ids", {}), schema.get("$defs", {}))
    return risk(op) == "high" and ids.get("type") == "array"


def blocked(op: Operation, arguments: dict) -> bool:
    """Whether ``arguments`` ask the dangerous write ``op`` over records (``ids``) and name none: not done from the
    chat, whatever else they say (its card says so; the model is never asked to name records for it)."""
    ids = arguments.get("ids")
    return _over_records(op) and not (isinstance(ids, list) and ids)


def card(op: Operation, arguments: dict, language: str, words: Words | None = None) -> dict:
    """What the person sees before ``op`` runs with ``arguments``: where it happens (``Words.app_name``), its action,
    each datum it sends by its name in ``language`` (``label``) and in ``words`` (``said``; ``PlainWords`` without
    them), its risk and, for a dangerous one, what to type (``confirm_word``) — how many records when it names them
    by ``ids``, and ``blocked`` when it names none (not from the chat)."""
    schema = input_schema(op)
    defs = schema.get("$defs", {})
    props = schema.get("properties", {})
    level = risk(op)
    refused = blocked(op, arguments)
    count = len(arguments["ids"]) if _over_records(op) and not refused else None
    words = (words if words is not None else PlainWords(op, language)).within(arguments, props, defs)
    with translation.override(language):
        shown = [
            # The title of the property itself: a ``$ref``'s own is its schema class's name.
            field(name, label(op, name, prop.get("title")), prop, defs, arguments[name], words.money(), words)
            for name, prop in props.items()
            if name in arguments
        ]
        fields = [one for one in shown if one is not None]
        word = str(count) if count else str(CONFIRM_WORD)
        app = words.app_name()
    return {
        "operation": op.name,
        "app": op.app_label,
        "app_name": app,
        "action": op.name.rsplit(".", 1)[-1],
        "risk": level,
        "fields": fields,
        "count": count,
        "confirm_word": word if level == "high" else "",
        "blocked": refused,
    }


def confirmed(card_: dict, typed: str) -> bool:
    """Whether ``typed`` is what the card asks, as the platform's ``ConfirmDialog`` compares it (``@erplora/ui``: spaces
    around and case ignored, accents not); a normal write asks nothing; a blocked one, never."""
    word = card_["confirm_word"]
    return not card_["blocked"] and (word == "" or typed.strip().casefold() == word.casefold())
