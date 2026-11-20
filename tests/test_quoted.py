"""A quoted text changed for another quoted text is a text named: «cambia «Sin cilantro» por «Nada de cilantro»» is
read as «cambia el texto «Sin cilantro» por «Nada de cilantro»», so the change that takes a text comes first
(ERPlora/live#167)."""

import pytest

from tests.assistant_catalogue import NOISE, ranked, takes, tool


NOTE = "sale.quick_note.update"
#: The Hub's change of a quick note of the till, beside the writes that tie with it when nothing names what changes:
#: the noise's updates, whose names come first, the note's create, a product's change and a device's rename.
TILL_NOTES = [
    tool(NOTE, "Change the text or the position of a quick note of the till. Pass its current text in quick_note, or "
         "its id when already known.", input=takes("id", "quick_note", "text", "sort_order")),
    tool("sale.quick_note.create", "Add a quick note to the till: it becomes a chip of the line-note sheet.",
         input=takes("text", "sort_order")),
    tool("inventory.product.update", "Change a product, named by its id, SKU or name: its data.",
         input=takes("id", "name", "price")),
    tool("base.device.rename", "Names a device of this business.", input=takes("name")),
    *NOISE,
]


@pytest.mark.parametrize(
    ("phrase", "language"),
    [
        ("cambia «Sin cilantro» por «Nada de cilantro»", "es"),
        ('cambia "Sin cebolla" por "Nada de cebolla"', "es"),
        ("cambia “Sin cebolla” por “Nada de cebolla”", "es"),
        ("cambia «Sin cilantro» a «Nada de cilantro»", "es"),
        ("pon «Nada de cilantro» en vez de «Sin cilantro»", "es"),
        ("pon «Nada de cilantro» en lugar de «Sin cilantro»", "es"),
        ('change "Well done" to "Medium"', "en"),
        ("change 'No cilantro' to 'No coriander'", "en"),
        ("change ‘No cilantro’ to ‘No coriander’", "en"),
        ('change "Well done" with "Medium"', "en"),
        ('change "Well done" for "Medium"', "en"),
        ('set "Medium" instead of "Well done"', "en"),
    ],
)
def test_a_quoted_text_changed_for_another_offers_the_change_of_a_text_first(phrase, language):
    assert ranked(TILL_NOTES, phrase, language).index(NOTE) == 0


@pytest.mark.parametrize(
    ("phrase", "language"),
    [
        ("cambia el texto «Sin cilantro» por «Nada de cilantro»", "es"),
        ('change the text "Well done" to "Medium"', "en"),
    ],
)
def test_saying_it_is_a_text_still_offers_it_first(phrase, language):
    assert ranked(TILL_NOTES, phrase, language).index(NOTE) == 0


@pytest.mark.parametrize(
    "phrase",
    [
        # One text quoted, nothing put in its place.
        "cambia «Sin cilantro»",
        # Two texts, but neither said for the other.
        "cambia «Sin cilantro» y «Nada de cilantro»",
        # What is changed, or what is put in its place, is no quoted text: a product swapped on a check.
        "cambia el café por «Té verde»",
        "cambia «Café» por un té",
    ],
)
def test_without_one_quoted_text_said_for_another_nothing_names_a_text(phrase):
    assert ranked(TILL_NOTES, phrase).index(NOTE) > 3
