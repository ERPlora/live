"""What a turn offers when it notes something down («anota», «apunta», «registra») or takes it away («retira»)."""

import pytest
from ninja import Schema

from live import assistant
from tests.assistant_catalogue import (
    CHECK,
    NOISE,
    REGISTERED_AT_THE_TILL,
    CustomerIn,
    MovementIn,
    ProductIn,
    ranked,
    till_apps,
    tool,
)


#: What «anota» asks for: writing something new down, adding to what there is or writing on it; what is named says which.
NOTING = {"create", "add", "update"}
#: What «retira» asks for: taking something away, retiring it or withdrawing it; the thing named says which.
TAKING_AWAY = {"delete", "remove", "retire", "withdraw"}


@pytest.mark.parametrize(
    ("said", "language", "actions"),
    [
        ("anota en la cita de Ana que use mascarilla", "es", NOTING),
        ("anótalo en la ficha de Ana", "es", NOTING),
        ("hay que anotar en la espera de Marta que viene con un bebé", "es", NOTING),
        ("hay que anotarlo en la cita de Ana", "es", NOTING),
        # «Apunta» is said as «anota» is, with each of its forms (ERPlora/live#80).
        ("apunta el teléfono nuevo de Ana en su ficha", "es", NOTING),
        ("apúntale el teléfono nuevo a Ana", "es", NOTING),
        ("hay que apuntar en la cita de Ana que use mascarilla", "es", NOTING),
        ("hay que apuntarlo en la ficha de Ana", "es", NOTING),
        ("retira la mesa 90 del plano", "es", TAKING_AWAY),
        ("retírala del plano", "es", TAKING_AWAY),
        ("hay que retirar la mesa 90 del plano", "es", TAKING_AWAY),
        ("hay que retirarla del plano", "es", TAKING_AWAY),
        ("retire the Bar 2 station for good", "en", {"retire"}),
        ("withdraw Ana's consent to the emails", "en", {"withdraw"}),
    ],
)
def test_noting_and_taking_away_ask_for_their_action(said, language, actions):
    """«Anota» writes something new down (``create``: «anota una cita para Ana», as «apunta» does), adds to what there
    is (``add``) or writes on it (``update``: «anota en la cita de Ana…»); «retira» takes it
    away (``delete``, ``remove``), retires it (``retire``) or withdraws it (``withdraw``: a consent) — ERPlora/live#64.
    With their pronouns too; in English, «retire» and «withdraw»."""
    assert assistant.asked([said]).verbs == actions


#: What is noted on or taken away, beside the reads and the other writes of the same things.
NOTED_OR_TAKEN_AWAY = [
    tool("appointment.appointment.create", "Book an appointment for a customer with a service."),
    tool("appointment.appointment.list", "List the appointments of some days.", "query"),
    tool("appointment.appointment.update", "Change an appointment: its time, its service or its notes."),
    tool("customer.consent.grant", "Record that a customer gives their consent to marketing by a channel."),
    tool("customer.consent.list", "List a customer's consents, given or withdrawn.", "query"),
    tool("customer.consent.withdraw", "Record that a customer withdraws their consent to marketing by a channel."),
    tool("printing.device.list", "List the devices that print.", "query"),
    tool("printing.device.retire", "Retire a device that prints (a till replaced or lost)."),
    tool("printing.device.update", "Rename a device that prints."),
    tool("sale.order.add", "Add lines to an open check."),
    tool("sale.order.update", "Change an open check's title or note."),
    tool("table.table.create", "Creates a table of the floor plan with its name and seats."),
    tool("table.table.delete", "Delete a table of the floor plan; its checks keep their history."),
    tool("table.table.list", "Lists the tables of the floor plan with their seats.", "query"),
    tool("table.table.update", "Change a table of the floor plan: its name, its seats, its zone."),
    *NOISE,
]


@pytest.mark.parametrize(
    ("asked", "first"),
    [
        ("anota una cita para Ana mañana a las 10", "appointment.appointment.create"),
        ("anótame dos cafés en la cuenta de Ana", "sale.order.add"),
        ("apúntame dos cafés en la cuenta de Ana", "sale.order.add"),
        ("retira la mesa 90 del plano", "table.table.delete"),
        ("retira el dispositivo Barra 2, ya no está", "printing.device.retire"),
        ("Ana retira su consentimiento para la publicidad", "customer.consent.withdraw"),
    ],
)
def test_what_is_noted_or_taken_away_comes_first(asked, first):
    """An appointment noted is booked; noted on a check, a line is added to it; a table taken away is deleted, a device
    retired and a consent withdrawn: the action of the thing named, not its other writes nor its reads (live#64).
    Before, neither «anota» nor «retira» asked for anything."""
    names = ranked(NOTED_OR_TAKEN_AWAY, asked, synonyms=CHECK)
    assert names[0] == first, names[:4]


@pytest.mark.parametrize(
    "asked",
    [
        "anota en la cita de Ana de mañana «usa mascarilla», sin cambiar la hora",
        "hay que anotar en la cita de Ana que use mascarilla",
        "anota una cita para Ana mañana a las 10",
        # «Apunta» as «anota» (ERPlora/live#80): writing on her appointment, or booking one.
        "apunta en la cita de Ana de mañana que use mascarilla",
        "apunta una cita para Ana mañana a las 10",
    ],
)
def test_what_is_noted_brings_the_write_that_books_it_and_the_one_that_changes_it(asked):
    """«Anota una cita para Ana» books one and «anota en la cita de Ana…» writes on hers: the words do not say which,
    so both writes of the thing named come before its reads and every other write — the model chooses. Read as
    changing only, «anota una reserva para 4…» left the booking at the end of what a turn offers (live#64)."""
    names = ranked(NOTED_OR_TAKEN_AWAY, asked, synonyms=CHECK)
    assert set(names[:2]) == {"appointment.appointment.create", "appointment.appointment.update"}, names[:4]


class TillSettingsIn(Schema):
    enable_cash_register: bool | None = None
    require_blind_count: bool | None = None


class PrintingSettingsIn(Schema):
    open_drawer_on_sale: bool | None = None
    receipt_copies: int | None = None


class SaleSettingsIn(Schema):
    allow_cash: bool | None = None
    max_discount_percent: int | None = None


class BookingSettingsIn(Schema):
    min_booking_notice: int | None = None
    auto_confirm_online: bool | None = None


class QuickNoteIn(Schema):
    text: str
    sort_order: int | None = None


#: What is noted down at the till, beside the settings whose fields a sentence names in passing («la caja»: the till's
#: settings take the cash register, the printer's open the drawer, the till's charge with cash; «el aviso»: the booking
#: rules take a notice), the writes of the shift a sentence names where something is noted and the reads of what it
#: names for what («para comprar»: a customer's purchases; «el aviso»: the notices of the appointments), as the Hub's:
#: a thing named, the till's name is no thing of its tools.
NOTED_IN_PASSING = [
    tool("cash_register.movement.add", "Record money put in or taken out of the drawer of the open session.",
         input=MovementIn, asks={"es": ("mete 50 € de cambio en la caja",),
                                 "en": ("record 20 € taken out to pay the supplier",)}),
    tool("cash_register.movement.list", "List the money put in or taken out of a session.", "query"),
    tool("cash_register.settings.update", "Change how the drawer works, field by field: cash register on, blind "
         "count.", input=TillSettingsIn),
    tool("printing.settings.update", "Change how the business prints: open the drawer at checkout, receipt copies.",
         input=PrintingSettingsIn),
    tool("sale.settings.update", "Change the till settings field by field: which payment types charge, the cap of "
         "discounts.", input=SaleSettingsIn),
    tool("sale.quick_note.create", "Add a quick note to the till (e.g. «no salt»): a chip of the line-note sheet.",
         input=QuickNoteIn),
    tool("appointment.settings.update", "Change the booking rules: the minimum notice, auto-confirming.",
         input=BookingSettingsIn),
    tool("staff.schedule.create", "Create a shift of the schedule for a member."),
    tool("staff.schedule.update", "Change a shift of the schedule: its hours or its member."),
    tool("staff.settings.update", "Change the staff settings: how shifts are planned and swapped."),
    tool("customer.customer.create", "Creates a new customer; only the name is required.", input=CustomerIn),
    tool("customer.customer.update", "Change a customer's card: its name, its phone.", input=CustomerIn,
         asks={"es": ("pon la dirección nueva de Marta en su ficha", "cambia el correo de Luis")}),
    tool("customer.customer.list", "List the customers.", "query"),
    tool("inventory.product.create", "Create a product of the catalog with its name and its price.", input=ProductIn),
    tool("inventory.product.update", "Change a product: its name, its price.", input=ProductIn),
    tool("customer.purchase.list", "List what a customer bought.", "query"),
    tool("appointment.appointment.notices", "List the notices of today's appointments.", "query"),
    *NOISE,
]


@pytest.mark.parametrize(
    ("asked", "noted"),
    [
        ("anota una salida de 15 € de la caja para comprar hielo", "cash_register.movement.add"),
        ("apunta una salida de 15 € de la caja para comprar hielo", "cash_register.movement.add"),
        ("hay que apuntar una entrada de 20 € en efectivo en la caja para el cambio del turno",
         "cash_register.movement.add"),
        ("hay que anotarlo en la caja: una salida de 15 € para comprar hielo", "cash_register.movement.add"),
        # Where it is noted, said before what is noted, is no datum noted down.
        ("apunta en la caja una salida de 15 € para comprar hielo", "cash_register.movement.add"),
        ("deja preparado el aviso «Sin cilantro QA» para marcarlo rápido al apuntar platos", "sale.quick_note.create"),
    ],
)
def test_what_is_noted_comes_before_the_settings_a_word_names_in_passing(asked, noted):
    """«Anota una salida de 15 € de la caja» notes a movement of the till down: «anota» and «apunta» write on a thing
    named («anota en la cita de Ana…») or on what they note down, so a setting whose field a word names in passing
    («caja»: the till's, the printer's and the charge's settings; «aviso»: the booking rules) never comes before what
    writes the thing down (ERPlora/live#88: those settings took the 7 points of a write that takes what is named, and
    the movement came 8th in the Hub). «Una entrada… en el turno» names no movement in the Hub."""
    names = ranked(NOTED_IN_PASSING, asked, app_words=till_apps)
    settings = [name for name in names if name.endswith(".settings.update")]
    assert all(names.index(noted) < names.index(name) for name in settings), names[:6]


@pytest.mark.parametrize(
    ("said", "written_on"),
    [
        ("anota una salida de 15 € de la caja", {"update"}),
        ("apúntame una entrada de 50 € en el turno", {"update"}),
        ("hay que anotarlo en la cita de Ana", {"update"}),
        # Asked by another verb too, a change is that verb's, of whatever it changes.
        ("apunta una salida de 15 € y cambia la caja a arqueo ciego", set()),
        ("ponle a la caja el arqueo ciego y anota una salida de 15 €", set()),
        ("apunta una salida de 15 € y ponle de nombre «Hielo»", set()),
        ("crea un aviso", set()),
        ("cambia el precio del café", set()),
        # A request asks for it as a command does; a question that asks to know, for no change at all.
        ("¿puedes anotar una salida de 15 €?", {"update"}),
        ("¿hay que anotar la salida de 15 € en la caja?", set()),
    ],
)
def test_noting_writes_only_on_what_is_named(said, written_on):
    """The actions asked only as what «anota» and «apunta» write on (``Asked.written_on``): their ``update``, unless
    another word asks for it as well (ERPlora/live#88)."""
    assert assistant.asked([said]).written_on == written_on


@pytest.mark.parametrize(
    ("said", "noted"),
    [
        ("anota una salida de 15 € de la caja", {"salida"}),
        ("apúntale el teléfono nuevo a Ana", {"teléfono", "nuevo", "ana"}),
        ("apunta en la ficha de Ana su teléfono nuevo", {"ana", "teléfono", "nuevo"}),
        ("anótale a Ana en su ficha el teléfono nuevo", {"ana", "teléfono", "nuevo"}),
        ("apunta en la caja una salida de 15 €", {"salida"}),
        ("apunta en esta caja una salida de 15 €", {"salida"}),
        ("anota de la caja de Barra una salida de 15 €", {"barra", "salida"}),
        ("apunta del turno de Barra una entrada de 20 €", {"barra", "entrada"}),
        ("apúntale al cliente el teléfono nuevo", {"teléfono", "nuevo"}),
        ("anótale a la clienta el teléfono nuevo", {"teléfono", "nuevo"}),
        # Every thing named outside where it is noted, whatever comes before it (the review of ERPlora/live#96).
        ("apunta también el email de Ana", {"también", "email", "ana"}),
        ("apúntale a Ana García el teléfono nuevo", {"ana", "garcía", "teléfono", "nuevo"}),
        # «En», «de» and «a» say where it is noted, or whose it is, only before an article or another word that names
        # nothing («de la caja», «en su ficha», «del», «al»); before a name, what follows is the datum («de teléfono»).
        ("apunta el número de teléfono de Ana", {"número", "teléfono", "ana"}),
        ("apunta la subida de precio del café", {"subida", "precio"}),
        ("apunta una salida de caja", {"salida", "caja"}),
        ("hay que apuntar una salida de", {"salida"}),
        # Of each word that notes something down, in each of its sentences, until another command starts; never of
        # another verb.
        ("hay que anotarlo en la caja: una salida de 15 €", set()),
        ("una salida de 15 € de la caja hay que apuntarla", set()),
        ("una salida de 15 € apúntala en la caja", set()),
        ("anota una salida de 15 € y apunta el teléfono de Ana", {"salida", "teléfono", "ana"}),
        ("anota una salida de 15 € y dime el saldo", {"salida"}),
        ("anota una salida de 15 € y búscame el teléfono de Ana", {"salida"}),
        ("crea una salida de 15 € de la caja", set()),
    ],
)
def test_what_is_noted_down_is_what_the_word_that_notes_names_after_it(said, noted):
    """What a word that notes something down notes (``Asked.noted``): every thing named after it, until another command
    starts, but the one a word of where or whose introduces with its article («en la ficha de Ana», «de la caja», «al
    cliente»; ERPlora/live#88)."""
    found = assistant.asked([said]).noted
    assert len(found) == len(noted), found
    assert all(any(assistant.stems(word) <= concept for concept in found) for word in noted), found


def test_noting_with_another_verb_said_before_writes_on_what_that_verb_changes():
    """A change asked in an earlier text of the turn is still asked: the till's settings take the cash register it
    changes, before every other write (ERPlora/live#88)."""
    said = assistant.asked(["cambia la caja a arqueo ciego", "y apunta una salida de 15 €"])
    assert said.written_on == frozenset()
    names = [op.name for op in assistant.relevant(
        {op.name: op for op in NOTED_IN_PASSING},
        ["cambia la caja a arqueo ciego", "y apunta una salida de 15 €"],
        "es",
        app_words=till_apps,
    )]
    assert names.index("cash_register.settings.update") < names.index("printing.settings.update"), names[:6]
    assert "cash_register.settings.update" in names[:2], names[:6]


@pytest.mark.parametrize(
    "asked",
    [
        "apúntale el teléfono nuevo a Ana",
        "anota el teléfono nuevo de Ana",
        "hay que apuntar el teléfono nuevo de Ana",
        # Said after where it is noted: what is noted is still the phone.
        "apunta en la ficha de Ana su teléfono nuevo",
        "anótale a Ana en su ficha el teléfono nuevo",
        # With an adjective, an adverb, a surname or a number before it, too (the review of ERPlora/live#96: only the
        # first word after the verb was what is noted down, and the card left the first ones).
        "apúntale a Ana el nuevo teléfono",
        "apunta también el teléfono de Ana",
        "anota bien el teléfono de Marta",
        "apúntale a Ana García el teléfono nuevo",
        "apunta en la ficha de Ana García su teléfono nuevo",
        "anota 600 111 222 como teléfono de Ana",
        "anota su nuevo teléfono, 600 111 222",
        "apunta otro teléfono para Marta",
        # Said after «de» or «a» with no article, it is the datum, not whose it is (the review of ERPlora/live#96, round
        # 2: «de teléfono» was read as where it is noted, and the card left what a turn offers).
        "apunta el número de teléfono de Ana",
        "anótale a Ana el número de teléfono",
        "apunta el número de móvil de Ana",
        "anota el número de teléfono de Ana: 600 111 222",
        "apunta el nuevo número de teléfono de Ana en su ficha",
        "apunta en la ficha de Ana el número de teléfono",
        "anota el cambio de teléfono de Ana",
        "apunta a Ana de teléfono el 600 111 222",
    ],
)
def test_what_is_noted_of_someone_is_still_written_on_their_card(asked):
    """What a command notes down is what a write that takes it writes on («apúntale el teléfono nuevo a Ana»: the
    customer's phone), so the change that takes it stays beside the create that does: the model chooses
    (ERPlora/live#88 leaves out only what a word names in passing)."""
    names = ranked(NOTED_IN_PASSING, asked, app_words=till_apps)
    assert set(names[:2]) == {"customer.customer.create", "customer.customer.update"}, names[:6]


@pytest.mark.parametrize(
    "asked",
    ["apunta la subida de precio del café", "apunta el precio nuevo del café"],
)
def test_what_is_noted_of_a_product_is_still_written_on_it(asked):
    """«La subida de precio del café» notes a price down: the product's change that takes it stays beside the create that
    does, as a customer's phone does: «de precio» is the datum noted, not where it is noted (ERPlora/live#96)."""
    names = ranked(NOTED_IN_PASSING, asked, app_words=till_apps)
    assert set(names[:2]) == {"inventory.product.create", "inventory.product.update"}, names[:6]


@pytest.mark.parametrize(
    "asked",
    [
        "anota el DNI de Luis en su ficha",
        "apunta la calle nueva de Marta: Mayor 3",
        "apúntale a Luis el correo nuevo, luis@example.com",
        "anótale a Luis otro correo, luis@example.com",
        "apunta el cumpleaños de Ana en su ficha: 3 de mayo",
    ],
)
def test_what_is_noted_of_someone_with_no_datum_its_card_takes_still_brings_the_card(asked):
    """What is noted down need not be named as the card's write names it («el DNI», «la calle», «el correo»): the change
    of the card the sentence names still comes before every write that shares only the verb, as a write that takes
    nothing named keeps the points of any other write (the review of ERPlora/live#96: with none, «anota el DNI de Luis
    en su ficha» left the card out of what a turn offers in the Hub)."""
    names = ranked(NOTED_IN_PASSING, asked, app_words=till_apps)
    noise = [name for name in names if name.startswith("appointment.thing")]
    assert all(names.index("customer.customer.update") < names.index(name) for name in noise), names[:6]


@pytest.mark.parametrize(
    ("said", "thing"),
    [
        ("anota en el turno una salida de 50 € de cambio", "salida"),
        ("anota en el turno una entrada de 50 € de cambio", "entrada"),
        ("apunta en la caja una salida de 15 € para comprar hielo", "salida"),
        ("hay que anotar en el turno una salida de 20 € para el proveedor", "salida"),
        # Where it is done goes on with what it is of («de Barra», «de la mesa 4») and with its name («la carpeta
        # Facturas»): the thing acted on is named in a phrase of its own, after an article, a determiner or a number.
        ("mete en el turno de Barra una entrada de 20 € de cambio", "entrada"),
        ("añade a la cuenta de la mesa 4 una cerveza", "cerveza"),
        ("añade a la carpeta Facturas un documento", "documento"),
        ("mete en la caja 50 € de cambio", "cambio"),
        # Once a number opens what is put, it stays open through what the money is of.
        ("mete en la caja 50 € de la propina", "propina"),
        # «Del» and «al» say where with their article; «en» and «a» before a determiner too.
        ("anota del turno una salida de 15 €", "salida"),
        ("apunta en esta caja una salida de 15 €", "salida"),
        ("apunta en mi caja una salida de 15 €", "salida"),
        ("anota en tu turno una salida de 15 €", "salida"),
        ("anota en su turno una salida de 15 €", "salida"),
        # Each determiner opens what is put, as «una» does.
        ("apunta en la ficha de Ana su móvil nuevo", "movil"),
        ("apunta en el turno otra salida de 20 €", "salida"),
        ("añade a la mesa 4 otro café", "café"),
        ("añade a la mesa 4 otros cafés", "cafés"),
        ("añade a la mesa 4 otras cervezas", "cervezas"),
        ("añade a la mesa de la terraza el pan", "pan"),
        # A short name goes on with where it is done, as any name does («Ana QA»): only a determiner or a number opens
        # the phrase of what is acted on.
        ("anota en la cita de Ana QA de mañana", "cita"),
        # English's «a» goes before what is added: no place, before a number, a letter or a name.
        ("add a 10% discount to table 4", "discount"),
        ("add a QR code to table 4", "code"),
        ("add a 10% discount to the check of table 4", "discount"),
        # With nothing named in a phrase of its own before another clause or command, where it is done is what the
        # command acts on («anota en la cita de Ana…»: it writes on her appointment).
        ("anota en la cita de Ana que use mascarilla", "cita"),
        ("anota en la caja y luego una salida de 15 €", "caja"),
        ("hay que anotarlo en la caja", "caja"),
        # A word of under three letters names nothing, as anywhere («té»).
        ("añade a la cuenta de la mesa 4 un té", "cuenta"),
        # «A» before a name is whom it is done to, no place: what follows is no thing of its own.
        ("apúntale a Ana el teléfono nuevo", "ana"),
        # Only a verb that puts something somewhere: where another verb acts, said first, is what it acts on.
        ("borra del historial la cuenta de la mesa 4", "historial"),
        ("pon en la web el horario de verano", "web"),
        ("crea en la carpeta Facturas un documento", "carpeta"),
        # Of two verbs said before where, the one it follows says whether it is a place or the thing acted on.
        ("anota o borra del historial la cuenta de la mesa 4", "historial"),
        ("quita o añade a la cuenta de la mesa 4 una cerveza", "cerveza"),
        ("anota una salida de 15 € en el turno", "salida"),
        # Only a word of where says where; any other word said first is what the command acts on, as it always was.
        ("anota hoy una salida de 15 € en la caja", "hoy"),
        # «Registra» adds what it registers where it says, as «anota» does (ERPlora/live#95).
        ("registra en el turno una salida de 15 € para hielo", "salida"),
        ("hay que registrar en la caja una salida de 15 €", "salida"),
        ("regístrame en el turno de Barra una entrada de 20 € de cambio", "entrada"),
        ("registra en la ficha de Ana que es alérgica al marisco", "ficha"),
    ],
)
def test_what_a_command_acts_on_is_named_after_where_it_is_done(said, thing):
    """Where a command is done, said before what it does it to («anota en el turno una salida de 50 €»), is no thing it
    acts on: the shift is where the money taken out is noted, as in «anota una salida de 50 € en el turno»
    (ERPlora/live#94: read as the shift, the writes and reads of the staff's shifts came before noting the movement)."""
    said = assistant.asked([said])
    assert said.objects == {assistant._concept(assistant._plain(thing))}
    # What it acts on is named after the verb: the record a read finds, not where it is done.
    assert said.records == said.objects


#: The tools of the shift a sentence says something is noted in, its reads and its delete too, beside what is noted
#: down: as the Hub's staff shifts, which share the word «turno» with the till's session.
NOTED_IN_A_SHIFT = [
    *NOTED_IN_PASSING,
    tool("staff.schedule.detail", "Show a shift of the schedule: its member, its hours.", "query"),
    tool("staff.schedule.list", "List the shifts of the schedule, by day.", "query"),
    tool("staff.schedule.delete", "Delete a shift of the schedule."),
]


@pytest.mark.parametrize(
    "asked",
    [
        "anota en el turno una salida de 50 € de cambio",
        "anota en el turno una entrada de 50 € de cambio",
        "apunta en el turno una salida de 20 € para el proveedor",
        "mete en el turno de Barra una entrada de 20 € de cambio",
        "anota del turno una salida de 15 € de cambio",
        # Said after what is noted, as it always came.
        "anota una salida de 50 € de cambio en el turno",
        "mete una entrada de 20 € de cambio en el turno de Barra",
    ],
)
def test_what_is_noted_comes_before_what_is_read_or_deleted_of_where_it_is_noted(asked):
    """«Anota en el turno una salida de 50 €» notes a movement of the till down, wherever the shift is said: the reads
    and the delete of the staff's shifts, which do none of what is asked, never come before it (ERPlora/live#94: the
    movement came 95th in the Hub with «en el turno» first, against 24th after)."""
    names = ranked(NOTED_IN_A_SHIFT, asked, app_words=till_apps)
    assert "cash_register.movement.add" in names, names[:7]
    before = names[: names.index("cash_register.movement.add")]
    assert not {"staff.schedule.detail", "staff.schedule.list", "staff.schedule.delete"} & set(before), names[:7]


#: What «registra» asks for: writing something new down («registra un cliente nuevo»), adding it to what there is
#: («registra una salida de 15 € en el turno») or setting up a device («registra esta tablet»); the thing named says
#: which.
REGISTERING = {"create", "add", "register"}


@pytest.mark.parametrize(
    "said",
    [
        "registra una salida de 15 € para hielo en el turno",
        "regístrame una salida de 15 € para hielo en el turno",
        "regístralo en la caja: una salida de 15 € para comprar hielo",
        "hay que registrar una salida de 20 € para el proveedor",
        "hay que registrarla en la caja",
        "registra un cliente nuevo",
    ],
)
def test_registering_asks_to_write_down_or_to_add(said):
    """«Registra» writes something new down («registra un cliente nuevo») or adds it to what there is («registra una
    salida de 15 € en el turno»: a movement of the open session), as «anota» and «apunta» do but for writing on what is
    named: with its pronouns and in the infinitive too (ERPlora/live#95: asked only to create, the movement came 125th
    in the Hub)."""
    assert assistant.asked([said]).verbs == REGISTERING


def test_registering_in_english_still_asks_no_add():
    """English's «register» is also the till itself («close the cash register»): asking to add with it would bring the
    till's adds before closing it, so it still asks to create, and to register where it starts the command, never to
    add (ERPlora/live#95, ERPlora/live#117)."""
    assert assistant.asked(["register a new waiter, Pablo, at 12 € an hour"]).verbs == {"create", "register"}


@pytest.mark.parametrize(
    "asked",
    [
        "registra una salida de 15 € para hielo en el turno",
        "registra en el turno una salida de 15 € para hielo",
        "regístrame una salida de 15 € para hielo en el turno",
        "registrar una salida de 20 € para el proveedor en el turno",
    ],
)
def test_what_is_registered_at_the_till_comes_before_the_writes_of_what_nobody_named(asked):
    """«Registra una salida de 15 € para hielo en el turno» adds a movement to the open session: the write that adds
    it comes before the creates of things nobody names and before the reads and the delete of the staff's shifts, which
    do none of what is asked (ERPlora/live#95: read as creating only, it came 125th in the Hub, behind every create)."""
    names = ranked(REGISTERED_AT_THE_TILL, asked, app_words=till_apps)
    before = set(names[: names.index("cash_register.movement.add")])
    nobody_named = {op.name for op in NOISE}
    assert not before & nobody_named, names[:7]
    assert not {"staff.schedule.detail", "staff.schedule.list", "staff.schedule.delete"} & before, names[:7]


@pytest.mark.parametrize(
    ("asked", "first"),
    [
        ("registra un cliente nuevo", "customer.customer.create"),
        ("registra a Ana García como clienta nueva", "customer.customer.create"),
        ("registra un producto nuevo: café con leche a 1,50 €", "inventory.product.create"),
        ("registra un turno para Carmen el lunes de 9 a 14", "staff.schedule.create"),
        # Without «nuevo» or «nueva», which ask to create by themselves: here only «registra» does.
        ("registra a Ana García como clienta", "customer.customer.create"),
        ("regístrame un cliente: Luis Pérez", "customer.customer.create"),
        ("hay que registrar un producto: café con leche a 1,50 €", "inventory.product.create"),
    ],
)
def test_what_is_registered_as_new_is_still_created(asked, first):
    """Asking to add as well, «registra un cliente nuevo» still creates the customer, a product or a shift first: the
    thing named says which (ERPlora/live#95)."""
    assert ranked(REGISTERED_AT_THE_TILL, asked, app_words=till_apps)[0] == first
