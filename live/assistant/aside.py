"""What a text names in a sentence of its own that asks for nothing (``named_aside``)."""

from collections.abc import Iterable

from live.assistant.reading import _verbs_of
from live.assistant.stemming import _concept, _groups, _sentences
from live.assistant.vocabulary import _PHRASES, STOP_WORDS


def named_aside(texts: Iterable[str], synonyms: Iterable[Iterable[str]] = ()) -> frozenset[frozenset[str]]:
    """What ``texts`` name in a sentence with no verb of ``VERBS``, as a comma leaves what a command checks first:
    «activa el envío real a la AEAT, comprobando antes que la cuenta y la autorización estén listas» names the check
    and the authorisation aside, not as what it turns on (ERPlora/live#76). What a thing is of, said in its sentence
    («desactiva el control de stock»), is not aside."""
    extra = _groups(synonyms)
    return frozenset(
        _concept(word, extra)
        for text in texts
        for words in _sentences(text)
        if not _asks(words)
        for word in words
        if len(word) >= 3 and word not in STOP_WORDS
    )


def _asks(words: list[str]) -> bool:
    """Whether ``words`` say a verb of ``VERBS``, in one word or in several («turn on»)."""
    said = f" {' '.join(words)} "
    return any(_verbs_of(word) for word in words) or any(f" {phrase} " in said for phrase in _PHRASES)
