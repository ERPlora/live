"""Money said in a sentence: the amounts said with their sign, money taken out or come in, and a compound past read in
its present unless money follows it."""

import pytest

from live.assistant.money import _amounts, _as_present, _comes_in, _takes_money_out
from live.assistant.stemming import _sentences


def words(text: str) -> list[str]:
    return _sentences(text)[0]


def test_an_amount_is_a_number_said_with_its_currencys_sign():
    assert _amounts("saca 15 € de la caja y €20 del cajón, y 12,50 € más") == {"15", "20", "12"}
    assert _amounts("saca 2 copias del ticket") == frozenset()


@pytest.mark.parametrize(
    ("said", "taken_out"),
    [
        ("saca 15 € de la caja", True),
        ("sácame del cajón 20 €", True),
        ("take 15 € out of the till", True),
        ("take out 15 €", True),
        ("saca 2 copias del ticket", False),
        ("take 5 out of stock", False),
    ],
)
def test_a_word_takes_money_out_only_before_the_money(said, taken_out):
    assert _takes_money_out(words(said), 0, _amounts(said)) == taken_out


@pytest.mark.parametrize(
    ("said", "at", "came_in"),
    [
        ("entran 100 € de propina", 0, True),
        ("han entrado en caja 100 €", 1, True),
        ("entran 20 cafés", 0, False),
    ],
)
def test_money_comes_in_where_a_word_says_so_before_the_money(said, at, came_in):
    assert _comes_in(words(said), at, _amounts(said)) == came_in


@pytest.mark.parametrize(
    ("said", "read"),
    [
        ("han entrado 20 cafés", "entran han entrado 20 cafes"),
        ("han entrado 100 €", "han entrado 100"),
        ("han cuadrado la caja", "han cuadrado la caja"),
    ],
)
def test_a_compound_past_in_the_plural_is_also_read_in_its_present(said, read):
    assert _as_present(words(said), _amounts(said)) == read.split()
