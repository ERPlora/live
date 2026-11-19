"""Whether a word of the verbs asks for its action where it is said (``live.assistant.asking``)."""

import pytest

from live.assistant.asking import asks_nothing


@pytest.mark.parametrize(
    ("words", "at", "start"),
    [
        (["knock", "60", "off", "the", "wine", "i", "ll", "approve", "it"], 7, 0),
        (["it", "will", "turn", "on", "at", "nine"], 2, 0),
        (["delete", "that", "empty", "check"], 2, 0),
        (["drop", "the", "hold", "on", "table", "6"], 2, 0),
        (["cobra", "la", "venta", "suelta"], 3, 0),
        (["abre", "una", "cuenta", "vacia"], 3, 0),
    ],
)
def test_what_someone_will_do_or_a_word_that_names_or_describes_asks_nothing(words, at, start):
    assert asks_nothing(words, at, start)


@pytest.mark.parametrize(
    ("words", "at", "start"),
    [
        (["empty", "the", "cart"], 0, 0),
        (["please", "hold", "ana", "s", "session"], 1, 1),
        (["cobra", "la", "mesa", "y", "suelta", "la", "sesion"], 4, 0),
        (["charge", "it", "and", "release", "the", "session"], 3, 0),
        (["will", "you", "approve", "it"], 2, 2),
        (["delete", "that", "check"], 0, 0),
        (["borra", "la", "cuenta", "vacia"], 0, 0),
    ],
)
def test_a_command_where_it_starts_asks_for_its_action(words, at, start):
    assert not asks_nothing(words, at, start)
