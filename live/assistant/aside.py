"""What a text names in a clause of its own beside a command (``named_aside``)."""

from collections.abc import Iterable

from live.assistant.reading import _verbs_of
from live.assistant.stemming import _concept, _groups, _sentences
from live.assistant.vocabulary import _OTHER_CLAUSE, _PHRASES, STOP_WORDS

#: How a clause said beside a command opens, besides a word that opens another clause (``_OTHER_CLAUSE``: «que»): with
#: a gerund («comprobando», «viendo», «checking»).
_GERUNDS = ("ando", "iendo", "yendo", "ing")


def named_aside(texts: Iterable[str], synonyms: Iterable[Iterable[str]] = ()) -> frozenset[frozenset[str]]:
    """What ``texts`` name in a sentence that opens as a clause beside a command and asks for nothing of its own:
    «activa el envío real a la AEAT, comprobando antes que la cuenta y la autorización estén listas» names the check
    and the authorisation as what is checked first, not as what it turns on (ERPlora/live#76). A sentence that only
    names («desactívalos ya, los avisos») says what a pronoun stands for, and what a thing is of, said in its sentence
    («desactiva el control de stock»), is said with it: neither is aside."""
    extra = _groups(synonyms)
    return frozenset(
        _concept(word, extra)
        for text in texts
        for words in _sentences(text)
        if _beside(words)
        for word in words
        if len(word) >= 3 and word not in STOP_WORDS
    )


def _beside(words: list[str]) -> bool:
    """Whether ``words`` open as a clause beside a command (``_OTHER_CLAUSE``, ``_GERUNDS``) and say no verb of
    ``VERBS``, in one word or in several («turn on»)."""
    said = f" {' '.join(words)} "
    return (
        (words[0] in _OTHER_CLAUSE or words[0].endswith(_GERUNDS))
        and not any(_verbs_of(word) for word in words)
        and not any(f" {phrase} " in said for phrase in _PHRASES)
    )
