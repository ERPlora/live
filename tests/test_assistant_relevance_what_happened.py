"""What a turn offers when it notes down what happened: money taken out of the till or coming in, and goods
coming in."""

import pytest
from ninja import Schema

from live import assistant
from tests.assistant_catalogue import CHECK, NOISE, CustomerIn, MovementIn, ReservationIn, ranked, till_apps, tool


EXPORTING_OR_PRINTING = {"export", "print"}


@pytest.mark.parametrize(
    ("said", "verbs"),
    [
        ("saca 15 € de la caja para comprar hielo", {"add"}),
        ("sácame 10 € de la caja", {"add"}),
        ("quiero sacar 15 € de la caja para comprar hielo", {"add"}),
        ("saca 50 euros del cajón para llevarlos al banco", {"add"}),
        ("saca 12,50 € de la caja para el pan", {"add"}),
        # Where the money comes from, said before it.
        ("saca de la caja 15 € para el hielo", {"add"}),
        ("sácame del cajón 20 € para el pan", {"add"}),
        ("take 20 € out of the till for the supplier", {"add"}),
        ("take 15 euros out of the till for ice", {"add"}),
        ("take €15 out of the till", {"add"}),
        ("take out 15 € from the drawer for ice", {"add"}),
        # Each currency by its name, one or many, and by its sign, before the number too.
        ("saca 1 euro de la caja", {"add"}),
        ("saca 20 eur de la caja", {"add"}),
        ("saca 1 dólar de la caja", {"add"}),
        ("saca 20 dólares de la caja", {"add"}),
        ("saca 1 libra de la caja", {"add"}),
        ("saca 20 libras de la caja", {"add"}),
        ("take 1 dollar out of the till", {"add"}),
        ("take 20 dollars out of the till", {"add"}),
        ("take 1 pound out of the till", {"add"}),
        ("take 10 pounds out of the till", {"add"}),
        ("take $20 out of the drawer", {"add"}),
        ("take £10 out of the till", {"add"}),
        ("take € 15 out of the till", {"add"}),
        # English's «register» there is the till: it still asks to create and never to register (ERPlora/live#117).
        ("take 15 € out of the register for ice", {"add", "create"}),
        # Said twice, once of money and once of a list: both are asked.
        ("saca 15 € de la caja y saca el listado de clientes", {"add", "export", "print"}),
        # Anything else taken out is exported, printed or taken out of where it is.
        ("saca el listado de clientes", EXPORTING_OR_PRINTING),
        ("saca 2 copias del tique de la venta 7", EXPORTING_OR_PRINTING),
        ("take the coffee out of the drinks category", set()),
        # A number without its currency is how many, not money.
        ("saca 3 del almacén, se han caducado", EXPORTING_OR_PRINTING),
        ("take 5 out of stock, we used them ourselves", set()),
        ("take 2 out of table 4's check", set()),
        # Money taken off with no «out» is no cash taken out of the till.
        ("take 5 € off table 4's check", set()),
        ("take a 15 € discount off table 4's check", set()),
        # An «out» said far from the money is of something else.
        ("take 15 € and check out the cart", set()),
        # The word that takes out, where it is taken from or a number, when the sentence ends there.
        ("hay que sacar", EXPORTING_OR_PRINTING),
        ("saca de la", EXPORTING_OR_PRINTING),
        ("de ese tique saca 3", EXPORTING_OR_PRINTING),
    ],
)
def test_taking_money_out_asks_to_note_it_down(said, verbs):
    """«Saca 15 € de la caja» and «take 15 € out of the till» note the money taken out down, as «mete 50 € en la caja»
    notes what is put in: they ask to add, never to export or print (ERPlora/live#118: read as exporting or printing,
    the till's movement came 12th in the Hub, and 81st in English, where «take» asked for nothing)."""
    assert assistant.asked([said]).verbs == verbs


class CountIn(Schema):
    counted: int


#: The till as the Hub says cash is taken out of it or counted, beside what «saca» also does — export a list, print a
#: report or a receipt —, what else is taken out of where it is — stock written off, a line of a check —, a member
#: clocked out («salida» and «out» are hers too) and a customer's purchases, what «para comprar» names.
TAKEN_OUT_OF_THE_TILL = [
    tool("cash_register.movement.add", "Record cash brought into the drawer or taken out of it in the open session.",
         input=MovementIn, asks={"es": ("apunta una salida de 35 € de la caja", "mete 50 € de cambio en la caja"),
                                 "en": ("record 20 € taken out to pay the supplier",)}),
    tool("cash_register.movement.list", "List the money put in or taken out of a session.", "query"),
    tool("cash_register.count.add", "Record a count of the cash in the drawer.", input=CountIn,
         asks={"es": ("haz el arqueo de la caja",)}),
    tool("cash_register.session.print", "Print the report of the open session: what the drawer should hold.",
         asks={"es": ("saca el informe X de cómo va la caja",)}),
    tool("customer.customer.export", "Export the customers to a spreadsheet, with their purchases."),
    tool("sale.sale.print", "Print a copy of a sale's receipt.", asks={"es": ("sácame una copia del tique",)}),
    tool("inventory.stock.write_off", "Write stock off: what broke, expired or the business used itself.",
         asks={"en": ("write off what we used ourselves",)}),
    tool("sale.order.remove_line", "Remove a line from an open check.", asks={"en": ("take the coffee off table 4",)}),
    tool("attendance.record.clock_out", "Clocks the member out («ficha la salida de Ana»): the end of their working "
         "day.", asks={"es": ("ficha mi salida",), "en": ("clock me out",)}),
    tool("customer.purchase.list", "List what a customer bought.", "query"),
    *NOISE,
]


@pytest.mark.parametrize(
    ("asked", "language"),
    [
        ("saca 15 € de la caja para comprar hielo", "es"),
        ("sácame 10 € de la caja", "es"),
        ("saca de la caja 15 € para el hielo", "es"),
        ("hay que sacar 30 € de la caja para el butano", "es"),
        ("saca 15 € del turno para comprar hielo", "es"),
        ("take 15 € out of the register for ice", "en"),
        ("take out 15 € from the drawer for ice", "en"),
        ("please take 10 € out of the register", "en"),
    ],
)
def test_money_taken_out_of_the_till_is_noted_down_first(asked, language):
    """«Saca 15 € de la caja para comprar hielo» notes the cash taken out down: the till's movement comes before
    printing its report, exporting or reading what «comprar» names, counting the cash and the creates of what nobody
    named (ERPlora/live#118). Spanish says no «salida»: the money taken out is one, as English says with its «out»,
    and what it is for («para comprar hielo») is no purchase to find."""
    names = ranked(TAKEN_OUT_OF_THE_TILL, asked, language, app_words=till_apps)
    assert names[0] == "cash_register.movement.add", names[:5]


@pytest.mark.parametrize(
    ("asked", "language", "first"),
    [
        ("saca 2 copias del tique de la venta 7", "es", "sale.sale.print"),
        ("saca el informe de cómo va la caja", "es", "cash_register.session.print"),
        ("saca el listado de clientes", "es", "customer.customer.export"),
        ("take 5 out of stock, we used them ourselves", "en", "inventory.stock.write_off"),
        ("take 2 coffees out of table 4's check", "en", "sale.order.remove_line"),
    ],
)
def test_what_is_taken_out_but_money_is_not_noted_down(asked, language, first):
    """What «saca» takes out but money is exported or printed, and how many things «take … out» says is stock or a
    line: none of it is the till's movement."""
    names = ranked(TAKEN_OUT_OF_THE_TILL, asked, language, app_words=till_apps)
    movement = names.index("cash_register.movement.add") if "cash_register.movement.add" in names else len(names)
    assert names.index(first) < movement, names[:5]


@pytest.mark.parametrize(
    ("said", "stated"),
    [
        ("registra que entran 20 cafés más a 0,55 € la unidad con el albarán ALB-QA-01", {"create", "add"}),
        ("apunta que Carmen prefiere las mañanas", {"create", "add"}),
        ("anota que el pago del pedido QA-WEB-1 falló", {"create", "add"}),
        ("añade que Carmen prefiere las mañanas", {"create", "add"}),
        ("regístrame que entran 20 cafés", {"create", "add"}),
        ("hay que registrar que Luis no se presentó a su reserva", {"create", "add"}),
        # Only what is noted down: the change «apunta» asks for is still what it writes on (``written_on``).
        ("apunta que Ana es alérgica al marisco", {"create", "add"}),
        # «Que» said later is no fact noted down by the verb: it says what is written where.
        ("registra en la ficha de Ana que es alérgica al marisco", set()),
        ("registra una clienta nueva que se llama Marta", set()),
        ("registra una salida de 15 € en el turno", set()),
        # «Que» said right before the verb is no fact the verb notes down (the review of ERPlora/live#121).
        ("hay que registrar una salida de 15 € en el turno", set()),
        # Asked by another word too, the action is that word's.
        ("registra que entran 20 cafés y añade dos a la mesa 4", set()),
        ("crea un aviso que diga «Sin gluten»", set()),
        ("ponle que es alérgica al marisco", set()),
        # A word that only creates says what the new thing is like after «que»: nothing happened.
        ("una carta nueva que tenga postres", set()),
        # A question that asks to know asks for no write at all.
        ("¿hay que registrar que Luis no vino a su reserva?", set()),
    ],
)
def test_what_is_noted_down_as_what_happened_is_said_apart(said, stated):
    """A word that notes something down said right before «que» notes down what happened («registra que entran 20
    cafés…», «apunta que Carmen prefiere las mañanas»): the create and the add it asks for, asked by no other word, are
    ``Asked.stated`` (ERPlora/live#116)."""
    assert assistant.asked([said]).stated == stated


class ReceiptIn(Schema):
    items: list[str]
    reference: str | None = None


class LineIn(Schema):
    order: str
    product: str
    quantity: int


class CartItemIn(Schema):
    product: str
    quantity: int
    unit_price: int | None = None


class StockedProductIn(Schema):
    name: str
    price: int | None = None
    quantity: int | None = None


class NoteIn(Schema):
    customer: str
    content: str


#: Goods received as the Hub says it («registra que entran 20 cafés… con el albarán»), beside the writes that take the
#: quantity a sentence names (a check's line to add or to change, a cart's item, a product with its initial stock) and a
#: customer's note.
RECEIVED = [
    tool("inventory.stock.receive", "Receive goods from a supplier with their delivery note: each product's quantity "
         "and cost.", input=ReceiptIn),
    tool("sale.order.add_line", "Add a product to an open check, with its quantity.", input=LineIn),
    tool("sale.order.update_line", "Change a line of an open check: its quantity, its note.", input=LineIn),
    tool("cart_checkout.item.add", "Add a product to a customer's cart, with its quantity.", input=CartItemIn),
    tool("inventory.product.create", "Create a product of the catalog with its name, its price and its initial stock.",
         input=StockedProductIn),
    tool("customer.note.add", "Add a note to a customer's card: what to keep in mind of them.", input=NoteIn,
         asks={"es": ("añade una nota a Marta: prefiere venir por la tarde",)}),
    *NOISE,
]
#: The Hub's words for goods coming in and for how many.
RECEIVED_WORDS = (("entra", "entran", "recibe", "recibir", "receive", "albarán"),
                  ("unidad", "unidades", "cantidad", "quantity"))


@pytest.mark.parametrize(
    "asked",
    [
        "registra que entran 20 cafés más a 0,55 € la unidad con el albarán ALB-QA-01",
        "apunta que entran 20 cafés más a 0,55 € la unidad con el albarán ALB-QA-01",
        "anota que entran 20 cafés más a 0,55 € la unidad con el albarán ALB-QA-01",
        "hay que registrar que entran 12 cajas de agua a 3 € la unidad",
    ],
)
def test_what_is_noted_down_as_what_happened_brings_what_does_it_before_what_takes_its_data(asked):
    """«Registra que entran 20 cafés más a 0,55 € la unidad» notes down goods that came in: what follows «que» is what
    happened, and the quantity it names is no datum given to a check's line, a cart's item or a new product
    (ERPlora/live#116: those writes took the 7 points of a write that takes what is named, and receiving the goods came
    12th in the Hub)."""
    names = ranked(RECEIVED, asked, synonyms=RECEIVED_WORDS)
    assert "inventory.stock.receive" in names, names[:6]
    before = set(names[: names.index("inventory.stock.receive")])
    assert not before & {"sale.order.add_line", "cart_checkout.item.add", "inventory.product.create"}, names[:6]


@pytest.mark.parametrize(
    ("asked", "first"),
    [
        # A note of what happened is still added, as a write that takes nothing named: as the Hub's customer notes are
        # asked for («apunta que Carmen prefiere las mañanas»), naming neither the customer nor the note.
        ("apunta que Carmen prefiere las mañanas", "customer.note.add"),
        ("anota que Luis prefiere la mesa de la ventana", "customer.note.add"),
        # What a fact names that a write adds to is still what it adds to: the check of table 4.
        ("apunta que el pedido de la mesa 4 lleva otra caña", "sale.order.add_line"),
        # Asked by another word too, the write still takes the data named.
        ("añade 20 cafés a la cuenta, a 0,55 € la unidad", "sale.order.add_line"),
    ],
)
def test_what_is_noted_down_as_what_happened_still_adds_what_it_names(asked, first):
    """Noting down what happened still asks to add: the customer's note of «apunta que Carmen prefiere las mañanas»
    comes before the writes of what nobody named, and «apunta que el pedido de la mesa 4 lleva otra caña» still adds to
    the check it names before changing its lines (ERPlora/live#116 leaves out only the data a fact names: with no add
    at all, the note came 40th in the Hub, and with no thing either, the line left what a turn offers)."""
    names = ranked(RECEIVED, asked, synonyms=(*RECEIVED_WORDS, *CHECK))
    writes = [name for name in names if not name.endswith((".list", ".detail"))]
    assert writes[0] == first, names[:6]


class BlockedTimeIn(Schema):
    staff: str
    starts_at: str
    ends_at: str


class SessionMovementIn(Schema):
    session: str
    type: str
    amount: int


#: Facts whose data say which write notes them down, as the Hub's: a reservation by its guest's name, a customer's note
#: by the customer, a check's line by its quantity, a member's blocked time by the member, a movement by the session of
#: the till. A customer is also what a tool's action acts on (a conversation's ``link_customer``), and so is a session
#: no write asked here acts on (the till's ``session.close`` is of a session, not on it).
FACTS = [
    *RECEIVED,
    tool("reservation.reservation.create", "Takes a reservation: the guest, the day and time, the party size.",
         input=ReservationIn),
    tool("appointment.blocked_time.create", "Block a member's time in the agenda: when they do not work.",
         input=BlockedTimeIn),
    tool("cash_register.movement.add", "Record cash brought into the drawer or taken out of it.",
         input=SessionMovementIn),
    tool("cash_register.session.close", "Close the open session of the till."),
    tool("customer.customer.create", "Creates a new customer; only the name is required.", input=CustomerIn),
    tool("customer.customer.list", "List the customers.", "query"),
    tool("customer.customer.detail", "Show a customer's card.", "query"),
    tool("whatsapp_inbox.conversation.link_customer", "Link a conversation to a customer's card."),
]


@pytest.mark.parametrize(
    ("asked", "noted_by"),
    [
        ("apunta que el viernes vienen 6 a cenar a nombre de Luis", "reservation.reservation.create"),
        ("registra que la clienta Ana es alérgica al marisco", "customer.note.add"),
        ("añade que quieren dos unidades más de tarta", "sale.order.add_line"),
        ("anota que Carmen no trabaja el lunes por la mañana", "appointment.blocked_time.create"),
        # What the fact is about names no tool's action: the session is what a movement is added to.
        ("anota que la sesión de caja ha tenido una entrada de 50 €", "cash_register.movement.add"),
    ],
)
def test_what_is_noted_down_as_what_happened_still_gives_its_data_to_the_write_they_name(asked, noted_by):
    """The data of a fact are what says which write notes it down when the fact is about nothing another tool does
    («apunta que el viernes vienen 6 a cenar a nombre de Luis»: a reservation, by its guest's name): that write comes
    before the writes of what nobody named and before every read (the review of ERPlora/live#121: taking the data of
    every fact from the writes it asks for, the reservation came 50th in the Hub, the customer's note 39th behind the
    reads of the customer, the check's line 54th and the member's blocked time 172nd)."""
    names = ranked(FACTS, asked, synonyms=(*RECEIVED_WORDS, *CHECK))
    assert noted_by in names, names[:6]
    nobody_named_or_read = {op.name for op in FACTS if op in NOISE or op.kind == "query"}
    assert not set(names[: names.index(noted_by)]) & nobody_named_or_read, names[:6]


#: The Hub's own words for goods coming in: «entran», never «entra» nor «entrada», whose stem is that of «entre», of
#: the money brought into the till and of a clock-in («ficha la entrada»).
GOODS_IN = (("albarán", "mercancía", "entran", "recibir", "recibe", "recibido", "receive", "received", "goods",
             "delivery note"),)
GOODS = assistant.asked(["entran"], GOODS_IN).concepts


@pytest.mark.parametrize(
    ("past", "present"),
    [
        ("apunta que han entrado 12 unidades de tarta", "apunta que entran 12 unidades de tarta"),
        ("registra que han entrado 12 unidades de tarta", "registra que entran 12 unidades de tarta"),
        ("anota que habían entrado 12 unidades de tarta", "anota que entran 12 unidades de tarta"),
        ("registra que ya han entrado", "registra que ya entran"),
        ("nos han entrado 12 unidades de tarta, apúntalo", "nos entran 12 unidades de tarta, apúntalo"),
        # Said in any sentence of the text, not only the first.
        ("apúntalo, han entrado 12 unidades de tarta", "apúntalo, entran 12 unidades de tarta"),
        # A request is no question: it asks to note it down, or to look at what came in.
        ("¿puedes apuntar que han entrado 12 unidades de tarta?", "¿puedes apuntar que entran 12 unidades de tarta?"),
        ("¿puedes mirar si han entrado 12 unidades de tarta?", "¿puedes mirar si entran 12 unidades de tarta?"),
    ],
)
def test_a_compound_past_in_the_plural_also_names_what_its_present_names(past, present):
    """«Han entrado» is the verb «entran» said in the past: it names what the present names (the goods, as the Hub's
    words say them) and is what a word that notes it down acts on, asking for nothing more (ERPlora/live#122: its
    auxiliary was what «apunta» acted on, and «entrado» is cut as «entrada» is, so receiving the goods came 152nd)."""
    past_said, present_said = assistant.asked([past], GOODS_IN), assistant.asked([present], GOODS_IN)
    assert GOODS <= present_said.concepts <= past_said.concepts
    assert past_said.objects == present_said.objects
    assert (past_said.verbs, past_said.stated) == (present_said.verbs, present_said.stated)


@pytest.mark.parametrize(
    "said",
    [
        # What came in, said right after, is money: the till's, not the goods.
        "anota que han entrado 100 € en caja",
        "anota que han entrado 100 euros en caja",
        # A question about what happened asks to know it, not to note it down.
        "¿quiénes han entrado alguna vez en el negocio?",
        # Only the plural: «ha entrado» is «entra», which names no goods.
        "apunta que ha entrado una caja de leche",
        # «Entrada» never names the goods: money brought into the till, a clock-in.
        "registra una entrada de 50 € en la caja",
        "ficha la entrada de Ana",
        # A dictation cut short after the auxiliary.
        "apunta que han",
    ],
)
def test_what_is_no_compound_past_of_goods_coming_in_names_no_goods(said):
    """Only the compound past of goods coming in, told or noted down, names them: never money that came in, a question
    about who came in, the singular nor «entrada» (ERPlora/live#122)."""
    assert not GOODS & assistant.asked([said], GOODS_IN).concepts


@pytest.mark.parametrize(
    ("said", "read"),
    [
        ("apunta que han entrado 12 unidades", "apunta que entran han entrado 12 unidades"),
        ("anota que habían pagado la cuenta", "anota que pagan habian pagado la cuenta"),
    ],
)
def test_a_compound_past_in_the_plural_is_read_with_its_present_before_it(said, read):
    """The present goes before the auxiliary, so it is the first thing named after a word that notes it down, and is
    the participle's root with the plural's «-an» («pagado»: «pagan»)."""
    assert assistant._as_present(assistant._sentences(said)[0], frozenset()) == read.split()


def test_a_compound_past_asks_for_nothing_its_present_would():
    """«Han cuadrado» is no «cuadran» asking to check the till: what happened is no command."""
    assert assistant.asked(["apunta que han cuadrado las cajas de ayer"]).verbs == {"create", "add", "update"}


def test_only_a_participle_in_ado_is_read_as_its_present():
    """The present of a participle in «-ido» («venden», «reciben») is no word a project names: the compound past is
    read as said, its auxiliary the first word after the verb that notes it down."""
    assert assistant.asked(["apunta que han vendido 12 unidades de tarta"]).objects == {frozenset({"han"})}


@pytest.mark.parametrize(
    "asked",
    [
        "apunta que han entrado 12 unidades de tarta",
        "registra que han entrado 12 unidades de tarta",
        "anota que habían entrado 12 unidades de tarta",
    ],
)
def test_goods_noted_down_as_come_in_are_received_before_what_takes_their_quantity(asked):
    """«Apunta que han entrado 12 unidades de tarta» notes down goods that came in, as «apunta que entran…» does: they
    are received before a check's line, a cart's item or a new product takes the quantity (ERPlora/live#122: 152nd in
    the Hub, behind the cart's items)."""
    names = ranked(RECEIVED, asked, synonyms=(*GOODS_IN, RECEIVED_WORDS[1]))
    assert "inventory.stock.receive" in names, names[:6]
    before = set(names[: names.index("inventory.stock.receive")])
    assert not before & {"sale.order.add_line", "cart_checkout.item.add", "inventory.product.create"}, names[:6]


#: The till's cash, as live names it («caja», «cash», «drawer», «till»).
TILL = assistant.asked(["caja"]).concepts


@pytest.mark.parametrize(
    "said",
    [
        "apunta que entran 100 € en el turno",
        "registra que entran 100 € en el turno",
        "anota que entran 50 euros de cambio",
        "apunta que entra 20 € de propina en el turno",
        "anota que ha entrado 100 € en el turno",
        "apunta que han entrado 100 € en el turno",
        # Said after where it comes in.
        "apunta que entran en el turno 100 €",
        "anota que han entrado en el turno 100 €",
        # Said in the second sentence of the text.
        "apúntalo, entran 100 € en el turno",
        # Said again of goods, those are still named.
        "apunta que entran 100 € en el turno y que entran 12 unidades de tarta",
    ],
)
def test_money_that_comes_in_names_the_till_and_not_the_goods(said):
    """«Apunta que entran 100 € en el turno» notes down money brought into the till: «entran», «entra» and «entrado»,
    with money said right after them or after where it comes in, name the till's cash, never the goods a project names
    by them, and are no thing the command acts on (ERPlora/live#123: read as goods coming in, the till's movement came
    51st in the Hub)."""
    said_as = assistant.asked([said], GOODS_IN)
    assert TILL <= said_as.concepts
    assert not GOODS & said_as.objects
    assert (GOODS <= said_as.concepts) == ("unidades" in said)


@pytest.mark.parametrize("said", ["apunta que entran 100 € de propina", "apunta que entran en el turno 100 € de propina"])
def test_what_is_said_after_money_that_comes_in_is_no_thing_the_command_acts_on(said):
    """The command acts on the money that came in: where it comes in («el turno», a staff's shift too) and what it is
    («propina») are no thing it acts on."""
    assert not assistant.asked([said]).objects


@pytest.mark.parametrize(
    "said",
    [
        # A number without its currency says how many.
        "apunta que entran 12 unidades de tarta",
        "apunta que entran en el almacén 12 unidades de tarta",
        # Money said later is what the goods cost.
        "registra que entran 20 cafés más a 0,55 € la unidad",
        "apunta que han entrado 12 unidades de tarta a 3 €",
        # A dictation cut short after the word or after where it comes in.
        "apunta que entran",
        "apunta que entran en el",
    ],
)
def test_what_comes_in_but_money_still_names_the_goods(said):
    """What comes in but money is still what a project names by the word: the goods, and no till."""
    said_as = assistant.asked([said], GOODS_IN)
    assert GOODS <= said_as.concepts
    assert not TILL & said_as.concepts


#: The till as the Hub has it, beside the goods it receives.
CAME_IN = [*TAKEN_OUT_OF_THE_TILL, RECEIVED[0]]


@pytest.mark.parametrize(
    "asked",
    [
        "apunta que entran 100 € en el turno",
        "registra que entran 100 € en el turno",
        "anota que han entrado 100 € en el turno",
        "apunta que entran en el turno 50 € de cambio",
    ],
)
def test_money_noted_down_as_come_in_is_the_tills_movement(asked):
    """Money noted down as come in is the till's movement: before receiving goods and before the writes of what nobody
    named (ERPlora/live#123)."""
    names = ranked(CAME_IN, asked, synonyms=GOODS_IN, app_words=till_apps)
    assert "cash_register.movement.add" in names, names[:6]
    before = set(names[: names.index("cash_register.movement.add")])
    assert not before & {"inventory.stock.receive", *(op.name for op in NOISE)}, names[:6]
