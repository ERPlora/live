"""What a turn offers for a yes, for the words of one thing in either language, and for a name given to a device or
a record."""

import pytest
from ninja import Schema

from live import assistant
from tests.assistant_catalogue import (
    APPROVED_OR_SWITCHED,
    DEVICES,
    HUB_WORDS,
    MENU,
    REGISTERED_AT_THE_TILL,
    NameIn,
    place,
    ranked,
    till_apps,
    tool,
)


@pytest.mark.parametrize(
    ("said", "language"),
    [
        ("sí, confírmalo", "es"), ("confirma", "es"), ("vale, confirmo", "es"), ("claro, confírmalo", "es"),
        ("adelante, confirma", "es"), ("confirma todo", "es"), ("confirma eso", "es"), ("confírmalo por favor", "es"),
        ("sí confírmalo", "es"), ("yes, confirm it", "en"), ("ok, confirm", "en"), ("sure, confirm that", "en"),
        ("please confirm it", "en"),
    ],
)
def test_a_yes_that_confirms_asks_nothing_of_its_own(said, language):
    """«Sí, confírmalo» answers what was asked before (a write the person agrees to), as a card's yes does: it asks to
    confirm nothing and names nothing (ERPlora/live#50)."""
    heard = assistant.asked([said])
    assert (heard.verbs, heard.concepts) == (frozenset(), frozenset()), heard


@pytest.mark.parametrize(
    ("said", "language"),
    [("confírmala para mañana", "es"), ("confirma la reserva de Ana", "es"), ("confirm Ana's booking", "en")],
)
def test_a_confirmation_of_a_thing_named_still_asks_to_confirm(said, language):
    assert "confirm" in assistant.asked([said]).verbs


def test_a_yes_said_with_the_write_leaves_the_write():
    """In one message too: «cancela la reserva de Ana, sí, confírmalo» asks to cancel it, not to confirm it."""
    assert assistant.asked(["cancela la reserva de Ana, sí, confírmalo"]).verbs == {"cancel"}


@pytest.mark.parametrize("said", ["sí, claro", "yes, sure"])
def test_the_words_of_a_yes_without_a_confirmation_are_read_as_said(said):
    """Only beside a verb that confirms is a yes left out: «sí, claro» alone is read as any other words."""
    assert assistant.asked([said]).concepts != frozenset()


@pytest.mark.parametrize(
    ("before", "yes", "language", "first"),
    [
        ("cancela la reserva de Ana", "sí, confírmalo", "es", "reservation.reservation.cancel"),
        ("cancela la cita de Ana de mañana", "vale, confirmo", "es", "appointment.appointment.cancel"),
        ("cancel Ana's reservation", "yes, confirm it", "en", "reservation.reservation.cancel"),
    ],
)
def test_a_yes_after_a_write_keeps_the_write_asked_first(before, yes, language, first):
    """A turn ranks the person's last two messages: after «cancela la reserva de Ana», «sí, confírmalo» keeps the
    cancellation first, never the confirmation of the booking it was not asked to confirm."""
    tools = {op.name: op for op in APPROVED_OR_SWITCHED}
    names = [op.name for op in assistant.relevant(tools, [before, yes], language, synonyms=HUB_WORDS)]
    assert names[0] == first, names[:4]


@pytest.mark.parametrize(
    ("said", "english"),
    [
        ("los avisos", "alert"), ("las notificaciones", "alert"), ("the notices", "notification"),
        ("los grupos", "group"), ("las compras", "purchase"), ("sus datos", "data"), ("las descargas", "download"),
        ("los dispositivos", "device"), ("este aparato", "device"), ("la carpeta", "folder"), ("mi perfil", "profile"),
        ("mi foto de perfil", "avatar"), ("la ficha", "card"), ("recibir", "receive"), ("la devolución", "refund"),
        ("el reembolso", "refund"), ("las cuentas aparcadas", "park"),
        ("las etiquetas", "tag"), ("el portátil", "device"), ("este ordenador", "device"), ("los ordenadores", "device"),
        ("la tablet", "device"),
        ("los comensales", "guest"), ("un comensal", "guest"), ("la regla", "rule"), ("las reglas", "rule"),
        ("el método de pago", "method"), ("los métodos", "method"),
        # A switch whose asks only say it in English is still its switch (ERPlora/live#89).
        ("los recordatorios", "reminder"), ("el recordatorio", "reminder"),
    ],
)
def test_the_words_of_one_thing_name_it_in_either_language(said, english):
    tools = [tool("a.other.list", "Lists them.", "query"), tool(f"x.{english}.list", "Lists them.", "query")]
    assert ranked(tools, f"¿qué pasa con {said}?")[0] == f"x.{english}.list"


@pytest.mark.parametrize(
    ("one", "other"),
    [
        ("tablet", "mesa"), ("tablets", "table"), ("compartido", "empresa"), ("compartida", "company"),
        ("peluquería", "peluquero"), ("carta", "carrito"), ("carta", "cart"), ("contratos", "control"),
        ("contraseña", "control"), ("ficha", "fichar"), ("fichas", "fichaje"), ("recibo", "recibir"),
        ("receipt", "receive"), ("settings", "set"), ("registros", "register"),
        # «Comensal» (a diner) is no «comentario» (a comment) nor «comenzar» (to begin): all three cut to «comen».
        ("comensales", "comentarios"), ("comensal", "comentario"), ("comensales", "comenzar"),
        # «Listo» (ready, done) is no «lista» nor «listar» (the command to list): all of them cut to «list» (live#54).
        ("listo", "lista"), ("listos", "listar"),
        # «Disponible» (available) is no «dispositivo» (a device): both cut to «dispo» (ERPlora/live#47).
        ("disponible", "dispositivo"), ("disponibles", "dispositivos"), ("disponibilidad", "dispositivo"),
        # To seal is no sale, to exist no stock, production no product and to check no purchase: each pair cut to one
        # stem, «sell», «exist», «produ» and «compr» (ERPlora/live#71).
        ("sella", "vende"), ("sellado", "venta"), ("sellar", "sell"), ("sello", "sale"), ("selle", "seller"),
        ("sellemos", "vendemos"), ("sellemos", "sellers"),
        # «Sellable» (English: what can be sold, a menu of Combos) is no «sella» either.
        ("sellable", "sella"), ("sellable", "sellado"),
        ("existiera", "existencias"), ("existir", "stock"), ("existe", "inventario"), ("existing", "stock"),
        ("exists", "inventory"),
        ("producción", "producto"), ("producciones", "productos"), ("production", "product"),
        ("comprueba", "compra"), ("comprobando", "compras"), ("comprobante", "purchase"), ("compruebo", "comprar"),
        # A reminder is no record: both cut to «recor» (ERPlora/live#89).
        ("recordatorio", "record"), ("recordatorios", "records"), ("recordatorios", "recordar"),
        # A computer is no putting in order nor an order: all of them cut to «orden» (ERPlora/live#61).
        ("ordenador", "ordena"), ("ordenadores", "ordenar"), ("ordenador", "orden"), ("ordenador", "ordenado"),
        ("ordenadores", "ordenadas"),
        # To confirm is no setting up: «confirma» and «configura» both cut to «confi» (ERPlora/live#68).
        ("confirma", "configura"), ("confirmación", "configuración"), ("confirm", "configure"),
        ("confírmalo", "ajustes"), ("confirmation", "settings"), ("confirmed", "setup"),
        # A tip is nothing of one's own: «propina», «propia» and «propio» all cut to «propi».
        ("propina", "propia"), ("propinas", "propios"), ("propina", "propio"),
    ],
)
def test_words_of_two_things_are_never_one_stem(one, other):
    """«Tablet» is no «table», «compartido» no «company», «peluquería» (the business) no «peluquero» (its staff)."""
    names = lambda said: assistant._concept(assistant._plain(said))  # noqa: E731
    assert names(one).isdisjoint(names(other))


@pytest.mark.parametrize(
    ("words", "stem"),
    [
        ("compartir compartido compartida", "compart"),
        ("peluquería peluquerías", "peluqueri"),
        ("propina propinas", "propina"),
        ("contrato contratos contract contracts", "contrat"),
        ("fichar fichaje fichajes fichado", "fichar"),
        ("ficha fichas", "ficha"),
        ("tablet tablets tableta", "tablet"),
        # An English verb that doubles its last letter: «tagged» is «tag»; «billing» keeps its «bill».
        ("tag tags tagged tagging", "tag"),
        ("stop stopped stopping", "stop"),
        ("bill billing billed", "bill"),
        ("setting settings", "setting"),
        ("registro registros", "registro"),
        ("comensal comensales", "comensal"),
        ("listo listos", "listo"),
        ("disponible disponibles disponibilidad", "dispon"),
        ("sella sellar sellado sellamos sellan séllalo sello sellos selló selle sellen sellemos selléis", "sellar"),
        ("existe existen existir existiera existía exist exists existing existed existence", "existir"),
        ("producción producciones production productions", "produccion"),
        ("comprueba compruebo comprobar comprobando comprobado comprobación comprobante compruébalo", "comprobar"),
        ("recordatorio recordatorios", "recordatori"),
        ("ordenador ordenadores", "ordenador"),
        ("confirma confirmar confirmo confírmalo confirmación confirmada confirm confirmed confirmation", "confirm"),
    ],
)
def test_the_forms_of_a_word_kept_apart_still_join(words, stem):
    assert assistant.stems(words) == {stem}


@pytest.mark.parametrize(
    ("one", "other"),
    [
        # What the words kept apart of ERPlora/live#71 were cut like still names what it named.
        ("vende", "sell"), ("venta", "selling"), ("ventas", "sells"), ("venta", "seller"),
        ("existencias", "stock"), ("existencia", "inventario"),
        ("producto", "product"), ("productos", "products"), ("artículo", "product"),
        ("compra", "purchase"), ("compras", "purchases"), ("comprar", "compro"),
        # Setting up keeps naming the settings once confirming leaves them (ERPlora/live#68).
        ("configura", "ajustes"), ("configuración", "settings"), ("configure", "setup"), ("configurar", "setting"),
    ],
)
def test_the_words_a_word_kept_apart_was_cut_like_still_name_one_thing(one, other):
    """«Sell», «existencias», «producto» and «compra» keep their groups: only the words kept apart leave them."""
    names = lambda said: assistant._concept(assistant._plain(said))  # noqa: E731
    assert not names(one).isdisjoint(names(other))


VERIFACTU_AND_ITS_NEIGHBOURS = [
    tool("verifactu.config.back_to_testing", "Goes back to the test environment of the tax agency while no record has "
         "been sent there.", asks={"es": ("vuelve VeriFactu al entorno de pruebas",)}),
    tool("verifactu.record.create", "Seals and chains the record of an invoice that has none.",
         asks={"es": ("sella y encadena el registro de la factura",)}),
    tool("verifactu.chain.validate", "Verify the VeriFactu chain of an issuer: every record's fingerprint is "
         "recomputed and must carry the previous one's.", "query",
         asks={"es": ("comprueba que la cadena de huellas no está rota",)}),
    tool("inventory.product.list", "Lists the products.", "query"),
    tool("inventory.product.set_sold_out", "Marks a product as sold out."),
    tool("inventory.product.export", "Exports the products."),
    tool("inventory.config.update", "Changes the stock settings: what counts as stock and its alerts."),
    tool("sale.sale.print", "Prints the ticket of a sale."),
    tool("sale.sale.void", "Voids a sale."),
    tool("sale.sale.refund", "Refunds a sale."),
    tool("customer.purchase.list", "Paginated purchase history of a customer: each sale with its amount.", "query",
         asks={"es": ("¿qué ha comprado Sara?", "las compras de Ana")}),
    tool("customer.purchase.divergences", "Reconciliation audit: the customers whose purchase count or spend disagree "
         "with their purchase history.", "query", asks={"es": ("revisa si cuadra el gasto de cada cliente",)}),
]


def test_sealing_in_production_brings_no_sale_stock_or_product_before_going_back_to_testing():
    """The probe of the QA of VeriFactu that ERPlora/live#71 reports 12th: «sellado» named a sale and «producción» a
    product, so the tools of Inventory and Sales came before going back to the test environment."""
    said = "vuelve al entorno de pruebas si todavía no se ha sellado ningún registro en producción"
    names = ranked(VERIFACTU_AND_ITS_NEIGHBOURS, said)
    others = [name for name in names if not name.startswith("verifactu.")]
    assert all(names.index("verifactu.config.back_to_testing") < names.index(other) for other in others), names


@pytest.mark.parametrize(
    ("said", "language"),
    [
        ("sella el registro si aún no existiera, en producción, comprobando la cadena", "es"),
        ("sella y encadena el registro de la factura de prueba si aún no existiera", "es"),
        ("seal the record if it does not exist yet: we are in production", "en"),
        ("check the existing chain before going to production", "en"),
    ],
)
def test_sealing_existing_production_and_checking_name_no_sale_stock_product_or_purchase(said, language):
    """The words of ERPlora/live#71 name what they say: none of them a sale, the stock, a product or a purchase."""
    named = assistant.asked([said]).concepts
    for thing in ("venta", "existencias", "producto", "compra"):
        assert assistant._concept(thing) not in named, thing


@pytest.mark.parametrize(
    ("said", "language"),
    [
        ("confirma la reserva de Ana", "es"), ("confírmame la cita de las cinco", "es"),
        ("la confirmación de la cita de Ana", "es"), ("¿está confirmada la reserva de Ana?", "es"),
        ("confirm Ana's booking", "en"), ("the confirmation of Ana's appointment", "en"),
        ("is Ana's booking confirmed?", "en"),
    ],
)
def test_confirming_names_no_settings(said, language):
    assert assistant._concept("ajustes") not in assistant.asked([said]).concepts


@pytest.mark.parametrize(
    ("said", "language"),
    [("configura las reservas", "es"), ("la configuración de las citas", "es"), ("set up the bookings", "en")],
)
def test_setting_up_names_no_confirmation(said, language):
    assert assistant._concept("confirma") not in assistant.asked([said]).concepts


@pytest.mark.parametrize(
    ("said", "language"),
    [("confirma la reserva de Ana", "es"), ("confirm Ana's booking", "en"), ("confirm the reservation", "en")],
)
def test_confirming_a_booking_offers_its_settings_after_the_booking(said, language):
    names = ranked(APPROVED_OR_SWITCHED, said, language)
    assert names[0] == "reservation.reservation.confirm", names
    assert names.index("reservation.settings.update") > names.index("reservation.reservation.list"), names


@pytest.mark.parametrize(
    ("said", "language"),
    [("configura las reservas", "es"), ("cambia la configuración de las reservas", "es")],
)
def test_setting_up_the_bookings_offers_no_confirmation_before_the_booking(said, language):
    """Setting up asks for a write: confirming a booking, or an appointment, is no closer to it than cancelling one."""
    names = ranked(APPROVED_OR_SWITCHED, said, language)
    assert names[0] == "reservation.settings.update", names
    for confirm in ("reservation.reservation.confirm", "appointment.appointment.confirm"):
        assert place(names, confirm) > names.index("reservation.reservation.cancel"), names


PAYING_WITH_ABONAR = ("abonar", "abona", "abonan", "abonas", "abonamos", "abonarlo", "abonarme", "abonale", "abonado",
                      "abonada", "abone", "abonen")


@pytest.mark.parametrize("form", PAYING_WITH_ABONAR)
def test_the_forms_of_abonar_name_paying(form):
    """«Abonar» is how Spain often says paying («¿cómo quiere abonarlo?»): each of its forms names what «pagar» does."""
    assert assistant._concept(form) == assistant._concept("pagar")


@pytest.mark.parametrize("word", ["abono", "abonos"])
def test_a_credit_note_or_a_voucher_names_no_paying(word):
    """«Abono» is a credit note («factura de abono») or a pass («un abono de 10 sesiones»), never a payment."""
    assert assistant._concept(word).isdisjoint(assistant._concept("pagar"))


@pytest.mark.parametrize(
    "said",
    ["abona la cuenta de la mesa 4", "abónale la cuenta a la mesa 4", "hay que abonar la cuenta de la mesa 4",
     "abónalo con tarjeta"],
)
def test_abonar_asks_to_charge_as_pagar_does(said):
    assert "complete" in assistant.asked([said]).verbs


@pytest.mark.parametrize(
    "said",
    ["¿se puede abonar con tarjeta?", "¿se puede pagar con tarjeta?", "¿con qué pueden abonarlo los clientes?",
     "¿de qué maneras pueden abonarme los clientes en caja?"],
)
def test_a_question_about_abonar_is_about_paying(said):
    assert assistant._concept("pagar") in assistant.asked([said]).about


@pytest.mark.parametrize(
    "said",
    ["haz una factura de abono para Ana", "véndele a Ana un abono de 10 sesiones", "¿cuántos abonos hicimos este mes?",
     "el abono de Ana"],
)
def test_a_credit_note_or_a_voucher_asks_for_no_payment(said):
    asked = assistant.asked([said])
    assert "complete" not in asked.verbs
    assert not asked.about
    assert all(concept.isdisjoint(assistant._concept("pagar")) for concept in asked.concepts), asked.concepts


ATTENDANCE_AND_CUSTOMER = [
    tool("attendance.record.clock_in", "Clocks a member in («ficha la entrada de Ana»): opens the working day."),
    tool("customer.customer.get", "A customer's card: data, notes and purchases.", "query"),
]


def test_the_customers_card_is_not_clocking_in():
    assert ranked(ATTENDANCE_AND_CUSTOMER, "abre la ficha de Marta")[0] == "customer.customer.get"
    assert ranked(ATTENDANCE_AND_CUSTOMER, "ficha la entrada de Ana")[0] == "attendance.record.clock_in"


@pytest.mark.parametrize(
    "asked",
    [
        "pon al dispositivo que estoy usando ahora el nombre «Barra»",
        "ponle a esta tablet el nombre «Barra»",
        "ponle de nombre «Barra» al dispositivo",
    ],
)
def test_a_name_put_on_a_device_renames_it(asked):
    """«Pon al dispositivo … el nombre «Barra»» renames it, as «ponle de nombre» does: the words between the verb and
    the name do not make it any change that takes a ``name`` (ERPlora/live#47, 43rd of 40 in the Hub)."""
    names = ranked(DEVICES, asked)
    assert names[0] == "base.device.rename", names[:4]


class DeviceIn(Schema):
    name: str
    printers: list[str]


#: The device the person is using set up to print, as the Hub describes it, beside the other tools of devices, the till
#: a device may be where something is registered, the creates of what «registra» also writes down and the writes of
#: things nobody names.
REGISTERED_DEVICES = [
    tool("printing.device.register", "Set up the device the person is using to print, with its name and the printers "
         "it reaches: from then on it prints their jobs with anybody's session.", input=DeviceIn,
         asks={"es": ("deja este equipo encargado de la impresión de los tickets",),
               "en": ("enroll this station as the one that prints",)}),
    tool("printing.device.list", "List the devices set up to print and when each was last seen.", "query"),
    tool("printing.device.update", "Change the name and the printers of a device set up to print.", input=DeviceIn),
    tool("printing.device.retire", "Retire a device set up to print: its jobs go back to the queue."),
    tool("base.device.list", "Lists the devices that use this business: tablets, laptops, phones.", "query"),
    tool("base.device.rename", "Names a device of this business («Barra», «Cocina»).", input=NameIn),
    tool("cash_register.session.open", "Open the till: start a cash session with its opening float."),
    tool("cash_register.session.close", "Close the open cash session of the till with the cash counted."),
    *REGISTERED_AT_THE_TILL,
]


@pytest.mark.parametrize(
    ("asked", "language"),
    [
        ("registra esta tablet como Tablet Barra", "es"),
        ("regístrame este ordenador como Caja 2", "es"),
        ("hay que registrar la tablet nueva de la terraza", "es"),
        ("registra este dispositivo como Tablet QA y dale acceso a la impresora Caja QA", "es"),
        ("register this tablet as Bar tablet", "en"),
        ("please register this laptop as Office", "en"),
        ("can you register the new tablet for printing?", "en"),
    ],
)
def test_a_device_registered_is_set_up_to_print(asked, language):
    """«Registra esta tablet como Tablet Barra» sets the device up to print: registering a device asks for the action
    of that name, before the creates and the adds of what nobody named (ERPlora/live#117: read as creating or adding
    only, it came 61st in the Hub, 54th in English)."""
    names = ranked(REGISTERED_DEVICES, asked, language, app_words=till_apps)
    assert names[0] == "printing.device.register", names[:5]


@pytest.mark.parametrize(
    ("asked", "language", "first"),
    [
        # The device is where something is registered, not what is.
        ("registra en esta tablet una salida de 15 € para hielo", "es", "cash_register.movement.add"),
        ("registra una salida de 15 € desde la tablet de la barra", "es", "cash_register.movement.add"),
        ("registra un cliente nuevo desde esta tablet", "es", "customer.customer.create"),
        ("registra desde esta tablet una salida de 20 € para pan", "es", "cash_register.movement.add"),
        ("registra con esta tablet una entrada de 50 € de cambio", "es", "cash_register.movement.add"),
        # English's «register» is also the till: only where it starts the command does it register.
        ("open the register on this tablet with a 100 € float", "en", "cash_register.session.open"),
        ("close the register on the bar tablet", "en", "cash_register.session.close"),
        ("register 2: close it from this tablet", "en", "cash_register.session.close"),
        ("register on this tablet won't open, open it with a 50 € float", "en", "cash_register.session.open"),
    ],
)
def test_a_device_named_but_not_registered_is_not_set_up_to_print(asked, language, first):
    """A device named beside «registra» is set up to print only when it is what is registered: «registra en esta tablet
    una salida de 15 €» notes the money down and «open the register on this tablet» opens the till, so their tools come
    before setting the tablet up (ERPlora/live#117: with any device named, the money came 15th in the Hub, not 14th,
    and opening the till 20th, not 8th)."""
    names = ranked(REGISTERED_DEVICES, asked, language, app_words=till_apps)
    device = place(names, "printing.device.register")
    assert device > place(names, first) or device == len(names), names[:5]


class OptionReorderIn(Schema):
    combo_id: str
    group_id: str
    option_ids: list[str]


class OptionUpdateIn(Schema):
    combo_id: str
    id: str
    product: str | None = None
    price_delta: int | None = None
    is_available: bool | None = None


#: The choices and the courses of a menu as the Hub's Menus describe them and ask for them, beside the tools of
#: devices: changing a choice shares a word with the request (its flan), reordering them does not.
MENU_CHOICES = [
    tool("combo.option.reorder", "Put the choices of a course in a new order (the order the till shows them in): give "
         "every choice id, in order.", input=OptionReorderIn,
         asks={"es": ("ordena los postres del menú infantil: helado, natillas y fruta",),
               "en": ("sort the desserts of the kids' menu: ice cream, custard, fruit",)}),
    tool("combo.option.update", "Change a choice: its supplement, mark it sold out («no flan today in the menu of the "
         "day»: is_available false) or back on offer, or replace its product. It keeps its place.",
         input=OptionUpdateIn, asks={"es": ("se han acabado las natillas del menú infantil",),
                                     "en": ("the custard is sold out in the kids' menu",)}),
    tool("combo.option.bulk_create", "Offer several products at once in a course, without supplement, in the order "
         "given; all or nothing."),
    tool("combo.option.create", "Offer a product as a choice of a course: it goes last."),
    tool("combo.option.delete", "Remove a choice from its course."),
    tool("combo.group.reorder", "Put the courses of a menu in a new order (the order the till asks them in): give "
         "every course id, in order."),
    tool("combo.combo.update", "Change a menu: its name, its price."),
    *REGISTERED_DEVICES,
]
#: The Hub's words for a choice of a menu.
CHOICE = (("opcion", "opciones", "eleccion", "elecciones", "option", "options", "choice", "choices"),)


@pytest.mark.parametrize(
    ("asked", "language"),
    [
        ("ordena las opciones del primer plato", "es"),
        ("ordena las opciones de Platos QA del Menú QA así: flan, merluza, lentejas y café, incluyendo todas", "es"),
        ("reorder the choices of the first course", "en"),
    ],
)
def test_putting_things_in_order_offers_reordering_them_first(asked, language):
    """«Ordena» puts things in order and names no computer (ERPlora/live#61: reordering the choices of a menu came 9th
    in the Hub, after changing a printing device). It also asks ``update``, for what nothing reorders: where a tool
    reorders, that one comes first, even when the change of the same thing shares a word with the request."""
    names = ranked(MENU_CHOICES, asked, language, synonyms=CHOICE)
    assert names[0] == "combo.option.reorder", names[:5]


@pytest.mark.parametrize(
    ("asked", "language"),
    [
        ("ofrece en Platos QA del Menú QA, y en este orden, lentejas, merluza y flan, todos sin suplemento", "es"),
        ("add to the first course, in this order, lentils, hake and flan", "en"),
    ],
)
def test_a_list_said_in_order_offers_no_device_first(asked, language):
    names = ranked(MENU_CHOICES, asked, language, synonyms=CHOICE)
    ahead = names[: names.index("combo.option.bulk_create")]
    assert not [name for name in ahead if ".device." in name], names[:8]


@pytest.mark.parametrize(
    ("said", "names_a_device"),
    [
        ("ordena las opciones del primer plato", False),
        ("pon los platos en este orden: sopa, merluza y flan", False),
        ("borra el ordenador de la oficina", True),
        ("ordena los ordenadores por nombre", True),
    ],
)
def test_only_a_computer_is_a_device_to_act_on(said, names_a_device):
    device = assistant._concept("dispositivo")
    assert any(not thing.isdisjoint(device) for thing in assistant.asked([said]).objects) is names_a_device


@pytest.mark.parametrize(
    ("said", "verbs"),
    [
        ("registra esta tablet como Tablet Barra", {"create", "add", "register"}),
        ("regístrame este ordenador como Caja 2", {"create", "add", "register"}),
        ("register this tablet as Bar tablet", {"create", "register"}),
        ("please register this laptop as Office", {"create", "register"}),
        ("rename it and register this device as Bar 2", {"rename", "create", "register"}),
        ("rename it then register this device as Bar 2", {"rename", "create", "register"}),
        # Said twice, as the command and as the till: the command still registers.
        ("register this tablet and close the register", {"close", "create", "register"}),
        # The device said right after as where or with what it is done is not what is registered.
        ("registra desde esta tablet una salida de 20 €", {"create", "add"}),
        ("registra con esta tablet una entrada de 50 €", {"create", "add"}),
        ("regístrame desde este ordenador un cliente nuevo", {"create", "add"}),
        # The till said by its number or with where it is, even first in the sentence.
        ("register 2: close it from this tablet", {"close", "create"}),
        ("register on this tablet won't open", {"open", "create"}),
        ("register from the bar tablet is stuck", {"create"}),
        ("registra 2 tablets nuevas para la terraza", {"create", "add", "register"}),
        # English's «register» is also the till: anywhere but where a command starts it registers nothing.
        ("open the register on this tablet", {"open", "create"}),
        ("close the cash register", {"close", "create"}),
        # The money taken out asks to add it (ERPlora/live#118).
        ("take 15 € out of the register for ice", {"add", "create"}),
        # What happened, noted down, sets nothing up (ERPlora/live#116).
        ("registra que la tablet de la barra se ha roto", {"create", "add"}),
        ("regístrame que entran 20 cafés", {"create", "add"}),
    ],
)
def test_registering_asks_to_register_only_as_the_command(said, verbs):
    """«Registra» and «register» ask to register what the command registers («registra esta tablet»), never where
    English's «register» is the till nor what happened, noted down («registra que la tablet se ha roto»)."""
    assert assistant.asked([said]).verbs == verbs


@pytest.mark.parametrize(
    ("said", "verbs"),
    [
        # A name the thing is found by is no name put on it.
        ("pon el precio del menú con el nombre «Café» a 3 €", {"set", "update"}),
        ("change the price of the menu with the name Coffee", {"change", "set", "update"}),
        ("cambia la reserva bajo el nombre de García a las nueve", {"change", "set", "update"}),
        ("change the booking under the name Smith to nine", {"change", "set", "update"}),
        ("ponle al menú de nombre «Carta» un precio", {"add", "set", "update"}),
        # Also said apart, after «a», «al», «for» (ERPlora/live#59: «pon el precio…» is a verb with its own object).
        ("ponle al menú con el nombre «Café» un precio de 3 €", {"add", "set", "update"}),
        ("change for the menu with the name Coffee the price to 3", {"change", "set", "update"}),
        ("cámbiale a la reserva bajo el nombre de García la hora", {"change", "set", "update"}),
        ("change for the booking under the name Smith the time", {"change", "set", "update"}),
        ("cámbiale a la reserva buscada por el nombre de García la hora", {"change", "set", "update"}),
        ("change for the booking found by the name Smith the time", {"change", "set", "update"}),
        ("change for the tablet the colour of the name to red", {"change", "set", "update"}),
    ],
)
def test_a_name_that_finds_the_thing_is_no_rename(said, verbs):
    assert assistant.asked([said]).verbs == verbs


@pytest.mark.parametrize(
    ("said", "verbs"),
    [
        ("cambia el precio del café y dime el nombre del cliente", {"change", "list", "set", "update"}),
        ("change the price of the coffee and tell me the name of the customer", {"change", "set", "update"}),
        # Dictated, with no «y» between the two commands.
        ("cambia el precio del café dime el nombre del cliente", {"change", "list", "set", "update"}),
        # The other command with its pronouns.
        ("cámbiale el precio al café y búscame el nombre del cliente", {"change", "list", "set", "update"}),
    ],
)
def test_a_name_another_command_asks_for_is_no_rename(said, verbs):
    """«Cambia el precio … y dime el nombre del cliente» asks for two things: «el nombre» is of «dime», no name put on
    anything, and «cambia» still changes (ERPlora/live#57, born of live#47's names said apart)."""
    assert assistant.asked([said]).verbs == verbs


def test_a_change_with_a_name_asked_after_it_is_no_rename():
    """The writes that change come before the rename when the name is asked for by another command (ERPlora/live#57)."""
    names = ranked(MENU, "cambia el precio del menú y dime el nombre del cliente")
    assert names.index("menu.menu.update") < names.index("menu.menu.rename"), names[:6]


@pytest.mark.parametrize(
    "said",
    [
        # A verb's word said of the thing named (after an article, or a «que» that says which) starts no command.
        "ponle a la lista de precios el nombre «Verano»",
        "change on the list its name to Summer",
        "pon a la tablet que cobra en la barra el nombre «Barra»",
        # Nor a word of a verb that names a thing (``_NOT_VERBS``).
        "ponle a la mesa nueva el nombre «Terraza»",
        # Nor the verb's word after one of those («la nueva lista» is a list, no «lista las…»).
        "ponle a la nueva lista de precios el nombre «Verano»",
        "change on the new list its name to Summer",
    ],
)
def test_a_verbs_word_said_of_the_thing_named_still_renames(said):
    assert {"rename", "set", "update"} <= assistant.asked([said]).verbs


@pytest.mark.parametrize(
    "said",
    [
        *(f"ponle a {which} lista de precios el nombre «Verano»" for which in ("mi", "tu", "su", "nuestra", "esta", "esa")),
        *(f"change on {which} list its name to Summer" for which in ("my", "your", "our", "this", "that")),
    ],
)
def test_a_verbs_word_after_whose_or_which_thing_it_is_still_renames(said):
    """«Esta lista», «mi lista», «this list» say which thing is named, like an article: no other command starts there
    (the Hub's price lists are «lista de precios»; a name said apart renamed them before ERPlora/live#57)."""
    assert {"rename", "set", "update"} <= assistant.asked([said]).verbs


@pytest.mark.parametrize(
    ("said", "verbs"),
    [
        # After an ordinal, «de», «for», «on» or another noun, a verb's word («lista», «muestra», «list», «register»)
        # is of the thing named.
        ("ponle a la primera lista el nombre «Verano»", {"list", "rename", "set", "update"}),
        ("pon a la tarifa de muestra el nombre «Demo»", {"list", "rename", "set", "update"}),
        ("change for the price list the name to Summer", {"list", "rename", "set", "update"}),
        ("change on my price list the name to Summer", {"list", "rename", "set", "update"}),
        ("change for register 2 the name to Bar", {"create", "rename", "set", "update"}),
        ("change on register 2 the name to Bar", {"create", "rename", "set", "update"}),
        # The name said in a row, with a verb's word that ends the sentence.
        ("cámbiale el nombre a la primera lista", {"list", "rename", "set", "update"}),
        ("change its name for the price list", {"list", "rename", "set", "update"}),
    ],
)
def test_a_verbs_word_inside_the_name_of_the_thing_still_renames(said, verbs):
    """A verb's word starts another command only where one starts («y», «then», its pronouns); inside what names the
    thing it is a noun: «la primera lista», «the price list», «register 2» (ERPlora/live#59, born of live#58)."""
    assert assistant.asked([said]).verbs == verbs


@pytest.mark.parametrize(
    "said",
    [
        # After «y» / «and», a word of ``_NOT_VERBS`` still names («la temporada baja y alta», «old and new»).
        "cámbiale a la tarifa de temporada baja y alta el nombre «Verano»",
        "change for the old and new price list the name to Summer",
        # Nor a word that is no verb («vinos y cervezas»).
        "ponle a la carta de vinos y cervezas el nombre «Bodega»",
        "change for the wine and beer list the name to Cellar",
    ],
)
def test_a_word_that_names_after_and_still_renames(said):
    assert {"rename", "set", "update"} <= assistant.asked([said]).verbs


@pytest.mark.parametrize(
    ("said", "verbs"),
    [
        # Each word after which a verb starts another command, in its language: the name said apart from a verb
        # whose thing goes after «al» / «for» («cámbiale al café el precio…»).
        ("cámbiale al café el precio y muestra el nombre del cliente", {"change", "list", "set", "update"}),
        ("cámbiale al café el precio e imprime el nombre del cliente", {"change", "print", "set", "update"}),
        ("cámbiale al café el precio y luego muestra el nombre del cliente", {"change", "list", "set", "update"}),
        ("cámbiale al café el precio y después muestra el nombre del cliente", {"change", "list", "set", "update"}),
        ("cámbiale al café el precio y también muestra el nombre del cliente", {"change", "list", "set", "update"}),
        ("change for the coffee the price and show the name of the customer", {"change", "list", "set", "update"}),
        ("change for the coffee the price then show the name of the customer", {"change", "list", "set", "update"}),
        ("change for the coffee the price and also show the name of the customer", {"change", "list", "set", "update"}),
        # Dictated, the other command with its pronouns: at its end in Spanish, after it in English; or what only asks.
        ("cámbiale al café el precio búscame el nombre del cliente", {"change", "list", "set", "update"}),
        ("cámbiale al café el precio dame el nombre del cliente", {"change", "get", "set", "update"}),
        ("change for the coffee the price show me the name of the customer", {"change", "list", "set", "update"}),
        ("change for the coffee the price show us the name of the customer", {"change", "list", "set", "update"}),
        ("change for the coffee the price and tell me the name of the customer", {"change", "set", "update"}),
    ],
)
def test_a_name_asked_by_a_command_that_starts_there_is_no_rename(said, verbs):
    """Another command starts after «y», «e», «luego», «después», «también», «and», «then», «also», or said with its
    pronouns («búscame», «dame», «show me»): «el nombre» after it is the one it asks for (ERPlora/live#59)."""
    assert assistant.asked([said]).verbs == verbs


@pytest.mark.parametrize(
    "said",
    [
        # Each article that opens the verb's own object, in its language.
        "cambia el precio del café muestra el nombre del cliente",
        "cambia la hora de la reserva muestra el nombre del cliente",
        "cambia los precios del café muestra el nombre del cliente",
        "cambia las horas de la reserva muestra el nombre del cliente",
        "change the price of the coffee list the name of the customer",
    ],
)
def test_a_verb_with_its_own_object_puts_no_name_said_later(said):
    """Dictated with no «y» nor pronouns, a second command («muestra», «list») is no word of the thing named: a verb
    followed by its own object («cambia el precio…») names nothing with «el nombre» said later, it is what that
    command asks for (ERPlora/live#59; a name said apart goes after «a», «for», «on»: «ponle a la lista el nombre»)."""
    assert assistant.asked([said]).verbs == {"change", "list", "set", "update"}


@pytest.mark.parametrize(
    ("said", "verbs"),
    [
        # A naming verb that ends the sentence has no word after it to be its own object.
        ("el nombre de la tablet lo quiero cambiar", {"change", "set", "update"}),
        ("that name I want to change", {"change", "set", "update"}),
    ],
)
def test_a_naming_verb_that_ends_the_sentence_is_read(said, verbs):
    assert assistant.asked([said]).verbs == verbs
