"""The tools a turn offers, best first (relevant)."""

from collections.abc import Callable, Iterable
from functools import cache, lru_cache

from django.utils import translation

from live.assistant.aside import named_aside
from live.assistant.reading import (
    Asked,
    asked,
)
from live.assistant.stemming import (
    _concept,
    _groups,
    _sentences,
    _stems_of,
    _taken,
    stem,
    stems,
)
from live.assistant.tools import (
    MAX_TOOLS,
    asks_of,
    config_of,
    description,
)
from live.assistant.vocabulary import (
    _BEFORE_UPDATE,
    _CHANGES,
    _EMPTYING,
    _OF,
    _REGISTERS,
    _SET_STATES,
    _TURNS,
    HOWTO_POINTS,
    READ_VERBS,
    SWITCHES,
    VERBS,
)
from live.operations import AI, Operation


# ── By relevance ─────────────────────────────────────────────────────────────────────────────────────────────────
#
# A turn offers the few tools of what was asked (``relevant``), chosen with no model nor network: the words of the
# question, cut to their stems (``stem``: «vendí», «vendido» and «vender» are one; «cóbrale» is «cobra»), each with the
# words that name the same thing (``SYNONYMS``, and the project's own: «cuenta» is a check in the Hub, the account in
# the SaaS), against each tool's app (its names in both languages), the parts of its name, its ``ai=`` description and
# what people say to ask for it (its ``asks``); the action asked (``VERBS``) of the thing named weighs most. A question
# asks to know: its reads come first, and the action it names without asking for it («what can customers pay with?»)
# is what it asks about; a how-to question («how do I…?») is answered from the help (``howto``). The same question
# always gets the same tools.

@cache
def app_words(label: str, language: str) -> frozenset[str]:
    """How a person names the app ``label``: its id, its name and its menu, in English and in ``language``."""
    config = config_of(label)
    words = stems(label.replace("_", " "))
    if config is None:
        return frozenset(words)
    for lang in ("en", language):
        with translation.override(lang):
            words |= stems(str(config.verbose_name))
            for nav in getattr(config, "navigation", []) or []:
                words |= stems(str(nav.label))
    return frozenset(words)


#: The stems of an operation's entity that name an app («base.app.enable»): an app named by its name is that entity.
_APP_THING = frozenset(stem(word) for word in ("app", "aplicacion", "modulo", "module"))


#: The words of an action that say for what, not what it acts on (``list_for_customer``, ``by_phone``,
#: ``create_from_sale``): what comes after them is no object of it.
_QUALIFIERS = frozenset({"for", "by", "from", "to", "of", "in", "with"})


@lru_cache(maxsize=4_096)
def _acts(op: Operation) -> frozenset[str]:
    """The words of ``op``'s action (``create_folder`` → «create», «folder») and what they do said another way: the
    state it sets turns a thing on and off (``_SET_STATES``: ``set_enabled``), emptying takes away (``_emptied``), a
    change that takes a name renames («renombra Bienvenida»: ``flow.flow.update``; ERPlora/live#53) and what its ``ai=``
    says it does («ponle el IVA a la comida»: creating a tax rule sets the rate; ``AI.does``)."""
    words = frozenset(op.name.split(".")[2].split("_"))
    does = {verb for word in words for verb in _SET_STATES.get(word, ())} | _emptied(op)
    if "update" in words and "name" in getattr(op.input, "model_fields", {}):
        does.add("rename")
    if isinstance(spec := op.ai_spec(), AI):
        does.update(spec.does)
    return words | does


@lru_cache(maxsize=4_096)
def _emptied(op: Operation) -> frozenset[str]:
    """What ``op``'s action does by emptying a thing (``_EMPTYING``), besides its own words: asked only of what the
    command acts on."""
    words = frozenset(op.name.split(".")[2].split("_"))
    return frozenset(verb for word in words for verb in _EMPTYING.get(word, ())) - words


@lru_cache(maxsize=4_096)
def _things(op: Operation) -> frozenset[str]:
    """The stems of what ``op`` is of: its entity and what its action acts on (``_parts``)."""
    _, entity, action = op.name.split(".")
    return _stems_of(entity.replace("_", " ")) | _parts(action)[0]


@lru_cache(maxsize=8_192)
def _parts(action: str) -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    """The stems of what an operation's ``action`` acts on — its words before a qualifier (``_QUALIFIERS``) that are no
    action asked (``create_folder`` → «folder», ``avatar_set`` → «avatar», ``today``) —, of the actions it does
    (``create``) and of what it says for what (``customer`` of ``list_for_customer``)."""
    words = action.split("_")
    cut = next((i for i, word in enumerate(words) if word in _QUALIFIERS), len(words))
    acted_on = [word for word in words[:cut] if word not in VERBS]
    doing = [word for word in words[:cut] if word in VERBS]
    return _stems_of(" ".join(acted_on)), _stems_of(" ".join(doing)), _stems_of(" ".join(words[cut:]))


def relevant(  # noqa: PLR0913
    tools: dict[str, Operation],
    texts: Iterable[str],
    language: str,
    *,
    always: Iterable[str] = (),
    app_words: Callable[[str, str], frozenset[str]] = app_words,
    synonyms: Iterable[Iterable[str]] = (),
    howto: Iterable[str] = (),
) -> list[Operation]:
    """The tools of what ``texts`` ask, best first, at most ``MAX_TOOLS``; ``always`` (what is always at hand) first.

    Each thing the question names (``asked``, with the project's ``synonyms``) counts 2 when it names the tool's entity
    or what its action acts on (``_parts``: ``create_folder`` acts on a folder), else 1 when it names only the tool's
    app (in either language, ``app_words``: an app's name breaks ties, it never drowns the thing asked) — unless the
    question names no tool's thing at all: then the app named by its own name is the thing of its tools («la cocina»:
    its tickets and stations; «abre la caja»: the till's session); 2 more when it names the action itself and not the
    tool's entity («asignado» names an assignment, not assigning), 1 when it names what the action says it is for
    (``list_for_customer``), and 1 for each of its description, what people say to ask for it (``asks_of``, in any
    language) and the data its input takes.

    The action asked (``VERBS``) of a thing the question names, or another way of saying it (``_acts``: «activa» is
    the ``set_enabled`` of an automation), adds 9, 1 more when the tool's action is that verb
    itself (``create``, before ``bulk_create``), 1 more again when its words ask ``update`` only for what has none of
    its own (``_BEFORE_UPDATE``: ``reorder``, before ``update``) and 3 more when that thing is what the command acts on
    (``Asked.objects``: «crea la carpeta Facturas» creates a folder, not an invoice); setting a device up
    (``_REGISTERS``) and taking away what a tool empties (``_emptied``: «borra el enrutado») count only when that thing
    is what the command acts on («registra esta tablet», never «registra en
    esta tablet una salida…»); «activa la app» is
    ``base.app.enable``, never an operation of the app named after it, and so is «activa los clientes», an app named
    by its name; named alone as what a switch turns on or off, with no other app nor thing nor what it is of, the app
    adds the 3 of what the command acts on («apaga las ventas», «turn off the kitchen»: before a write that takes what
    the app's name also names, a product's sold out or a ticket; never «turn off stock control», «desactiva el control
    de stock» nor «desactiva la venta del café»; ERPlora/live#77). What a switch turns on or off (``Asked.switched``)
    that names no tool's thing but an app is the thing
    of the switch of that action whose asks name it, with the apps said beside it: «desactiva los recordatorios de
    las citas» turns off the recipe whose asks say «apaga la receta del recordatorio de citas», before turning the
    Appointments app off; a word the asks of the switches of several things say («de momento», «por ahora») is the
    thing of none (ERPlora/live#89). Of no thing named, it adds 7 to a write that takes a datum the question names
    («cambia el precio»: a write that takes a ``price``; «turn off the alerts»: a write that takes what is turned on
    or off, as switching changes it, never a datum a clause said beside the command names (``named_aside``:
    «activa el envío real, comprobando antes que la cuenta…» changes no check; ERPlora/live#76)), 3 to
    any other write unless a tool does that to what the command acts on, or it is an app named by its name («reserva
    una mesa»: no write of the staff; «abre la cocina»: no other app's open), 1 to
    a read of the app named and nothing to any other read: «¿cuántos…?» is no list of everything, and what a read is
    filtered by is not what it reads. A change asked only by a word that notes something down («anota», «apunta»:
    ``Asked.written_on``) writes on a thing named or on what is noted down (``Asked.noted``: «apúntale el teléfono
    nuevo a Ana»): of no thing named, a write that takes only what another word names in passing adds nothing («anota
    una salida de 15 € de la caja» notes a movement down, not the till's settings, which take the cash register;
    ERPlora/live#88), and one that takes what is noted down, or nothing named, adds what any other write does. A create
    or an add asked only by a word that notes down what happened (``Asked.stated``) takes nothing the fact names when the
    fact is another tool's doing: what it is about is what a tool's action acts on and no write asked acts on it
    («registra que entran 20 cafés a 0,55 € la unidad»: receiving goods), and then, of no thing named, a write that takes
    it adds nothing; about anything else, the fact's data still say which write notes it down («apunta que el viernes
    vienen 6 a cenar a nombre de Luis»: a reservation; ERPlora/live#116).

    A write of a thing named after its verb brings its reads 3 («borra el cliente Ana»: the read that finds Ana). A
    question that asks to know and to do nothing puts the reads first (1), a thing's list before its other reads (1),
    and the reads of what it asks about 3 more («what can customers pay with?»: the payment methods); a how-to question
    gives the help (``howto``, the project's documentation search) ``HOWTO_POINTS``. Ties go by name: the same
    question, the same tools."""
    return _relevant(
        tools, list(texts), language, always=always, app_words=app_words, synonyms=tuple(synonyms), howto=howto
    )


def _relevant(  # noqa: C901, PLR0913, PLR0915
    tools: dict[str, Operation],
    texts: Iterable[str],
    language: str,
    *,
    always: Iterable[str] = (),
    app_words: Callable[[str, str], frozenset[str]] = app_words,
    synonyms: Iterable[Iterable[str]] = (),
    howto: Iterable[str] = (),
    asks: Callable[[Operation], frozenset[str]] | None = None,
) -> list[Operation]:
    """``relevant``, with what each tool's asks say read by ``asks`` (the QA leaves out the phrase it ranks)."""
    said = asked(texts, synonyms)
    concepts, verbs, about = said.concepts, said.verbs, said.about
    asks = asks or _asks_stems
    writing = bool(verbs - READ_VERBS)
    switching = not verbs.isdisjoint(SWITCHES)
    helps = frozenset(howto) if said.howto else frozenset()
    always = tuple(always)

    def named(words: frozenset[str]) -> int:
        return sum(1 for concept in concepts if not concept.isdisjoint(words))

    # The things the catalogue's tools are of. A question that names none of them but an app by its name («la cocina»:
    # the kitchen app, of tickets and stations) makes that app the thing; beside a thing named («el registro de
    # eventos») the app's name only breaks ties.
    things = frozenset().union(*(_things(op) for op in tools.values())) if concepts else frozenset()
    every_app = {op.app_label for op in tools.values()} if concepts else set()
    names_a_thing = any(not concept.isdisjoint(things) for concept in concepts)
    by_app = frozenset() if names_a_thing else _naming_apps(concepts, every_app, app_words, language)
    # An app switched is one the command names («activa las ventas», «activa otra vez las ventas», «ya no usamos la
    # cocina, desactívala»), not one named for what something is («vuelve a activar Mayorista para las próximas ventas»:
    # a price list, ERPlora/live#50).
    apps_named = _naming_apps(said.direct, every_app, app_words, language) if switching else frozenset()
    # What a command acts on, when a tool does that to it or it is an app named by its name: then the writes of other
    # things are not what it asks («reserva una mesa» is no staff's create; «create a 10% discount» has no tool that
    # creates a discount, so the creates stay).
    aimed_at = writing and any(
        concept in by_app
        or any(
            not concept.isdisjoint(_things(op)) and not verbs.isdisjoint(_acts(op))
            for op in tools.values()
        )
        for concept in said.objects
    )
    # What happened, noted down («registra que entran 20 cafés…»), is another tool's doing when what it is about is what
    # a tool's action acts on («entran»: ``stock.receive``) and no write asked acts on it: its data are not the create's
    # or the add's asked so. About anything else («vienen 6 a cenar a nombre de Luis», «la clienta Ana…»), its data
    # still say which write notes it down.
    done_by_another = not aimed_at and any(
        not concept.isdisjoint(_parts(op.name.split(".")[2])[0]) for op in tools.values() for concept in said.objects
    )
    # What a switch turns on or off that the catalogue names as no thing, beside the apps said with it («los
    # recordatorios» of «desactiva los recordatorios de las citas», «the appointment reminders»): only what people say
    # to ask for a tool names it (ERPlora/live#89).
    unnamed: list[tuple[frozenset[frozenset[str]], frozenset[frozenset[str]]]] = []
    for head in said.switched:
        apps = _naming_apps(head, every_app, app_words, language)
        rest = head - apps
        if rest and all(concept.isdisjoint(things) for concept in rest):
            unnamed.append((rest, apps))
    # A word the asks of the switches of several things say tells for how long, not what («de momento», «por ahora»):
    # it is the thing of none of them.
    if unnamed:
        said_by: dict[frozenset[str], set[tuple[str, str]]] = {}
        for op in tools.values():
            app, entity, action = op.name.split(".")
            if not _TURNS.isdisjoint(verbs.intersection(_acts(op))):
                its = asks(op)
                for rest, _ in unnamed:
                    for concept in rest:
                        if not concept.isdisjoint(its):
                            said_by.setdefault(concept, set()).add((app, entity))
        unnamed = [
            (frozenset(concept for concept in rest if len(said_by.get(concept, ())) == 1), apps)
            for rest, apps in unnamed
        ]
    # What a clause beside the command names, but what a switch turns on or off, is no datum the switch changes.
    beside = named_aside(texts, synonyms) - frozenset().union(*said.switched)

    def score(op: Operation) -> int:  # noqa: C901, PLR0912
        app, entity, action = op.name.split(".")
        named_app, named_entity = app_words(app, language), _stems_of(entity.replace("_", " "))
        acted_on, doing, qualified = _parts(action)
        # A word that names the tool's thing is not also its action named («asignaciones», «assigned»: an assignment).
        doing -= named_entity
        acts = _acts(op)
        # A switch of the action asked whose asks name what is turned on or off, and one of the apps said with it if
        # any, switches that thing.
        by_asks: set[frozenset[str]] = set()
        if unnamed and not _TURNS.isdisjoint(verbs.intersection(acts)):
            its = asks(op)
            by_asks = {
                concept
                for rest, apps in unnamed
                if not apps or any(not app_said.isdisjoint(its) for app_said in apps)
                for concept in rest
                if not concept.isdisjoint(its)
            }
        places = thing = 0
        aimed = found = app_named = False
        for concept in concepts:
            in_app = not concept.isdisjoint(named_app)
            is_thing = (
                not concept.isdisjoint(named_entity)
                or not concept.isdisjoint(acted_on)
                or (in_app and concept in by_app)
                or concept in by_asks
            )
            thing += is_thing
            aimed = aimed or (is_thing and concept in said.objects)
            found = found or (is_thing and concept in said.records)
            app_named = app_named or in_app
            places += 2 if is_thing else in_app
            places += 2 * (not concept.isdisjoint(doing)) + (not concept.isdisjoint(qualified))
        if not thing and apps_named and not _APP_THING.isdisjoint(named_entity):
            thing, aimed = 1, _one_app_switched(said, apps_named, things, _said_of(texts, synonyms))
        taken = _taken(op.input)
        takes = named(taken)
        points = places + named(_stems_of(description(op))) + named(asks(op)) + takes
        matched = verbs.intersection(acts)
        if not aimed:
            matched -= _REGISTERS | _emptied(op)
        if matched:
            if thing:
                points += 9 + (action in verbs) + (action in verbs & _BEFORE_UPDATE) + 3 * aimed
            else:
                writes = matched - READ_VERBS
                # What «anota» writes on is a thing named, or what it notes down («apúntale el teléfono nuevo a Ana»): a
                # write that takes only what another word names in passing is none of it («anota una salida de 15 €
                # de la caja»: the till's settings take the cash register, not the money taken out). What happened, noted
                # down as another tool's doing («registra que entran 20 cafés a 0,55 € la unidad»), gives the create or
                # the add asked so none of what it names: the quantity is the goods', not a check line's.
                in_passing = (
                    takes
                    and writes
                    and (
                        (
                            writes <= said.written_on
                            and not any(not concept.isdisjoint(taken) for concept in said.noted)
                        )
                        or (done_by_another and writes <= said.stated)
                    )
                )
                if not in_passing:
                    points += 7 if takes and writes else 3 if writes and not aimed_at else 1 if app_named else 0
        elif (
            switching
            and not _CHANGES.isdisjoint(acts)
            and any(not concept.isdisjoint(taken) for concept in concepts - beside)
        ):
            points += 7
        if op.kind == "query":
            if about and any(not concept.isdisjoint(named_entity) for concept in about):
                points += 3
            if writing and found:
                points += 3
            if said.reading and not writing:
                points += 1 + (action == "list" and thing > 0)
        if op.name in helps:
            points += HOWTO_POINTS
        return points

    return _offered(tools, always, score)


def _offered(
    tools: dict[str, Operation], always: tuple[str, ...], score: Callable[[Operation], int]
) -> list[Operation]:
    """``always`` first, then the tools the words name (a ``score`` above 0), best first and by name, at most
    ``MAX_TOOLS``: one they do not name is never offered to fill the share."""
    first = [tools[name] for name in always if name in tools]
    points = {op.name: score(op) for op in tools.values() if op.name not in always}
    named = sorted((name for name, got in points.items() if got > 0), key=lambda name: (-points[name], name))
    return [*first, *(tools[name] for name in named)][:MAX_TOOLS]


def _naming_apps(
    concepts: Iterable[frozenset[str]],
    labels: Iterable[str],
    app_words: Callable[[str, str], frozenset[str]],
    language: str,
) -> frozenset[frozenset[str]]:
    """The ``concepts`` that name one of the apps of ``labels`` by its name (``app_words``)."""
    return frozenset(
        concept for concept in concepts if any(not concept.isdisjoint(app_words(label, language)) for label in labels)
    )


def _one_app_switched(
    said: Asked, apps_named: frozenset[frozenset[str]], things: frozenset[str], said_of: frozenset[frozenset[str]]
) -> bool:
    """Whether what a switch turns on or off is the one app the command names (of ``apps_named``, never empty here),
    nothing else it names is an app or a thing of the catalogue (``things``) and it is not said with what it is of
    (``said_of``): «las ventas», «the kitchen»; never «stock control» nor «el control de stock», a setting of the
    stock, nor «la venta del café», the sales of a product."""
    named = frozenset(concept for concept in said.direct if concept in apps_named or not concept.isdisjoint(things))
    return len(named) == 1 and named in said.switched and named.isdisjoint(said_of)


def _said_of(texts: Iterable[str], synonyms: Iterable[Iterable[str]]) -> frozenset[frozenset[str]]:
    """What ``texts`` name with what it is of right after it (``_OF``: «la venta del café», «the sales of the
    coffee»)."""
    extra = _groups(synonyms)
    return frozenset(
        _concept(word, extra)
        for text in texts
        for words in _sentences(text)
        for word, after in zip(words, words[1:], strict=False)
        if after in _OF
    )


@lru_cache(maxsize=4_096)
def _asks_stems(op: Operation) -> frozenset[str]:
    """The stems of every phrase of ``op``'s asks, in every language: read once per operation (by identity; its
    ``ai=`` does not change once declared), however many turns rank it — the QA ranks once per ask of hundreds."""
    return _stems_of(" ".join(phrase for phrases in asks_of(op).values() for phrase in phrases))
