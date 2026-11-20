"""What a command acts on: the thing its verb names or the first one after it, what a word that notes something down
notes, and what a switch turns on or off."""

import pytest

from live.assistant.clauses import _verbs_of
from live.assistant.money import _amounts, _takes_money_out
from live.assistant.objects import _named_after_where, _noted, _objects, _puts_where, _switched
from live.assistant.stemming import _concept, _sentences


def words(text: str) -> list[str]:
    return _sentences(text)[0]


def concepts(*said: str) -> set[frozenset[str]]:
    return {_concept(word, ()) for word in said}


@pytest.mark.parametrize(
    ("said", "acted", "named_after"),
    [
        ("crea la carpeta facturas", concepts("carpeta"), concepts("carpeta")),
        ("borra el cliente ana", concepts("cliente"), concepts("cliente")),
        ("cobra la mesa 4", concepts("cobra"), set()),
        ("anota en el turno una salida", concepts("salida"), concepts("salida")),
        ("saca 15 € de la caja para comprar hielo", set(), set()),
    ],
)
def test_a_command_acts_on_its_verbs_own_thing_or_the_first_one_named_after_it(said, acted, named_after):
    sentence = words(said)
    acting = {word: _verbs_of(word) for word in sentence if _verbs_of(word)}
    of_money = {(0, at) for at in range(len(sentence)) if _takes_money_out(sentence, at, _amounts(said))}

    assert _objects([sentence], acting, (), (), of_money) == (acted, named_after)


def test_where_something_is_put_said_first_is_skipped_to_what_is_put():
    sentence = words("anota en el turno de barra una entrada")

    assert [at for at in range(len(sentence)) if _puts_where(sentence, at)] == [1]
    assert _named_after_where(sentence, 1) == sentence.index("entrada")


def test_a_word_that_notes_something_down_notes_all_it_names_but_where_it_is_noted():
    sentence = words("apunta en la ficha de ana garcía su teléfono nuevo")

    assert _noted(sentence, 0, ()) == concepts("ana", "garcia", "telefono", "nuevo")


@pytest.mark.parametrize(
    ("said", "phrases", "switched"),
    [
        ("desactiva los recordatorios de las citas", set(), {frozenset(concepts("recordatorios"))}),
        ("desactiva de momento los recordatorios", set(), {frozenset(concepts("momento", "recordatorios"))}),
        ("turn off the appointment reminders", {"turn off"}, {frozenset(concepts("appointment", "reminders"))}),
    ],
)
def test_a_switch_turns_on_or_off_what_is_named_after_it(said, phrases, switched):
    verbal = {word for phrase in phrases for word in phrase.split()}

    assert _switched(words(said), phrases, verbal, ()) == switched
