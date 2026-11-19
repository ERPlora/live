"""Whether a word of ``VERBS`` that also names a thing asks for its action where it is said."""

from live.assistant.vocabulary import _LEADING, _THEN


def describes(words: list[str], at: int, start: int) -> bool:
    """Whether the word ``words[at]``, one that also names a thing or says what it is (``_LEADING``), does so where it
    is said: where no command starts, neither first in what its sentence says (``start``, after greetings and the words
    of a request) nor after ``_THEN`` («delete that empty check», «drop the hold on table 6»; ERPlora/live#67)."""
    return words[at] in _LEADING and at != start and (at == 0 or words[at - 1] not in _THEN)
