"""Money said in a sentence: the amounts said with their sign (``_amounts``), money taken out or come in, and a compound
past read in its present unless money follows it (``_as_present``)."""

from collections.abc import Collection

from live.assistant.clauses import _determiner, _verbs_of
from live.assistant.stemming import _unclitic
from live.assistant.vocabulary import (
    _COMES_IN,
    _CURRENCIES,
    _HAVE,
    _OUT,
    _PARTICIPLE,
    _PRESENT,
    _TAKE,
    _TAKES_OUT,
    _WHERE,
    _WITH_ITS_SIGN,
)


def _amounts(text: str) -> frozenset[str]:
    """The numbers ``text`` says with their currency's sign («15 €», «€15», «12,50 €» → «15», «12»)."""
    return frozenset(before or after for before, after in _WITH_ITS_SIGN.findall(text))


def _money(words: list[str], at: int, amounts: Collection[str]) -> bool:
    """Whether ``words[at]`` is money: a number said with its currency's sign (``amounts``) or name («50 euros»). Any
    other number says how many («saca 2 copias», «take 5 out of stock»)."""
    if at >= len(words) or not words[at].isdigit():
        return False
    return words[at] in amounts or (at + 1 < len(words) and words[at + 1] in _CURRENCIES)


def _money_after(words: list[str], at: int, amounts: Collection[str]) -> bool:
    """Whether money (``_money``) is said right after ``words[at]`` or after where it goes or comes from, said first
    («15 € de la caja», «de la caja 15 €», «en caja 100 €»)."""
    money = at + 1
    if money < len(words) and words[money] in _WHERE:
        money += 1
        while money < len(words) and _determiner(words[money]):
            money += 1
        money += 1
    return _money(words, money, amounts)


def _comes_in(words: list[str], at: int, amounts: Collection[str]) -> bool:
    """Whether the word ``words[at]`` says money came in (``_COMES_IN``): «entran 100 €», «han entrado en caja 100 €»
    (``_money_after``)."""
    return words[at] in _COMES_IN and _money_after(words, at, amounts)


def _takes_money_out(words: list[str], at: int, amounts: Collection[str]) -> bool:
    """Whether the word ``words[at]`` takes money out (``_TAKES_OUT``): «saca» right before the money or before where it
    comes from and then the money («saca 15 € de la caja», «sácame del cajón 20 €»), «take» before the money and its
    «out» («take 15 € out of the till», «take 15 euros out») or before «out» and the money («take out 15 €»)."""
    word = words[at]
    if word in _TAKES_OUT or _unclitic(word) in _TAKES_OUT:
        return _money_after(words, at, amounts)
    if word != _TAKE:
        return False
    if _money(words, at + 1, amounts):
        return _OUT in words[at + 2 : at + 4]
    return words[at + 1 : at + 2] == [_OUT] and _money(words, at + 2, amounts)


def _as_present(words: list[str], amounts: Collection[str]) -> list[str]:
    """``words`` with the present of each compound past in the plural (``_HAVE``) said before it: «han entrado» is read
    «entran han entrado». Not of money said right after the participle or after where it comes in (``_money_after``:
    «han entrado 100 €», «han entrado en caja 100 €») nor of a present that asks for an action («han cuadrado»)."""
    read: list[str] = []
    for at, word in enumerate(words):
        participle = words[at + 1] if at + 1 < len(words) else ""
        present = participle.removesuffix(_PARTICIPLE) + _PRESENT
        if (
            word in _HAVE
            and participle.endswith(_PARTICIPLE)
            and not _verbs_of(present)
            and not _money_after(words, at + 1, amounts)
        ):
            read.append(present)
        read.append(word)
    return read
