"""``named_aside``: what a text names in a sentence of its own that asks for nothing (ERPlora/live#76)."""

import pytest

from live.assistant.aside import named_aside
from live.assistant.stemming import _concept, _groups, _plain
from tests.assistant_catalogue import CHECK


def concepts_of(*said: str, synonyms=()) -> frozenset[frozenset[str]]:
    extra = _groups(synonyms)
    return frozenset(_concept(_plain(word), extra) for word in said)


@pytest.mark.parametrize(
    ("said", "aside"),
    [
        # What a command checks first, after a comma, is named aside: it asks for nothing of its own.
        ("activa el envío real a la AEAT a partir de ahora, comprobando antes que la cuenta y la autorización estén "
         "listas", concepts_of("comprobando", "antes", "cuenta", "autorización", "estén", "listas", synonyms=CHECK)),
        ("turn on real filing with the AEAT from now on, checking first that the account and the authorisation are "
         "ready", concepts_of("checking", "first", "account", "authorisation", "ready", synonyms=CHECK)),
        # A sentence with a verb of its own asks for it: what it names is not aside.
        ("activa la web de reservas, exige email y permite elegir profesional a la clienta", frozenset()),
        ("activa las propinas y cierra la cuenta", frozenset()),
        # What a thing is of, in the same sentence, is said with it.
        ("desactiva el control de stock", frozenset()),
        ("desactiva las alertas de stock bajo", frozenset()),
        # A sentence that only names: aside, whatever said it before.
        ("desactívalos ya, los recordatorios", concepts_of("recordatorios")),
    ],
)
def test_what_a_sentence_that_asks_for_nothing_names_is_aside(said, aside):
    assert named_aside([said], CHECK) == aside
