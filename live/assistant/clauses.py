"""How the words of a sentence group: the actions a word asks for (``_verbs_of``), where a phrase or another command
starts, and the verbs that ask for nothing — said as what is not to be done (``_unasked``) or as what someone will do
(``_foretold``)."""

from live.assistant.stemming import _goes_on, _unclitic
from live.assistant.vocabulary import (
    _CAN,
    _DETERMINERS,
    _FILLERS,
    _FUTURE,
    _INFINITIVE,
    _LETS,
    _NOR,
    _NOT_VERBS,
    _OTHER_CLAUSE,
    _PHRASES,
    _PRONOUNS_AFTER,
    _THEN,
    _TO_WHOM,
    _VERB_OF,
    _WITH_PRONOUNS,
    _WITHOUT,
    STOP_WORDS,
    VERBS,
)


def _phrase_verbs(phrase: str) -> frozenset[str]:
    """The actions a verb said in words (`` set up ``) asks for."""
    return frozenset(verb for verb, forms in VERBS.items() if phrase.strip() in forms)


def _verbs_of(word: str) -> frozenset[str]:
    """The actions the plain ``word`` asks for: as said, or without the pronouns of a command («cóbrale»)."""
    found = _VERB_OF.get(word)
    if found is None and (bare := _unclitic(word)) is not None:
        found = _VERB_OF.get(bare)
    return found or frozenset()


def _determiner(word: str) -> bool:
    """Whether ``word`` opens a phrase of its own: a determiner (``_DETERMINERS``) or another word that names nothing
    by itself (``STOP_WORDS``: «esta», «unos», «sus»)."""
    return word in _DETERMINERS or word in STOP_WORDS


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
