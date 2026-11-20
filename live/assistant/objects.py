"""What a command acts on (``_objects``), what a word that notes something down notes (``_noted``) and what each switch
turns on or off (``_switched``)."""

from collections.abc import Collection, Mapping

from live.assistant.clauses import _determiner, _phrase_verbs, _starts_command, _verbs_of
from live.assistant.stemming import _concept
from live.assistant.vocabulary import (
    _FOR_WHAT,
    _OF,
    _OTHER_CLAUSE,
    _PUTS,
    _THEN,
    _WHERE,
    _WITH_ITS_ARTICLE,
    STOP_WORDS,
    SWITCHES,
)


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
