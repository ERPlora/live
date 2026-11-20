"""What a turn asks (asked): the things it names, the actions it asks for and whether it asks to know."""

import unicodedata
from collections.abc import Iterable
from typing import NamedTuple

from live.assistant.asking import describes
from live.assistant.clauses import (
    _foretold,
    _phrase_verbs,
    _starts_command,
    _unasked,
    _verbs_of,
)
from live.assistant.money import (
    _amounts,
    _as_present,
    _comes_in,
    _takes_money_out,
)
from live.assistant.naming import puts_name
from live.assistant.objects import (
    _noted,
    _objects,
    _switched,
)
from live.assistant.stemming import (
    _concept,
    _groups,
    _sentences,
    _synonyms,
    _unclitic,
)
from live.assistant.vocabulary import (
    _ARTICLES,
    _AUXILIARIES,
    _CLITICS,
    _CONFIRMS,
    _FOR_WHAT,
    _GREETINGS,
    _HOW_TO,
    _HOW_TO_LEADS,
    _INTERROGATIVE,
    _NAMING,
    _NOTES,
    _OUTFLOW,
    _PHRASE_NAMES,
    _PHRASES,
    _PUTS,
    _REGISTERED_FROM,
    _REGISTERS,
    _REQUESTS,
    _STATES,
    _TAKE,
    _TAKEN_OUT,
    _THAT,
    _THEN,
    _TILL,
    _WRITTEN_ON,
    _YES,
    QUESTION_WORDS,
    READ_VERBS,
    STOP_WORDS,
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
    dispositivo el nombre»; its pronouns too: «cámbiale a la tablet el nombre»), each with its verb as said; never a
    name the verb does not put (``puts_name``: «con el nombre», «cambia el precio del café muestra el nombre del
    cliente», «cámbiale al café el precio ni el nombre»), nor one after another command starts
    (``_starts_command``: «cambia el precio y dime el nombre del cliente», ERPlora/live#57) or after a verb that says
    what is not to be done (``_unasked``: «ponle otro precio sin cambiarle el nombre», ERPlora/live#60), which puts no
    name either («sin ponerle al menú el nombre»)."""
    found: set[tuple[str, str]] = set()
    for words in sentences:
        for at, word in enumerate(words):
            head = word if word in _NAMING else _unclitic(word)
            if head not in _NAMING or _unasked(words, at) or _foretold(words, at):
                continue
            end = next(
                (later for later in range(at + 1, len(words)) if _starts_command(words, later) or _unasked(words, later)),
                len(words),
            )
            for rest in _NAMING[head]:
                size = len(rest)
                if any(
                    tuple(words[later : later + size]) == rest and puts_name(words, at, later)
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
            start = len(words) - len(_opening(words)[0])
            for at, word in enumerate(words):
                if word not in verbal and not describes(words, at, start) and (of := _verbs_of(word)):
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
