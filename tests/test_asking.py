"""Whether a word of the verbs that also names a thing asks for its action where it is said
(``live.assistant.asking``)."""

import pytest

from live.assistant.asking import describes


@pytest.mark.parametrize(
    ("words", "at", "start"),
    [
        (["delete", "that", "empty", "check"], 2, 0),
        (["drop", "the", "hold", "on", "table", "6"], 2, 0),
        (["publish", "the", "new", "release"], 3, 0),
        (["is", "the", "routing", "clear"], 3, 0),
        (["cobra", "la", "venta", "suelta"], 3, 0),
        (["abre", "una", "cuenta", "vacia"], 3, 0),
    ],
)
def test_such_a_word_where_no_command_starts_names_or_describes(words, at, start):
    assert describes(words, at, start)


@pytest.mark.parametrize(
    ("words", "at", "start"),
    [
        (["empty", "the", "cart"], 0, 0),
        (["please", "hold", "ana", "s", "session"], 1, 1),
        (["cobra", "la", "mesa", "y", "suelta", "la", "sesion"], 4, 0),
        (["charge", "it", "and", "release", "the", "session"], 3, 0),
        (["vacia", "la", "cesta"], 0, 0),
    ],
)
def test_such_a_word_where_a_command_starts_is_the_command(words, at, start):
    assert not describes(words, at, start)


@pytest.mark.parametrize(
    ("words", "at"),
    [
        (["borra", "la", "cuenta"], 0),
        (["delete", "that", "check"], 0),
        (["cobra", "y", "luego", "borra", "la", "cuenta"], 3),
    ],
)
def test_any_other_word_asks_for_its_action_wherever_it_is_said(words, at):
    assert not describes(words, at, 0)
