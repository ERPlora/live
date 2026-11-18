"""What a turn offers when a verb is said after «sin» or «ni»: what is not to be done is not asked."""

import pytest

from live import assistant
from tests.assistant_catalogue import SWITCHING_OFF, SWITCHING_ON


@pytest.mark.parametrize(
    ("said", "verbs"),
    [
        ("borra el grupo Salsas sin cambiar los pedidos", {"delete", "remove"}),
        ("delete the Sauces group without changing the old orders", {"delete", "remove"}),
        # With its pronouns: an infinitive carries them at its end, as a command does.
        ("desactiva a Lucía en la agenda sin borrarla", SWITCHING_OFF),
        ("desactiva esa placa sin quitarle el PIN", SWITCHING_OFF),
        # A verb said in words, and a name put apart, are no more asked after «sin».
        ("desactiva el horario de Ana sin cambiar el nombre", SWITCHING_OFF),
        ("activa la tarifa sin ponerle al menú el nombre «Verano»", SWITCHING_ON),
        # Each ending of an infinitive: «-ar», «-er» («ponerle») and «-ir».
        ("cobra la mesa 4 sin imprimir el ticket", {"complete"}),
    ],
)
def test_a_verb_said_after_sin_is_not_asked(said, verbs):
    """«Sin cambiar los pedidos» says what is not to be done, as «without changing» does in English: the infinitive
    after «sin» asks for nothing, and every update that takes a ``sort_order`` stopped drowning the delete asked
    (ERPlora/live#60)."""
    assert assistant.asked([said]).verbs == verbs


def test_a_verb_asked_and_said_after_sin_is_still_asked():
    """What «sin» leaves out is the word after it, not every time it is said: «cambiar el precio» is asked, «sin
    cambiar el nombre» is no rename."""
    assert assistant.asked(["quiero cambiar el precio sin cambiar el nombre"]).verbs == {"change", "set", "update"}


@pytest.mark.parametrize(
    ("said", "asked"),
    [
        ("ponle al café otro precio sin cambiarle el nombre", "ponle al café otro precio"),
        ("ponle precio nuevo al café sin cambiar el nombre", "ponle precio nuevo al café"),
        ("ponle otro precio sin cambiarle al café el nombre", "ponle otro precio"),
    ],
)
def test_a_name_not_to_be_changed_is_not_put_by_the_verb_asked_before(said, asked):
    """«Ponle al café otro precio sin cambiarle el nombre» renames nothing: the name said after the verb that is not
    asked is not the one «ponle» puts, as it was not when that verb started another command (ERPlora/live#57)."""
    heard = assistant.asked([said]).verbs
    assert "rename" not in heard
    assert heard == assistant.asked([asked]).verbs


def test_a_read_said_after_sin_asks_to_know_nothing():
    said = assistant.asked(["cierra la caja sin contar el efectivo"])
    assert (said.verbs, said.reading) == ({"close"}, False)


@pytest.mark.parametrize(
    ("said", "thing"),
    [
        ("sin cambiar los pedidos borra el grupo Salsas", "grupo"),
        # The same verb, asked after: what it acts on is what follows the one asked.
        ("sin cambiar los pedidos quiero cambiar el precio del café", "precio"),
    ],
)
def test_a_verb_said_after_sin_is_no_command_acting_on_what_follows(said, thing):
    """What the command acts on is what its verb names after it: «sin cambiar los pedidos» acts on nothing."""
    assert assistant.asked([said]).objects == {assistant._concept(thing)}


def test_a_verb_said_after_sin_names_only_what_its_synonyms_name():
    """«¿Queda alguna mesa sin cobrar?» asks for the checks still to charge: «cobrar» is no charge asked, and it still
    names the sale, as a verb does by its synonyms; «sin cambiar» names nothing."""
    said = assistant.asked(["queda alguna mesa sin cobrar"])
    assert "complete" not in said.verbs
    assert assistant._concept("venta") in said.concepts
    unchanged = assistant.asked(["borra el grupo Salsas sin cambiar los pedidos"])
    assert assistant._concept("cambiar") not in unchanged.concepts


def test_a_word_after_sin_that_is_no_verb_still_names():
    """«Sin azúcar» ends like an infinitive and is no verb: it names what it names."""
    assert assistant._concept("azucar") in assistant.asked(["pon un café sin azúcar en la mesa 4"]).concepts


def test_a_verb_that_starts_a_sentence_ending_in_sin_is_asked():
    """Dictation cut short («cambiar el precio del café sin…»): the verb has no «sin» before it."""
    assert assistant.asked(["cambiar el precio del café sin"]).verbs == {"change", "set", "update"}


def test_only_a_verbs_infinitive_after_sin_is_not_asked():
    """A word of ``VERBS`` that names a thing after «sin» («sin lista de precios») is read as anywhere: only an
    infinitive says what is not to be done."""
    assert assistant.asked(["borra las tarifas sin lista de precios"]).verbs == {"delete", "list", "remove"}


@pytest.mark.parametrize(
    ("said", "verbs"),
    [
        # The three readings of ERPlora/live#74: «ni cambiar» reads as «sin cambiar» does.
        ("marca como cobrada la factura, sin tocar caja ni cambiar importes", set()),
        ("marca como cobrada la factura, sin cambiar importes", set()),
        ("sin quitarle el PIN ni borrar su cuenta", set()),
        # With the verb asked before, and with its pronouns after «ni».
        ("desactiva esa placa sin quitarle el PIN ni borrar su cuenta", SWITCHING_OFF),
        ("sin tocar la caja ni borrarla", set()),
        # Each ending of an infinitive after «ni»: «-ar» above, «-er» («ponerle») and «-ir».
        ("cobra la mesa 4 sin imprimir el ticket ni ponerle propina", {"complete"}),
        ("cobra la mesa 4 sin tocar la caja ni imprimir el ticket", {"complete"}),
        # One «ni» after another goes on with the same «sin».
        ("sin tocar caja ni cambiar importes ni borrar nada", set()),
    ],
)
def test_a_verb_said_after_ni_that_goes_on_from_sin_is_not_asked(said, verbs):
    """«Sin tocar caja ni cambiar importes» says two things not to be done: the infinitive after «ni» goes on from the
    «sin» before it, so it asks for nothing either, as the one right after «sin» (ERPlora/live#60). Read as asked, every
    write that changes something came before marking the invoice paid (ERPlora/live#74)."""
    assert assistant.asked([said]).verbs == verbs


def test_a_verb_said_after_ni_that_goes_on_from_sin_is_no_command_acting_on_what_follows():
    """What the command acts on is what its verb names after it: «ni cambiar los precios» acts on nothing."""
    said = assistant.asked(["sin tocar la caja ni cambiar los precios borra el grupo Salsas"])
    assert said.objects == {assistant._concept("grupo")}


def test_a_verb_said_after_ni_that_goes_on_from_sin_puts_no_name():
    """«Ni ponerle al menú el nombre» puts no name, as «sin ponerle al menú el nombre» does not."""
    assert assistant.asked(["activa la tarifa sin tocar los precios ni ponerle al menú el nombre «Verano»"]).verbs == (
        SWITCHING_ON
    )


def test_a_verb_said_after_ni_that_goes_on_from_sin_names_only_what_its_synonyms_name():
    """«¿Queda alguna mesa sin abrir ni cobrar?»: «cobrar» is no charge asked, and it still names the sale."""
    said = assistant.asked(["queda alguna mesa sin abrir ni cobrar"])
    assert "complete" not in said.verbs
    assert assistant._concept("venta") in said.concepts


@pytest.mark.parametrize(
    "said",
    [
        # «ni» alone is «not even»: what the person cannot do is what they ask for help with.
        "no sé ni cambiar el precio del café",
        # A «sin» after it goes on from nothing before: only what follows it is not asked.
        "no sé ni cambiar el precio del café sin borrar el producto",
    ],
)
def test_a_verb_said_after_ni_with_no_sin_before_is_asked(said):
    """Only a «ni» that goes on from a «sin» before it in the sentence says what is not to be done."""
    assert assistant.asked([said]).verbs == {"change", "set", "update"}


@pytest.mark.parametrize(
    ("said", "verbs"),
    [
        # The «sin» before says how a thing is («una mesa sin cobrar»), and «no puedo ni…» is «not even»: asked.
        ("tengo una mesa sin cobrar y no puedo ni cerrar la caja", {"close"}),
        ("el café está sin precio y no sé ni cambiar el precio", {"change", "set", "update"}),
        ("hay un grupo sin opciones y no consigo ni borrarlo", {"delete", "remove"}),
        # A «sin» after the «no» is the one the «ni» goes on from.
        ("no me avises y cierra la caja sin contar ni cambiar el fondo", {"close"}),
    ],
)
def test_a_verb_said_after_ni_is_asked_when_a_no_comes_between_it_and_the_sin_before(said, verbs):
    """«No puedo ni cerrar la caja» asks for help closing the till, whatever was said «sin» something before: a «no»
    between the «sin» and the «ni» makes the «ni» «not even», so its verb is asked, as with no «sin» at all."""
    assert assistant.asked([said]).verbs == verbs


def test_only_a_verbs_infinitive_after_ni_is_not_asked():
    """A word of ``VERBS`` that names a thing after «ni» («sin precios ni lista») is read as anywhere, as after «sin»:
    only an infinitive says what is not to be done."""
    assert assistant.asked(["borra las tarifas sin precios ni lista"]).verbs == {"delete", "list", "remove"}


@pytest.mark.parametrize(
    ("said", "verbs"),
    [
        # The reading of ERPlora/live#81: a comma before «ni», as people write it.
        ("marca como cobrada la factura, sin tocar caja, ni cambiar importes", set()),
        ("sin quitarle el PIN, ni borrar su cuenta", set()),
        ("desactiva esa placa sin quitarle el PIN, ni borrar su cuenta", SWITCHING_OFF),
        ("sin tocar caja, ni cambiar importes, ni borrar nada", set()),
        # A space before the comma, and «Ni» as dictation writes it.
        ("sin tocar la caja , ni borrarla", set()),
        ("sin tocar caja, Ni cambiar importes", set()),
        # The comma at the end of a line, as a message of two lines has it.
        ("sin tocar caja,\nni cambiar importes", set()),
    ],
)
def test_a_verb_said_after_a_comma_and_ni_that_goes_on_from_sin_is_not_asked(said, verbs):
    """«Sin tocar caja, ni cambiar importes» says the same as without the comma: two things not to be done. The comma
    cut the sentence before the «ni», which then went on from no «sin» and asked to change (ERPlora/live#81)."""
    assert assistant.asked([said]).verbs == verbs


@pytest.mark.parametrize(
    ("with_comma", "without"),
    [
        ("borra el grupo Salsas sin tocar los pedidos, ni cambiar los precios",
         "borra el grupo Salsas sin tocar los pedidos ni cambiar los precios"),
        ("activa la tarifa sin tocar los precios, ni ponerle al menú el nombre «Verano»",
         "activa la tarifa sin tocar los precios ni ponerle al menú el nombre «Verano»"),
        ("queda alguna mesa sin abrir, ni cobrar", "queda alguna mesa sin abrir ni cobrar"),
    ],
)
def test_a_comma_before_ni_is_read_as_said_without_it(with_comma, without):
    """Verbs, the thing acted on, the name put and what is named: a comma before «ni» changes none of them."""
    assert assistant.asked([with_comma]) == assistant.asked([without])


@pytest.mark.parametrize(
    ("said", "verbs"),
    [
        # With no «sin» before, the «ni» after a comma is «not even», as without the comma.
        ("no sé, ni cambiar el precio del café", {"change", "set", "update"}),
        # A «no» between the «sin» and the «ni» still makes it «not even» (ERPlora/live#83).
        ("tengo una mesa sin cobrar y no puedo, ni cerrar la caja", {"close"}),
        # Only a comma: after a full stop, «Ni…» starts a sentence of its own.
        ("la mesa 4 se fue sin pagar. Ni cerrar la caja puedo ahora", {"close"}),
        # Nor a comma with anything else that ends a sentence.
        ("la mesa 4 se fue sin pagar..., ni cerrar la caja puedo ahora", {"close"}),
    ],
)
def test_a_verb_said_after_a_comma_and_ni_is_asked_when_it_goes_on_from_no_sin(said, verbs):
    assert assistant.asked([said]).verbs == verbs


@pytest.mark.parametrize(
    "said",
    [
        "cámbiale al café el precio, ni el nombre ni la foto",
        "ponle otro precio al café, ni el nombre ni la foto",
        # A «sin» of a sentence further back is none for the «ni» to go on from.
        "sin prisa, cámbiale al café el precio, ni el nombre ni la foto",
    ],
)
def test_a_comma_before_ni_that_goes_on_from_no_sin_still_ends_the_sentence(said):
    """«Cámbiale al café el precio, ni el nombre ni la foto» changes the price alone: with no «sin» for the «ni» to go
    on from, the comma still ends the sentence, and «el nombre» after it is no name put by «cámbiale»."""
    assert "rename" not in assistant.asked([said]).verbs


def test_only_the_word_ni_after_a_comma_goes_on_with_the_sentence():
    """Only what starts with the word «ni» goes on: «ninguno» starts like it, and a «ni» later on starts nothing."""
    assert len(assistant._sentences("cierra la caja sin contar, ni cambiar el fondo")) == 1
    assert len(assistant._sentences("cierra la caja sin contar, ninguno ha contado el fondo")) == 2
    assert len(assistant._sentences("cierra la caja sin contar, no toques ni el fondo")) == 2


@pytest.mark.parametrize(
    ("said", "verbs"),
    [
        # The readings of ERPlora/live#86: what someone cannot even do, with no «no» between the «sin» and the «ni».
        ("tengo una mesa sin cobrar, ni cerrar la caja me deja", {"close"}),
        ("tengo una mesa sin cobrar ni cerrar la caja me deja", {"close"}),
        ("quedan mesas sin cobrar, ni cerrar puedo la caja", {"close"}),
        ("el cliente se fue sin pagar, ni cancelar la reserva pudo", {"cancel"}),
        # With its pronouns, and one «ni» after another, each «not even».
        ("la tarta sale sin stock, ni editarla puedo", {"update"}),
        ("tengo una mesa sin cobrar, ni cerrar la caja ni abrirla puedo", {"close", "open"}),
    ],
)
def test_a_verb_said_after_ni_is_asked_when_a_verb_after_it_says_it_cannot_even_be_done(said, verbs):
    """«Tengo una mesa sin cobrar, ni cerrar la caja me deja» asks for help closing the till: the verb after the
    infinitive («me deja», «puedo», «pudo») says it cannot even be done, as «no puedo ni cerrar la caja» says it, and
    the «ni» is «not even», not one more thing not to be done after the «sin» (ERPlora/live#86)."""
    assert assistant.asked([said]).verbs == verbs


@pytest.mark.parametrize(
    "cannot",
    ["puedo", "puedes", "puede", "podemos", "pueden", "pude", "pudo", "podía", "he podido",
     "consigo", "consigue", "conseguí", "consiguió", "he conseguido",
     "me deja", "te deja", "le deja", "nos deja", "les deja", "me dejan", "me dejó", "me dejaba"],
)
def test_each_form_of_a_verb_of_what_cannot_be_done_makes_ni_not_even(cannot):
    """Each form of «poder», «conseguir» and «dejar» (after whom it lets) said after the infinitive after «ni»."""
    assert assistant.asked([f"tengo una mesa sin cobrar, ni cerrar la caja {cannot}"]).verbs == {"close"}


@pytest.mark.parametrize(
    ("said", "verbs"),
    [
        # «Dejar» that leaves a thing («lo dejo»), not that lets someone: the «ni» goes on from the «sin».
        ("tengo una mesa sin cobrar ni cerrar la caja lo dejo hasta mañana", set()),
        # A verb with an infinitive of its own after it says what that one can do («puedo cuadrar»): «cuadrar» is
        # asked, «cambiar» still is not.
        ("márcala cobrada sin tocar caja ni cambiar importes y así puedo cuadrar la caja", {"check", "stats"}),
        # Its pronouns too («cuadrarla»).
        ("márcala cobrada sin tocar caja ni cambiar importes y así puedo cuadrarla", {"check", "stats"}),
        # Only a verb said after the infinitive counts: one said before the «sin» is not about what follows the «ni».
        ("el camarero me deja la mesa sin cobrar ni cerrar la caja", set()),
        # After a word that opens another clause, what someone can do is that clause's, no «not even».
        ("márcala cobrada sin tocar caja ni cambiar importes si puede", set()),
        ("cierra la caja sin contar ni cambiar el fondo que me deja el turno de tarde", {"close"}),
        ("cierra la caja sin contar ni cambiar el fondo porque no puedo", {"close"}),
        ("cierra la caja sin contar ni cambiar el fondo pero no me deja", {"close"}),
    ],
)
def test_a_verb_said_after_ni_that_goes_on_from_sin_is_not_asked_whatever_verb_comes_after(said, verbs):
    """Only «poder», «conseguir» or «dejar» said of what cannot be done make the «ni» «not even»: the enumerations of
    ERPlora/live#74 and live#81 still ask nothing."""
    assert assistant.asked([said]).verbs == verbs


@pytest.mark.parametrize(
    ("said", "verbs"),
    [
        # The readings of ERPlora/live#93: a command before the «sin», then a complaint or an aside.
        ("quiero cerrar la caja sin contar ni cambiar el fondo y no me deja", {"close"}),
        ("cierra la caja sin contar ni cambiar el fondo como siempre se puede", {"close"}),
        ("da de baja a Ana sin borrar sus turnos ni cambiar su rol y me deja de salir en el cuadrante",
         {"terminate", "withdraw"}),
        ("anula el pedido sin cobrar ni imprimir el ticket me deja el camarero", {"cancel", "void"}),
        # Its pronouns too.
        ("anúlalo sin cobrar ni imprimir el ticket me deja el camarero", {"cancel", "void"}),
        # The «sin» the «ni» goes on from is the last one: a dictated «sin prisa» before the command is another.
        ("sin prisa cierra la caja sin contar ni cambiar el fondo y no me deja", {"close"}),
    ],
)
def test_a_verb_said_after_ni_is_not_asked_when_an_action_is_asked_before_the_sin(said, verbs):
    """«Quiero cerrar la caja sin contar ni cambiar el fondo y no me deja» asks to close the till without changing the
    float: with an action asked before the «sin», the «ni» goes on with what is not to be done, and the «me deja» after
    it is a complaint about the whole, not «not even» (ERPlora/live#93)."""
    assert assistant.asked([said]).verbs == verbs


def test_what_someone_can_do_after_cuando_is_that_clauses():
    """«…cuando puedes» opens another clause, as «si» or «porque» do: what someone can do is that clause's, no «not
    even», though «marca» is no verb asked before the «sin» (ERPlora/live#93)."""
    said = "marca como cobrada la factura sin tocar caja ni cambiar importes cuando puedes"
    assert assistant.asked([said]).verbs == set()


@pytest.mark.parametrize(
    ("said", "verbs"),
    [
        # The complaints of ERPlora/live#86 with the endings of ERPlora/live#93: nothing is asked before the «sin».
        ("tengo una mesa sin cobrar ni cerrar la caja y no me deja", {"close"}),
        ("la mesa 4 sigue sin cobrar ni imprimir el ticket me deja el camarero", {"print"}),
        ("Ana sigue sin turnos ni cambiar su rol me deja", {"change", "set", "update"}),
        # A verb said as what is not to be done asks for nothing before the «sin» either.
        ("la mesa se fue sin pagar y sigue sin cobrar, ni cerrar la caja me deja", {"close"}),
        # A verb's phrase asks only said as its own words: «queda de baja» says no «da de baja».
        ("Ana se queda de baja sin turnos ni cambiar su rol me deja", {"change", "set", "update"}),
        # Only what is said before the «sin» is asked before it.
        ("tengo una mesa sin cobrar que muestra la cuenta, ni cerrar la caja me deja", {"list", "close"}),
        # «Cuando» after what lets: still said of what cannot be done.
        ("tengo una mesa sin cobrar ni cerrar la caja me deja cuando hay cola", {"close"}),
        # «Como» opens no other clause: «como antes» says how.
        ("tengo mesas sin cobrar ni cerrar la caja como antes puedo", {"close"}),
        # A «sin» said after the «ni» is not the one it goes on from.
        ("tengo una mesa sin cobrar ni cerrar la caja me deja sin el ticket", {"close"}),
    ],
)
def test_a_verb_said_after_ni_is_still_not_even_when_nothing_is_asked_before_the_sin(said, verbs):
    """With no action asked before the «sin», «me deja» or «puedo» after the infinitive still says it cannot even be
    done (ERPlora/live#86)."""
    assert assistant.asked([said]).verbs == verbs
