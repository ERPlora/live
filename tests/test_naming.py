"""A name said apart from the verb that puts it («ponle al menú el nombre…»): which verb puts it, and when the verb
has an object of its own said before it and puts no name."""

import pytest

from live import assistant
from live.assistant.vocabulary import VERBS
from tests.assistant_catalogue import MENU, ranked

#: Every verb said in one word but those that put a name themselves («… cambia el nombre del cliente» renames).
ONE_WORD_VERBS = sorted(
    {form for forms in VERBS.values() for form in forms if " " not in form}
    - {phrase.split()[0] for phrase in VERBS["rename"]}
)


@pytest.mark.parametrize(
    ("said", "verbs"),
    [
        # Dictated with no «y»: the second command asks for the name, as «… y muestra el nombre del cliente» does.
        ("cámbiale al café el precio muestra el nombre del cliente", {"change", "list", "set", "update"}),
        ("cámbiale al menú de la terraza el precio muestra el nombre del cliente", {"change", "list", "set", "update"}),
        ("cámbiale ya el precio al café muestra el nombre del cliente", {"change", "list", "set", "update"}),
        ("change for the coffee the price show the name of the customer", {"change", "list", "set", "update"}),
        ("change on the menu of the terrace the price list the name of the customer", {"change", "list", "set", "update"}),
        # The name that «ni» leaves alone, with a comma or not, after a «sin» or not.
        ("cámbiale al café el precio ni el nombre ni la foto", {"change", "set", "update"}),
        ("cámbiale al café el precio sin tocar la foto ni el nombre", {"change", "set", "update"}),
        ("cámbiale al café el precio sin tocar la foto, ni el nombre", {"change", "set", "update"}),
    ],
)
def test_a_verb_with_its_object_after_whom_it_is_done_to_puts_no_name(said, verbs):
    """«Cámbiale al café el precio …» changes the price: «el precio» after «al café» is the verb's own object, as
    right after the verb («cambia el precio del café …»), so «el nombre» said later is no name it puts."""
    assert assistant.asked([said]).verbs == verbs


@pytest.mark.parametrize(
    "template",
    [
        "cámbiale al café el precio {} el nombre del cliente",
        "change for the coffee the price {} the name of the customer",
        "cámbiale al café el precio {} el nombre ni la foto",
        "cámbiale al café el precio sin tocar la foto ni {} el nombre",
    ],
)
def test_no_verb_said_after_the_object_makes_the_name_a_rename(template):
    assert [verb for verb in ONE_WORD_VERBS if "rename" in assistant.asked([template.format(verb)]).verbs] == []


@pytest.mark.parametrize(
    "said",
    [
        # What it is done to is said with how many, or with a number.
        "ponle a todas las mesas el nombre «Terraza»",
        "change for all the tables the name to Terrace",
        "cámbiale a la mesa 4 de la terraza el nombre",
        # Or with a clause of its own, whose articles are of that clause.
        "ponle a la mesa que tiene la reserva el nombre «Ana»",
        "pon a la tablet que lleva la caja el nombre «Barra»",
    ],
)
def test_the_name_put_after_whom_it_is_done_to_still_renames(said):
    assert {"rename", "set", "update"} <= assistant.asked([said]).verbs


@pytest.mark.parametrize(
    ("said", "language"),
    [
        ("cámbiale al menú el precio muestra el nombre del cliente", "es"),
        ("change for the menu the price show the name of the customer", "en"),
        ("cámbiale al menú el precio ni el nombre ni la foto", "es"),
        ("cámbiale al menú el precio sin tocar la foto ni el nombre", "es"),
        ("cámbiale al menú el precio sin tocar la foto, ni el nombre", "es"),
    ],
)
def test_the_change_asked_is_offered_and_no_rename(said, language):
    actions = [name.split(".")[-1] for name in ranked(MENU, said, language)]
    assert "rename" not in actions[: actions.index("update") + 1], actions[:5]
