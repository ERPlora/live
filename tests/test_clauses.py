"""How the words of a sentence group: the actions a word asks for, where a phrase or another command starts, and the
verbs that ask for nothing because they say what is not to be done or what someone will do."""

import pytest

from live.assistant.clauses import (
    _determiner,
    _foretold,
    _infinitive,
    _not_even,
    _phrase_verbs,
    _starts_command,
    _unasked,
    _verbs_of,
)
from live.assistant.stemming import _sentences
from live.assistant.vocabulary import SWITCHES


def words(text: str) -> list[str]:
    return _sentences(text)[0]


def test_a_word_asks_for_its_actions_with_the_pronouns_of_a_command_too():
    assert _verbs_of("borrala") == _verbs_of("borra") != frozenset()
    assert _verbs_of("mesa") == frozenset()
    assert not _phrase_verbs("turn off").isdisjoint(SWITCHES)


def test_an_infinitive_and_a_determiner_are_told_apart():
    assert (_infinitive("borrarla"), _infinitive("borra")) == (True, False)
    assert (_determiner("esta"), _determiner("caja")) == (True, False)


@pytest.mark.parametrize(
    ("said", "verb", "unasked"),
    [
        ("sin cambiar los pedidos", "cambiar", True),
        ("sin tocar caja ni cambiar importes", "cambiar", True),
        ("cierra la caja sin contar ni cambiar el fondo y no me deja", "cambiar", True),
        ("sin contar ni cerrar la caja me deja", "cerrar", False),
        ("no puedo ni cerrar la caja", "cerrar", False),
    ],
)
def test_a_verb_after_sin_or_its_ni_is_not_to_be_done_unless_it_cannot_even_be_done(said, verb, unasked):
    sentence = words(said)

    assert _unasked(sentence, sentence.index(verb)) == unasked


def test_what_someone_cannot_even_do_after_a_ni_is_said_by_a_verb_after_it():
    sentence = words("sin contar ni cerrar la caja me deja")

    assert _not_even(sentence, sentence.index("cerrar"))


@pytest.mark.parametrize(
    ("said", "word", "starts"),
    [
        ("cobra la mesa 4 y muestra los pedidos", "muestra", True),
        ("cobra la mesa y dime el total", "dime", True),
        ("cobra la mesa de muestra", "muestra", False),
        ("la primera lista", "lista", False),
    ],
)
def test_another_command_starts_after_then_or_with_its_pronouns(said, word, starts):
    sentence = words(said)

    assert _starts_command(sentence, sentence.index(word)) == starts


def test_what_someone_will_do_is_no_verb_asked():
    assert _foretold(words("it will turn on at nine"), 2)
    assert not _foretold(words("turn on the alarm at nine"), 0)
