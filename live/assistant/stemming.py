"""The words of a turn cut to their stems and into sentences, and what each of them names."""

import unicodedata
from collections.abc import Iterable
from functools import lru_cache

from live.assistant.vocabulary import (
    _AFTER_PARTICLE,
    _APART_PREFIXES,
    _APART_WORDS,
    _BREAK_KEPT,
    _COMMANDS,
    _DOUBLING,
    _ENCLITICS,
    _ENDINGS,
    _IRREGULAR,
    _NOR,
    _NOT,
    _NOT_COMMANDS,
    _SPLIT,
    _THEN,
    _VERB_S_ENDINGS,
    _VERB_WORDS,
    _WHOLE,
    _WITHOUT,
    _WORD,
    STOP_WORDS,
    SYNONYMS,
)


def _plain(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def _unclitic(word: str) -> str | None:
    """The command ``word`` without the pronouns at its end («cobrale» → «cobra», «dime» → «di»), when what is left is
    a verb and the word is not another (``_NOT_COMMANDS``: «iniciales»); else ``None``."""
    if word in _NOT_COMMANDS:
        return None
    for clitic in _ENCLITICS:
        if word.endswith(clitic) and len(word) > len(clitic):
            rest = word[: -len(clitic)]
            if rest in _VERB_WORDS or rest in _IRREGULAR:
                return rest
    return None


def _apart(word: str) -> str | None:
    if word in _APART_WORDS:
        return _APART_WORDS[word]
    return next((kept for prefix, kept in _APART_PREFIXES if word.startswith(prefix)), None)


@lru_cache(maxsize=65_536)
def stem(word: str) -> str:  # noqa: C901
    """``word`` (plain: lowercase, no accents) cut to its stem, Spanish or English: the pronouns of a command off
    («cóbrale» is «cobra»), a plural «s» and one ending of a verb or a gender off, then five letters at most («vendí»,
    «vendido», «vendimos» → «vend»; «clientes», «client» → «clien»). The root keeps four letters, three for a plural
    («apps» → «app»; «mesa» is never «mes») and for a verb («sube», «subir» → «sub»); an English verb's doubled
    consonant goes with its ending («tagged» → «tag»); a word of ``_WHOLE`` stays whole and one kept apart
    (``_APART_WORDS``, ``_APART_PREFIXES``) has its own stem."""
    if word in _WHOLE:
        return word
    bare = _unclitic(word)
    verbal = bare is not None or word in _VERB_WORDS
    word = bare or word
    if word in _IRREGULAR:
        return _IRREGULAR[word]
    if (kept := _apart(word)) is not None:
        return kept
    for ending in _VERB_S_ENDINGS:
        if word.endswith(ending) and len(word) - len(ending) >= 4:
            return word[: -len(ending)][:5]
    if word.endswith("s") and len(word) >= 4:
        word = word[:-1]
        if (kept := _apart(word)) is not None:
            return kept
    root = 3 if verbal else 4
    for ending in _ENDINGS:
        if word.endswith(ending) and len(word) - len(ending) >= root:
            word = word[: -len(ending)]
            if ending in _DOUBLING and word[-1] == word[-2] and word[-1] not in "aeioulsfz":
                word = word[:-1]
            break
    return word[:5]


def _in_a_row(words: list[str]) -> list[str]:
    """``words`` with each switch said apart from its particle (``_SPLIT``: «turn the bookings off») said in a row, as
    ``VERBS`` has it («turn off the bookings»): the particle that ends the sentence or comes before a word that cannot be
    what it is said of (``_AFTER_PARTICLE``), never past a word that starts another command (``_THEN``: «switch the order
    to table 6 and leave the lights on»)."""
    for at, word in enumerate(words):
        if word not in _SPLIT:
            continue
        for later in range(at + 1, len(words)):
            if words[later] in _THEN:
                break
            if words[later] in _SPLIT[word] and (later + 1 == len(words) or words[later + 1] in _AFTER_PARTICLE):
                return [*words[: at + 1], words[later], *words[at + 1 : later], *_in_a_row(words[later + 1 :])]
    return words


def _sentences(text: str) -> list[list[str]]:
    """The plain words of ``text``, by sentence or quote (``_BREAK``), a noun at the start that is a command
    (``_COMMANDS``) said as its verb and a switch said apart from its particle said in a row (``_in_a_row``). A comma
    before a ``_NOR`` that goes on from a ``_WITHOUT`` of the sentence before (``_goes_on``) ends none: «sin tocar caja,
    ni cambiar importes» is «sin tocar caja ni cambiar importes» (ERPlora/live#81); with nothing for the «ni» to go on
    from («cámbiale el precio, ni el nombre»), it does."""
    found: list[list[str]] = []
    pieces = _BREAK_KEPT.split(text)
    for at in range(0, len(pieces), 2):
        words = _in_a_row(_WORD.findall(_plain(pieces[at])))
        if words and words[0] in _COMMANDS:
            verb, before = _COMMANDS[words[0]]
            if len(words) > 1 and words[1] in before:
                words[0] = verb
        if words and found and pieces[at - 1].strip() == "," and words[0] in _NOR and _goes_on(found[-1]):
            found[-1] = [*found[-1], *words]
        elif words:
            found.append(words)
    return found


def stems(text: str) -> set[str]:
    """The words of ``text`` that may name something, as their stems (``stem``): without accents, lowercase, of three
    letters or more and none that names nothing by itself (``STOP_WORDS``)."""
    return {
        stem(word) for words in _sentences(text) for word in words if len(word) >= 3 and word not in STOP_WORDS
    }


@lru_cache(maxsize=16_384)
def _stems_of(text: str) -> frozenset[str]:
    return frozenset(stems(text))


@lru_cache(maxsize=4_096)
def _taken(schema: type) -> frozenset[str]:
    """The stems of the data an operation's input ``schema`` takes, by their names (``price``, ``party_size``)."""
    return frozenset(stems(" ".join(name.replace("_", " ") for name in getattr(schema, "model_fields", {}))))


def _groups(synonyms: Iterable[Iterable[str]]) -> tuple[tuple[str, ...], ...]:
    return tuple(tuple(group) for group in synonyms)


@lru_cache(maxsize=64)
def _synonyms(extra: tuple[tuple[str, ...], ...] = ()) -> tuple[dict[str, frozenset[str]], tuple]:
    """Each stem of ``SYNONYMS`` and of the project's ``extra`` groups → the stems of every group it is in; and each
    phrase of them → the stems of its group's words."""
    index: dict[str, set[str]] = {}
    phrases: list[tuple[str, frozenset[str]]] = []
    for group in (*SYNONYMS, *extra):
        said = {stem(_plain(word)) for word in group if " " not in word}
        for one in said:
            index.setdefault(one, set()).update(said)
        phrases += [(f" {' '.join(_WORD.findall(_plain(word)))} ", frozenset(said)) for word in group if " " in word]
    return {one: frozenset(group) for one, group in index.items()}, tuple(phrases)


@lru_cache(maxsize=65_536)
def _concept(word: str, extra: tuple[tuple[str, ...], ...] = ()) -> frozenset[str]:
    """What the plain ``word`` names: its stem and those of its synonyms (``SYNONYMS`` and the project's ``extra``)."""
    one = stem(word)
    return _synonyms(extra)[0].get(one, frozenset()) | {one}


def _goes_on(words: list[str]) -> bool:
    """Whether a ``_NOR`` said after ``words`` goes on from a ``_WITHOUT`` among them: the last of ``_WITHOUT`` and
    ``_NOT`` said is a ``_WITHOUT``."""
    last = next((word for word in reversed(words) if word in _WITHOUT or word in _NOT), "")
    return last in _WITHOUT
