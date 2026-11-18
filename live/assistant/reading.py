"""What a turn asks (asked): the things it names, the actions it asks for and whether it asks to know."""

import unicodedata
from collections.abc import Collection, Iterable, Mapping
from typing import NamedTuple

from live.assistant.stemming import (
    _concept,
    _goes_on,
    _groups,
    _sentences,
    _synonyms,
    _unclitic,
)
from live.assistant.vocabulary import (
    _ARTICLES,
    _AUXILIARIES,
    _CAN,
    _CLITICS,
    _COMES_IN,
    _CONFIRMS,
    _CURRENCIES,
    _DETERMINERS,
    _FILLERS,
    _FOR_WHAT,
    _FOUND_BY,
    _FUTURE,
    _GREETINGS,
    _HAVE,
    _HOW_TO,
    _HOW_TO_LEADS,
    _INFINITIVE,
    _INTERROGATIVE,
    _LETS,
    _NAMING,
    _NOR,
    _NOT_VERBS,
    _NOTES,
    _OF,
    _OTHER_CLAUSE,
    _OUT,
    _OUTFLOW,
    _OWN_OBJECT,
    _PARTICIPLE,
    _PHRASE_NAMES,
    _PHRASES,
    _PRESENT,
    _PRONOUNS_AFTER,
    _PUTS,
    _REGISTERED_FROM,
    _REGISTERS,
    _REQUESTS,
    _STATES,
    _TAKE,
    _TAKEN_OUT,
    _TAKES_OUT,
    _THAT,
    _THEN,
    _TILL,
    _TO_WHOM,
    _VERB_OF,
    _WHERE,
    _WITH_ITS_ARTICLE,
    _WITH_ITS_SIGN,
    _WITH_PRONOUNS,
    _WITHOUT,
    _WRITTEN_ON,
    _YES,
    QUESTION_WORDS,
    READ_VERBS,
    STOP_WORDS,
    SWITCHES,
    VERBS,
)


class Asked(NamedTuple):
    """What texts ask (``asked``): what their words name (``concepts``, each a set of stems), the actions they ask for
    (``verbs``), whether they ask to know (``reading``), what a question asks about (``about``: what the action it names
    without asking for it names, «pay» in «what can customers pay with?»), whether it asks how something is done
    (``howto``) and what each command acts on (``objects``: the first thing it names from its verb on — «crea la
    carpeta Facturas» creates a folder; «cobra la mesa» charges a sale, the verb's own thing), of which ``records``
    the ones a word after the verb names («borra el cliente Ana»: a customer to find). ``direct`` are the things named
    outside what something is for (``_FOR_WHAT``: «ventas» in «activa las ventas», not in «para las próximas
    ventas»). ``written_on`` are the actions asked only as what a word that notes something down writes on
    (``_WRITTEN_ON`` of «anota», «apunta»; ERPlora/live#88): no other word asks for them; ``noted`` is what such a word
    notes down (``_noted``: the new phone of «apunta en la ficha de Ana su teléfono nuevo»). ``switched`` is what each
    switch said turns on or off, one set of things per switch (``_switched``: «los recordatorios» of «desactiva los
    recordatorios de las citas»; ERPlora/live#89). ``stated`` are the create and the add asked only by a word that notes
    down what happened (``_THAT``: «registra que entran 20 cafés…»; ERPlora/live#116)."""

    concepts: frozenset[frozenset[str]]
    verbs: frozenset[str]
    reading: bool
    about: frozenset[frozenset[str]]
    howto: bool
    objects: frozenset[frozenset[str]] = frozenset()
    records: frozenset[frozenset[str]] = frozenset()
    direct: frozenset[frozenset[str]] = frozenset()
    written_on: frozenset[str] = frozenset()
    noted: frozenset[frozenset[str]] = frozenset()
    switched: frozenset[frozenset[frozenset[str]]] = frozenset()
    stated: frozenset[str] = frozenset()


def _phrase_verbs(phrase: str) -> frozenset[str]:
    """The actions a verb said in words (`` set up ``) asks for."""
    return frozenset(verb for verb, forms in VERBS.items() if phrase.strip() in forms)


def _verbs_of(word: str) -> frozenset[str]:
    """The actions the plain ``word`` asks for: as said, or without the pronouns of a command («cóbrale»)."""
    found = _VERB_OF.get(word)
    if found is None and (bare := _unclitic(word)) is not None:
        found = _VERB_OF.get(bare)
    return found or frozenset()


def _opening(words: list[str]) -> tuple[list[str], bool]:
    """A sentence from the first word that says something — greetings (``_GREETINGS``) and the words of a request
    (``_REQUESTS``: «puedes», «can you») off — and whether it is a request."""
    at, request = 0, False
    while at < len(words):
        if words[at] in _GREETINGS:
            at += 1
            continue
        said = next((len(one) for one in (tuple(words[at : at + 2]), (words[at],)) if one in _REQUESTS), 0)
        if not said:
            break
        at, request = at + said, True
    return words[at:], request


def _commands(words: list[str]) -> bool:
    """Whether a sentence (``_opening``) is a command: it starts with a verb that does something («cobra la mesa 4»,
    «delete customer Ana»), or with «do» and what it does («do a refund»)."""
    if not words:
        return False
    if words[0] == "do":
        words = [word for word in words[1:3] if word not in _ARTICLES][:1]
    return bool(words) and bool(_verbs_of(words[0]) - READ_VERBS)


def _how_to(sentences: list[list[str]]) -> str | None:
    """Whether a sentence asks how something is done (``_HOW_TO``), after the words that only ask for it («dime cómo…»):
    the word that says what is done after «cómo» («invito»), «-» when none; ``None`` when no sentence asks so."""
    for said in sentences:
        lead = 0
        while lead < min(len(said), 3) and said[lead] in _HOW_TO_LEADS | _GREETINGS:
            lead += 1
        words = said[lead:]
        if not words:
            continue
        after = [word for word in words[1:] if word not in _CLITICS]
        if words[0] in _HOW_TO and after:
            if after[0] in _HOW_TO[words[0]]:
                return "-"
            if words[0] == "como" and after[0].endswith("o") and len(after[0]) >= 4:
                return after[0]
    return None


def _is_question(text: str, sentences: list[list[str]]) -> bool:
    """Whether ``text`` is a question: never when a sentence is a command (``_commands``, after its greetings and the
    words of a request: «hola, ¿puedes cobrar la mesa 4?», «cobra la mesa 4 y dime cuánto es», «do a refund»); else a
    question word with its accent, a text that starts with one or with the auxiliary of a yes/no question, or its
    marks («?», «¿»). An unaccented «que» asks only with the marks: inside a sentence («dice que sí»), after a command
    («anula el ticket, que me equivoqué») or at the start of a wish («que no se pueda cobrar sin cliente») it is
    none."""
    if any(_commands(_opening(words)[0]) for words in sentences):
        return False
    if _INTERROGATIVE.search(unicodedata.normalize("NFC", text).lower()):
        return True
    marked = "?" in text or "¿" in text
    first = sentences[0][0] if sentences else ""
    return first in _AUXILIARIES or (first in QUESTION_WORDS and first != "que") or marked


def _objects(
    sentences: list[list[str]],
    acting: Mapping[str, frozenset[str]],
    verbal: Collection[str],
    extra: tuple,
    of_money: Collection[tuple[int, int]] = (),
) -> tuple[set[frozenset[str]], set[frozenset[str]]]:
    """What the command of each sentence acts on: the first thing named from its verb on — the verb's own when it
    names one («cobra»: a sale), else the first word after it that names something («crea la carpeta»: a folder) —;
    and of those, the ones named by a word after the verb (a record to find). Of a verb that puts something somewhere
    (``_PUTS``), where it is put, said first, is no thing it acts on: what it puts is named after it
    (``_named_after_where``: «anota en el turno una salida» notes the money taken out, as «anota una salida en el
    turno» does; ERPlora/live#94). A verb that takes money out, or a word that says money came in (``of_money``, by
    sentence and word), acts on the money, no thing named («saca 15 € de la caja para comprar hielo», «apunta que entran
    100 € de propina»)."""
    found: set[frozenset[str]] = set()
    after: set[frozenset[str]] = set()
    for index, words in enumerate(sentences):
        seen = False
        verb = ""
        for at, word in enumerate(words):
            if (index, at) in of_money:
                break
            if word in acting or word in verbal:
                own = _concept(word, extra) if word in acting and not seen else frozenset()
                if len(own) > 1:
                    found.add(own)
                    break
                seen, verb = True, word
            elif (
                seen
                and not _PUTS.isdisjoint(acting.get(verb, ()))
                and _puts_where(words, at)
                and (thing := _named_after_where(words, at)) is not None
            ):
                found.add(_concept(words[thing], extra))
                after.add(_concept(words[thing], extra))
                break
            elif seen and len(word) >= 3 and word not in STOP_WORDS:
                found.add(_concept(word, extra))
                after.add(_concept(word, extra))
                break
    return found, after


def _determiner(word: str) -> bool:
    """Whether ``word`` opens a phrase of its own: a determiner (``_DETERMINERS``) or another word that names nothing
    by itself (``STOP_WORDS``: «esta», «unos», «sus»)."""
    return word in _DETERMINERS or word in STOP_WORDS


def _puts_where(words: list[str], at: int) -> bool:
    """Whether ``words[at]`` says where something is put, before what is put: a word of ``_WHERE`` with its article
    (``_WITH_ITS_ARTICLE``: «del turno», «al carrito») or before a determiner («en el turno», «a la cuenta», «en esta
    caja»). Before a name it is whom it is done to («apúntale a Ana…»), and English's «a» goes before a number, a letter
    or a word («add a 10% discount», «add a QR code»)."""
    after = words[at + 1] if at + 1 < len(words) else ""
    return words[at] in _WHERE and (words[at] in _WITH_ITS_ARTICLE or _determiner(after))


def _named_after_where(words: list[str], at: int) -> int | None:
    """Where the thing is named that a command acts on when ``words[at]`` says first where it is put
    (``_puts_where``): the first word that names something in a phrase of its own — after a determiner or a number no
    word of ``_WHERE`` introduces —, before another clause or command (``_OTHER_CLAUSE``, ``_THEN``). Where it is put
    goes on with what it is of and with its name: «anota en el turno de Barra una entrada» names the money brought in,
    «añade a la carpeta Facturas un documento» a document; ``None`` when nothing is named so («anota en la cita de Ana
    que…», «… de Ana QA de mañana»)."""
    introduced = opened = False
    for later in range(at, len(words)):
        word = words[later]
        if word in _OTHER_CLAUSE or word in _THEN:
            return None
        if word in _WHERE:
            introduced = True
        elif _determiner(word) or word.isdigit():
            opened = opened or not introduced
        elif len(word) >= 3:
            if opened:
                return later
            introduced = False
    return None


def _starts_command(words: list[str], at: int) -> bool:
    """Whether another command starts at ``words[at]``, inside a sentence: what only asks (``_FILLERS``: «tell me»),
    or a verb of ``VERBS`` where one starts — after ``_THEN`` («y muestra», «and show») or said with its pronouns
    («dime», «búscame», ``_WITH_PRONOUNS``; «show me», ``_PRONOUNS_AFTER``). Anywhere else a verb's word is of the
    thing named («la primera lista», «de muestra», «the price list», «register 2»: ERPlora/live#59), and a word that
    names a thing (``_NOT_VERBS``: «baja y alta», «old and new») never starts one."""
    if any(" ".join(words[at : at + len(one.split())]) == one for one in _FILLERS):
        return True
    word = words[at]
    if word in _NOT_VERBS or not _verbs_of(word):
        return False
    return (
        words[at - 1] in _THEN
        or _unclitic(word) is not None
        or word in _WITH_PRONOUNS
        or (at + 1 < len(words) and words[at + 1] in _PRONOUNS_AFTER)
    )


def _unasked(words: list[str], at: int) -> bool:
    """Whether the verb ``words[at]`` says what is not to be done: its infinitive, its pronouns too, after ``_WITHOUT``
    («sin cambiar los pedidos», «sin quitarle el PIN») or after ``_NOR`` going on from a ``_WITHOUT`` before it in the
    sentence («sin tocar caja ni cambiar importes»), with no ``_NOT`` between the two («no puedo ni cerrar la caja») and
    no verb after it that says it cannot even be done (``_not_even``: «ni cerrar la caja me deja»)."""
    word = words[at]
    before = words[at - 1] if at > 0 else ""
    negated = before in _WITHOUT or (
        before in _NOR and _goes_on(words[: at - 1]) and not _not_even(words, at)
    )
    return negated and bool(_verbs_of(word)) and _infinitive(word)


def _notes_what_happened(words: list[str], at: int, actions: frozenset[str]) -> bool:
    """Whether the word ``words[at]``, asking for ``actions``, notes down what happened: a word that notes something
    down or puts it somewhere (``_NOTES``, with ``_PUTS``) said right before ``_THAT`` («registra que…», «apúntame
    que…»)."""
    return actions <= _NOTES and not _PUTS.isdisjoint(actions) and at + 1 < len(words) and words[at + 1] in _THAT


def _registers(words: list[str], at: int) -> bool:
    """Whether the word ``words[at]`` asks there to set something up (``_REGISTERS``): never right before ``_THAT``,
    where it notes down what happened («registra que la tablet se ha roto»), and English's «register», which is also
    the till («open the register on this tablet», «close the cash register»), only where it starts the command: first,
    after the words of a request, or after ``_THEN`` («register this tablet as Bar», «please register…», «and
    register…»), and never before its number («register 2: close it»). Nor right before where or with what it is done
    (``_REGISTERED_FROM``: «registra desde esta tablet una salida», «register on this tablet won't open»)."""
    after = words[at + 1] if at + 1 < len(words) else ""
    if after in _THAT or after in _REGISTERED_FROM:
        return False
    if words[at] != "register":
        return True
    return not after.isdigit() and (
        at == len(words) - len(_opening(words)[0]) or (at > 0 and words[at - 1] in _THEN)
    )


def _amounts(text: str) -> frozenset[str]:
    """The numbers ``text`` says with their currency's sign («15 €», «€15», «12,50 €» → «15», «12»)."""
    return frozenset(before or after for before, after in _WITH_ITS_SIGN.findall(text))


def _money(words: list[str], at: int, amounts: Collection[str]) -> bool:
    """Whether ``words[at]`` is money: a number said with its currency's sign (``amounts``) or name («50 euros»). Any
    other number says how many («saca 2 copias», «take 5 out of stock»)."""
    if at >= len(words) or not words[at].isdigit():
        return False
    return words[at] in amounts or (at + 1 < len(words) and words[at + 1] in _CURRENCIES)


def _money_after(words: list[str], at: int, amounts: Collection[str]) -> bool:
    """Whether money (``_money``) is said right after ``words[at]`` or after where it goes or comes from, said first
    («15 € de la caja», «de la caja 15 €», «en caja 100 €»)."""
    money = at + 1
    if money < len(words) and words[money] in _WHERE:
        money += 1
        while money < len(words) and _determiner(words[money]):
            money += 1
        money += 1
    return _money(words, money, amounts)


def _comes_in(words: list[str], at: int, amounts: Collection[str]) -> bool:
    """Whether the word ``words[at]`` says money came in (``_COMES_IN``): «entran 100 €», «han entrado en caja 100 €»
    (``_money_after``)."""
    return words[at] in _COMES_IN and _money_after(words, at, amounts)


def _takes_money_out(words: list[str], at: int, amounts: Collection[str]) -> bool:
    """Whether the word ``words[at]`` takes money out (``_TAKES_OUT``): «saca» right before the money or before where it
    comes from and then the money («saca 15 € de la caja», «sácame del cajón 20 €»), «take» before the money and its
    «out» («take 15 € out of the till», «take 15 euros out») or before «out» and the money («take out 15 €»)."""
    word = words[at]
    if word in _TAKES_OUT or _unclitic(word) in _TAKES_OUT:
        return _money_after(words, at, amounts)
    if word != _TAKE:
        return False
    if _money(words, at + 1, amounts):
        return _OUT in words[at + 2 : at + 4]
    return words[at + 1 : at + 2] == [_OUT] and _money(words, at + 2, amounts)


def _as_present(words: list[str], amounts: Collection[str]) -> list[str]:
    """``words`` with the present of each compound past in the plural (``_HAVE``) said before it: «han entrado» is read
    «entran han entrado». Not of money said right after the participle or after where it comes in (``_money_after``:
    «han entrado 100 €», «han entrado en caja 100 €») nor of a present that asks for an action («han cuadrado»)."""
    read: list[str] = []
    for at, word in enumerate(words):
        participle = words[at + 1] if at + 1 < len(words) else ""
        present = participle.removesuffix(_PARTICIPLE) + _PRESENT
        if (
            word in _HAVE
            and participle.endswith(_PARTICIPLE)
            and not _verbs_of(present)
            and not _money_after(words, at + 1, amounts)
        ):
            read.append(present)
        read.append(word)
    return read


def _noted(words: list[str], at: int, extra: tuple[tuple[str, ...], ...]) -> set[frozenset[str]]:
    """What the word that notes something down ``words[at]`` notes: every thing named after it, until another command
    starts (``_starts_command``), but the one a word of ``_WHERE`` says, with its article, it is noted in or whose it is
    («apunta en la ficha de Ana García su teléfono nuevo»: Ana, García, the phone, new; «anota una salida de 15 € de la
    caja»: the money taken out; «apunta el número de teléfono de Ana»: the number, the phone, Ana)."""
    found: set[frozenset[str]] = set()
    where = False
    for later in range(at + 1, len(words)):
        word = words[later]
        if _starts_command(words, later):
            break
        if word in _WHERE:
            after = words[later + 1] if later + 1 < len(words) else ""
            where = word in _WITH_ITS_ARTICLE or len(after) < 3 or after in STOP_WORDS
        elif len(word) >= 3 and word not in STOP_WORDS:
            if not where:
                found.add(_concept(word, extra))
            where = False
    return found


def _switched(
    words: list[str], found: Collection[str], verbal: Collection[str], extra: tuple[tuple[str, ...], ...]
) -> set[frozenset[frozenset[str]]]:
    """What each switch said in ``words`` turns on or off — a word that asks for ``SWITCHES`` («desactiva», «apágalos»)
    or a phrase of them found in the text («turn off») —: the things named after it, up to the first word that says
    what they are of or for once one is named (``_OF``, ``_FOR_WHAT``), another switch or another command
    (``_starts_command``). «Desactiva los recordatorios de las citas»: the reminders; «turn off the appointment
    reminders»: the appointment and the reminders; «desactiva de momento los recordatorios»: the moment and the
    reminders."""
    starts = {at for at, word in enumerate(words) if not _verbs_of(word).isdisjoint(SWITCHES)}
    for phrase in found:
        if not _phrase_verbs(phrase).isdisjoint(SWITCHES):
            said = phrase.split()
            starts |= {at for at in range(len(words)) if words[at : at + len(said)] == said}
    heads: set[frozenset[frozenset[str]]] = set()
    for start in starts:
        head: set[frozenset[str]] = set()
        for later in range(start + 1, len(words)):
            word = words[later]
            if later in starts or _starts_command(words, later) or (head and word in _OF | _FOR_WHAT):
                break
            if word not in verbal and not _verbs_of(word) and len(word) >= 3 and word not in STOP_WORDS:
                head.add(_concept(word, extra))
        if head:
            heads.add(frozenset(head))
    return heads


def _infinitive(word: str) -> bool:
    """Whether the plain ``word`` is an infinitive, its pronouns too («cerrar», «borrarla»)."""
    return (_unclitic(word) or word).endswith(_INFINITIVE)


def _not_even(words: list[str], at: int) -> bool:
    """Whether the infinitive ``words[at]`` after a ``_NOR`` is what someone cannot even do: a form of ``_CAN``, or of
    ``_LETS`` after ``_TO_WHOM``, said after it with no infinitive of its own after it («ni cerrar la caja me deja»,
    «ni cerrar puedo la caja»; «…ni cambiar importes y así puedo cuadrar la caja» is what «cuadrar» can do) and with no
    ``_OTHER_CLAUSE`` before it («…ni cambiar importes si puede»), in a complaint: with an action asked before the
    ``_WITHOUT`` (``_asked_before_without``), the «ni» goes on with what is not to be done («cierra la caja sin contar
    ni cambiar el fondo y no me deja»)."""
    for later in range(at + 1, len(words)):
        word = words[later]
        if word in _OTHER_CLAUSE:
            return False
        if word in _CAN or (word in _LETS and words[later - 1] in _TO_WHOM):
            return (later + 1 == len(words) or not _infinitive(words[later + 1])) and not _asked_before_without(
                words, at
            )
    return False


def _asked_before_without(words: list[str], at: int) -> bool:
    """Whether an action is asked before the last ``_WITHOUT`` before ``words[at]``: a word of ``VERBS`` or one of its
    phrases («da de baja»), but a verb said as what is not to be done (``_unasked``: «se fue sin pagar y sigue sin
    cobrar»)."""
    without = max(before for before in range(at) if words[before] in _WITHOUT)
    heard = [word for before, word in enumerate(words[:without]) if not _unasked(words, before)]
    said = f" {' '.join(heard)} "
    return any(_verbs_of(word) for word in heard) or any(f" {phrase} " in said for phrase in _PHRASES)


def _foretold(words: list[str], at: int) -> bool:
    """Whether the word ``words[at]`` says what someone will do (after ``_FUTURE``: «knock 60% off the wine, I'll
    approve it», «it will turn on at nine»): the speaker's own doing, not what the assistant is asked; «will you…?» is
    a request."""
    return at > 0 and words[at - 1] in _FUTURE


def _without_yes(sentences: list[list[str]]) -> list[list[str]]:
    """The sentences of a text but its yes to what was asked before: a verb that confirms with no thing of its own and
    the words it is said with («sí, confírmalo», «vale, confirmo», «yes, confirm it»), never one that names what it
    confirms («confírmala para mañana»)."""
    yes = [words for words in sentences if all(word in _YES or word in _GREETINGS or _verbs_of(word) == _CONFIRMS
                                               for word in words)]
    if not any(_verbs_of(word) == _CONFIRMS for words in yes for word in words):
        return sentences
    return [words for words in sentences if words not in yes]


def _split_naming(sentences: list[list[str]]) -> set[tuple[str, str]]:
    """The naming phrases (``_NAMING``) of ``sentences`` said with words between their verb and the name («pon al
    dispositivo el nombre»; its pronouns too: «cámbiale a la tablet el nombre»), each with its verb as said; never of a
    verb with its own object (``_OWN_OBJECT``: «cambia el precio del café muestra el nombre del cliente»,
    ERPlora/live#59), a name that finds the thing (``_FOUND_BY``: «con el nombre») nor one after another command starts
    (``_starts_command``: «cambia el precio y dime el nombre del cliente», ERPlora/live#57) or after a verb that says
    what is not to be done (``_unasked``: «ponle otro precio sin cambiarle el nombre», ERPlora/live#60), which puts no
    name either («sin ponerle al menú el nombre»)."""
    found: set[tuple[str, str]] = set()
    for words in sentences:
        for at, word in enumerate(words):
            head = word if word in _NAMING else _unclitic(word)
            own_object = at + 1 < len(words) and words[at + 1] in _OWN_OBJECT
            if head not in _NAMING or _unasked(words, at) or _foretold(words, at) or own_object:
                continue
            end = next(
                (later for later in range(at + 1, len(words)) if _starts_command(words, later) or _unasked(words, later)),
                len(words),
            )
            for rest in _NAMING[head]:
                size = len(rest)
                if any(
                    tuple(words[later : later + size]) == rest and words[later - 1] not in _FOUND_BY
                    for later in range(at + 2, end - size + 1)
                ):
                    found.add((word, " ".join((head, *rest))))
    return found


def asked(texts: Iterable[str], synonyms: Iterable[Iterable[str]] = ()) -> Asked:  # noqa: C901, PLR0912, PLR0915
    """What ``texts`` ask (``Asked``): what each of their words names (``_concept``, with the project's ``synonyms``; a
    word of a verb's phrase names nothing, nor a verb but by its synonyms: «show me», «dame»), the actions they ask for
    (``VERBS``, a command with its pronouns too; money taken out, ``_TAKES_OUT``, asks to add it) and whether they ask
    to know (a question, ``_is_question``, or a read of ``READ_VERBS``). A question asks to do nothing it names unless
    it is a request («can you…?») or asks how («how do I…?»): its other actions are what it asks about
    (``Asked.about``)."""
    extra = _groups(synonyms)
    phrases_named = _synonyms(extra)[1]
    concepts: set[frozenset[str]] = set()
    verbs: set[str] = set()
    about: set[frozenset[str]] = set()
    objects: set[frozenset[str]] = set()
    records: set[frozenset[str]] = set()
    direct: set[frozenset[str]] = set()
    # The actions a word that notes something down asks for as writing on what is named (``_WRITTEN_ON``), those any
    # other word or phrase asks for — a change another one asks for, in any text of the turn, is its own («cambia la
    # caja…» and «y apunta una salida») — and what each word that notes something down notes (``_noted``).
    noting: set[str] = set()
    others: set[str] = set()
    noted: set[frozenset[str]] = set()
    switched: set[frozenset[frozenset[str]]] = set()
    # The actions asked by a word that notes down what happened (``_notes_what_happened``) and those any other word asks.
    stating: set[str] = set()
    asking: set[str] = set()
    reading = howto = False
    for text in texts:
        # A yes to what was asked before asks for nothing of its own: the write it agrees to is in the texts before.
        sentences = _without_yes(_sentences(text))
        amounts = _amounts(text)
        question = _is_question(text, sentences) and not any(_opening(words)[1] for words in sentences)
        # What happened in the plural, told or noted down, is also said in the present («han entrado»: «entran»); asked
        # about («¿quiénes han entrado…?»), it is what a read finds, as said.
        if not question:
            sentences = [_as_present(words, amounts) for words in sentences]
        # What asks to be done: every word but a verb that says what is not to be done («sin cambiar», ``_unasked``) or
        # what someone will do («I'll approve it», ``_foretold``).
        heard = [
            [word for at, word in enumerate(words) if not _unasked(words, at) and not _foretold(words, at)]
            for words in sentences
        ]
        joined = [f" {' '.join(words)} " for words in heard]
        found = {phrase for phrase in _PHRASES if any(f" {phrase} " in one for one in joined)}
        verbal = {word for phrase in found for word in phrase.split()}
        for said_as, phrase in _split_naming(sentences):
            found.add(phrase)
            verbal |= {said_as, *phrase.split()}
        said = {verb for verb, forms in VERBS.items() if not found.isdisjoint(forms)}
        acting: dict[str, frozenset[str]] = {}
        for words in heard:
            for word in words:
                if word not in verbal and (of := _verbs_of(word)):
                    acting[word] = of
        for word, of in list(acting.items()):
            if not _REGISTERS.isdisjoint(of) and not any(
                _registers(words, at) for words in heard for at, one in enumerate(words) if one == word
            ):
                acting[word] = of - _REGISTERS
        # Money taken out notes it down; a word said again of anything else still asks for what it did («saca 15 € de
        # la caja y saca el listado de clientes»).
        taken_out = {
            (index, at)
            for index, words in enumerate(heard)
            for at in range(len(words))
            if _takes_money_out(words, at, amounts)
        }
        for word in {heard[index][at] for index, at in taken_out}:
            said_so = {(index, at) for index, words in enumerate(heard) for at, one in enumerate(words) if one == word}
            acting[word] = _TAKEN_OUT if said_so <= taken_out else acting.get(word, frozenset()) | _TAKEN_OUT
        came_in = {
            (index, at)
            for index, words in enumerate(heard)
            for at in range(len(words))
            if _comes_in(words, at, amounts)
        }
        doing = _how_to(sentences)
        if doing and doing != "-" and doing not in acting:
            acting[doing] = _verbs_of(doing[:-1] + "a") or _verbs_of(doing[:-1] + "e")
        others |= said
        for of in acting.values():
            said |= of
            if of == _NOTES:
                noting |= _WRITTEN_ON
            else:
                others |= of
        for words in heard:
            for at, word in enumerate(words):
                if acting.get(word) == _NOTES:
                    noted |= _noted(words, at, extra)
                if word in acting:
                    (stating if _notes_what_happened(words, at, acting[word]) else asking).update(acting[word])
            switched |= _switched(words, found, verbal, extra)
        # A word that asks (a verb) names a thing only through its synonyms («cobra»: a sale); «show», «dame» none. So
        # does a verb not asked («sin cobrar»: still a sale); what someone will do is no verb asked, and names as any
        # word does.
        naming = [
            (word, _FOR_WHAT.isdisjoint(words[:at])) for words in sentences for at, word in enumerate(words)
            if (word not in verbal or word in _PHRASE_NAMES) and len(word) >= 3 and word not in STOP_WORDS
            and ((word not in acting and not _unasked(words, at)) or len(_concept(word, extra)) > 1)
            and not _comes_in(words, at, amounts)
        ]
        concepts |= {_concept(word, extra) for word, _ in naming}
        if any(heard[index][at] != _TAKE for index, at in taken_out):
            concepts.add(_concept(_OUTFLOW, extra))
        if came_in:
            concepts.add(_concept(_TILL, extra))
        direct |= {_concept(word, extra) for word, outside in naming if outside}
        concepts |= {group for phrase, group in phrases_named if any(phrase in one for one in joined)}
        acted, named_after = _objects(heard, acting, verbal, extra, taken_out | came_in)
        objects |= acted
        records |= named_after
        if question and not doing:
            asked_about = said - READ_VERBS
            about |= {_concept(word, extra) for word, of in acting.items() if of & asked_about}
            about |= {
                group
                for phrase, group in phrases_named
                if phrase.strip() in found and _phrase_verbs(phrase) & asked_about
            }
            said -= asked_about
        reading = reading or question or not said.isdisjoint(READ_VERBS)
        howto = howto or doing is not None
        verbs |= said
    return Asked(
        frozenset(concepts),
        frozenset(verbs),
        reading,
        frozenset(about),
        howto,
        frozenset(objects),
        frozenset(records),
        frozenset(direct),
        frozenset((noting - others) & verbs),
        frozenset(noted),
        frozenset(switched),
        frozenset((stating - asking) & _STATES & verbs),
    )
