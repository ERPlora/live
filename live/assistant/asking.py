"""Whether a word of ``VERBS`` asks for its action where it is said."""

from live.assistant.vocabulary import _FUTURE, _LEADING, _THEN


def asks_nothing(words: list[str], at: int, start: int) -> bool:
    """Whether the word ``words[at]`` asks for nothing where it is said, ``start`` being where what its sentence says
    starts (after greetings and the words of a request): what someone will do (after ``_FUTURE``: «knock 60% off the
    wine, I'll approve it», «it will turn on at nine»: the speaker's own doing; «will you…?» is a request), or a word that
    also names a thing or says what it is (``_LEADING``) where no command starts, neither first nor after ``_THEN``
    («delete that empty check», «drop the hold on table 6»; ERPlora/live#67)."""
    before = words[at - 1] if at > 0 else ""
    return before in _FUTURE or (words[at] in _LEADING and at != start and before not in _THEN)
