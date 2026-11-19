"""Whether a name said apart from the verb that puts names («ponle al menú el nombre…») is the one that verb puts."""

from live.assistant.vocabulary import (
    _DONE_TO,
    _FOUND_BY,
    _OTHER_CLAUSE,
    _OWN_OBJECT,
    STOP_WORDS,
)


def _object_before(words: list[str], at: int, name_at: int) -> bool:
    """Whether the verb ``words[at]`` says an object of its own before ``words[name_at]``: an article (``_OWN_OBJECT``)
    right after the verb or after a word that names what it is done to («cambia el precio…», «cámbiale al café el
    precio…», «cámbiale ya el precio…»), never after one that opens what it is done to or names nothing by itself
    (``_DONE_TO``, ``STOP_WORDS``: «ponle a todas las mesas…»). The articles after a ``_OTHER_CLAUSE`` are of the clause
    it opens («ponle a la mesa que tiene la reserva…»)."""
    for later in range(at + 1, name_at):
        if words[later] in _OTHER_CLAUSE:
            return False
        before = words[later - 1]
        if words[later] in _OWN_OBJECT and before not in _DONE_TO and before not in STOP_WORDS:
            return True
    return False


def puts_name(words: list[str], at: int, name_at: int) -> bool:
    """Whether the name said at ``words[name_at]`` is the one the verb ``words[at]`` puts: not one a thing is found by
    (``_FOUND_BY``: «con el nombre»), nor one said after the verb's own object («cámbiale al café el precio muestra el
    nombre del cliente»: the name is what «muestra» asks for)."""
    return words[name_at - 1] not in _FOUND_BY and not _object_before(words, at, name_at)
