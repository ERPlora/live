"""The few tools a turn offers of a catalogue of hundreds (``live.assistant.relevant``): what a person asks, in their
everyday words in Spanish or English, reaches the operation that does it.

The QA battery of the assistant with the real model (2026-10-31; ERPlora/live issue of the selection) found three
questions of an owner that never reached their tool: «Da de alta al empleado…» (``staff.member.create``), «¿Qué
vendí hoy?» (a read of ``sale``) and «Activa la app de clientes» (``base.app.enable``). The catalogue they rank is a
slice of the Hub's, with its real descriptions, drowned in tools that share the verb and nothing else, as the
Hub's 700 do.
"""

import time
from collections import Counter

import pytest
from ninja import Schema

from live import assistant
from tests.assistant_catalogue import CHECK, HUB_SLICE, MENU, NOISE, offered, ranked, tool


@pytest.mark.parametrize(
    ("language", "asked", "expected"),
    [
        ("es", "Da de alta al empleado «Luis QA» como cajero", "staff.member.create"),
        ("en", "Add the employee «Luis QA» as a cashier", "staff.member.create"),
        ("es", "¿Qué vendí hoy?", "sale.sale.today"),
        ("en", "What did I sell today?", "sale.sale.today"),
        ("es", "Activa la app de clientes", "base.app.enable"),
        ("en", "Turn on the customers app", "base.app.enable"),
        ("es", "Desactiva la app de clientes", "base.app.disable"),
        ("es", "Crea el cliente «Ana QA» con teléfono 600000000", "customer.customer.create"),
        ("es", "Borra el cliente «Ana QA»", "customer.customer.delete"),
        ("es", "Crea el producto «Café QA» a 1,50 € con IVA 10 %", "inventory.product.create"),
        # Review of live#18: a table named is not what is charged, nor the people of a reservation its staff.
        ("es", "Cobra la mesa 4", "sale.sale.complete"),
        ("en", "Charge table 4", "sale.sale.complete"),
        ("es", "Reserva una mesa para 4 personas", "reservation.reservation.create"),
    ],
)
def test_the_operation_that_does_what_was_asked_comes_first(language, asked, expected):
    assert offered(asked, language=language)[0] == expected


def test_a_question_without_a_write_offers_the_reads_of_what_it_names_before_its_writes():
    ranked = offered("¿Qué vendí hoy?")
    sale = [name for name in ranked if name.startswith("sale.")]
    assert sale[:2] == ["sale.sale.today", "sale.sale.list"]


def test_the_people_who_work_in_the_business_are_its_staff_whatever_the_person_calls_them():
    for asked in ("¿Cuántos empleados tengo?", "¿Quién trabaja hoy?", "Lista el personal", "Show my workers"):
        ranked = offered(asked)
        assert ranked.index("staff.member.list") < ranked.index("appointment.thing00.list"), asked


def test_the_people_of_a_reservation_are_not_the_staff():
    """«personas» and «personal» (the staff, the Hub's «Personal») share their first five letters: never their stem."""
    ranked = offered("Reserva una mesa para 4 personas")
    last = max(ranked.index(name) for name in ranked if name.startswith(("reservation.", "table.")))
    assert all(index > last for index, name in enumerate(ranked) if name.startswith("staff."))


def test_what_a_write_takes_is_what_it_changes():
    """«Cambia el precio del café»: the product's own write takes a price; it comes before every write that only
    shares the verb, though no product is named."""
    ranked = offered("Cambia el precio del café a 1,80")
    assert ranked.index("inventory.product.update") < ranked.index("appointment.thing00.update")
    # And before the reads of the price lists, which only name the price.
    assert ranked.index("inventory.product.update") < ranked.index("pricing.price_list.list")


def test_a_question_without_a_verb_offers_the_reads_of_what_it_names_first():
    ranked = offered("¿Qué mesas tengo?")
    assert [name for name in ranked if name.startswith("table.")] == ["table.table.list", "table.table.create"]


def test_a_verb_said_in_two_words_asks_for_nothing_else():
    """«Turn on» is ``enable``: its «turn» is not a «turno» (a shift of the schedule)."""
    assert "staff.shift.list" not in offered("Turn on the customers app", language="en")


def test_a_tool_that_names_two_things_asked_ranks_before_one_that_names_one_in_many_words():
    """A thing counts once, however many of its synonyms a tool says: «employee, worker and team member» is one."""
    tools = {
        op.name: op
        for op in (
            tool("x.a.list", "Lists each employee, worker and team member.", "query"),
            tool("x.b.list", "Lists the staff at each table.", "query"),
        )
    }
    ranked = [op.name for op in assistant.relevant(tools, ["¿Qué empleados hay en cada mesa?"], "es")]
    assert ranked == ["x.b.list", "x.a.list"]


def test_what_people_say_to_ask_for_a_tool_names_it_as_its_description_does():
    """Its asks (``AI.asks``) are words of the tool as its description's are: the phrases people really use, in any
    language, bring it to what they ask. Without them the two tie, and the first by name would win."""
    tools = {
        op.name: op
        for op in (
            tool("x.a.list", "Lists the documents of the business.", "query"),
            tool("x.b.list", "Lists the documents of the business.", "query",
                 asks={"es": ("¿cuánto he facturado este mes?", "lo facturado"), "en": ("my billing this month",)}),
        )
    }
    for asked, language in (("¿Cuánto llevo facturado?", "es"), ("Show my billing", "en")):
        assert [op.name for op in assistant.relevant(tools, [asked], language)] == ["x.b.list", "x.a.list"], asked


def test_a_tools_asks_are_read_once_however_many_turns_rank_it(monkeypatch):
    """The QA ranks once per ask of a catalogue of hundreds: what each tool says is read once, not once per turn."""
    read = Counter()
    real = assistant.asks_of
    monkeypatch.setattr(assistant.ranking, "asks_of", lambda op: read.update([op.name]) or real(op))
    tools = {
        op.name: op
        for op in (tool(f"x.thing{i}.create", "Creates a thing.", asks={"es": ("créame una cosa", "otra cosa")})
                   for i in range(50))
    }
    for asked in ("créame una cosa", "¿qué cosas hay?", "borra la cosa"):
        assistant.relevant(tools, [asked], "es")
    assert len(read) == 50 and set(read.values()) == {1}


def test_the_same_question_is_offered_the_same_tools():
    assert offered("¿Qué vendí hoy?") == offered("¿Qué vendí hoy?")


@pytest.mark.parametrize(
    ("said", "stem"),
    [
        # A verb in its tenses and forms, a noun and its plural: one stem.
        ("vendí vendido vender vendimos vendiste vendiendo", {"vend"}),
        ("venta ventas", {"vent"}),
        ("cliente clientes clienta client", {"clien"}),
        ("member members", {"memb"}),
        ("customer customers", {"custo"}),
        ("app apps", {"app"}),
        ("persona personas", {"perso"}),
        ("personal", {"personal"}),
        ("sale sales", {"sale"}),
        ("servicio service", {"servi"}),
        # A plural never shortens a word into another: «mesa» (a table) is never «mes» (a month).
        ("mesa mesas", {"mesa"}),
        ("mes", {"mes"}),
    ],
)
def test_the_words_of_a_text_are_stems_that_join_its_forms(said, stem):
    assert assistant.stems(said) == stem


@pytest.mark.parametrize(("said", "word"), [("¿Qué es la CAJA?", "caja"), ("What is the price of this?", "price")])
def test_accents_case_and_the_words_that_ask_nothing_are_not_words_of_a_tool(said, word):
    assert assistant.stems(said) == assistant.stems(word) != set()


def test_a_turn_ranks_the_hubs_catalogue_in_a_few_milliseconds():
    """No network call and no model: the selection runs on every turn, before the gateway."""
    many = {op.name: op for op in (tool(f"app{i % 28}.thing{i}.create", f"Creates thing {i} of the business with its "
                                        f"name, price and tax category; refused when it exists.") for i in range(720))}
    assistant.relevant(many, ["Da de alta al empleado «Luis QA» como cajero"], "es")  # the stems of the catalogue, once
    timings = []
    for _ in range(5):
        start = time.perf_counter()
        assistant.relevant(many, ["Da de alta al empleado «Luis QA» como cajero", "¿Qué vendí hoy?"], "es")
        timings.append(time.perf_counter() - start)
    assert min(timings) < 0.100  # ~2 ms here; generous for a loaded CI runner


# ── What the asks of the SaaS, ``sale``, ``customer`` and ``base`` found (2026-10-31) ──────────────────────────────
#
# Writing the phrases people use for every tool of an app, and ranking them with every app on, showed words the
# selection read wrong: a verb with its pronouns, a question word read as «list», a yes/no question read as a write,
# words of two things cut to one stem, and the words of an app's name drowning the thing asked. Each test below is a
# small catalogue with the real collision: two apps competing for the same words.



@pytest.mark.parametrize(
    ("said", "verb", "expected"),
    [
        ("cóbrale", "cobra cobrar", "cobr"),
        ("ponle", "pon poner", "pon"),
        ("súbele", "sube subir", "sub"),
        ("quítale", "quita quitar", "quit"),
        ("apúntame", "apunta apuntar", "apunt"),
        ("descárgame", "descarga descargar", "desca"),
        ("sácame", "saca sacar", "sac"),
        ("hazle", "haz hacer", "hac"),
        ("dime", "decir", "dec"),
    ],
)
def test_a_spanish_verb_with_its_pronouns_is_the_verb(said, verb, expected):
    """«Cóbrale», «súbele», «dime»: the pronouns a Spanish command carries («le», «me», «lo»…) are not its stem."""
    assert assistant.stems(said) == assistant.stems(verb) == {expected}


def test_a_charge_said_with_its_pronoun_is_a_charge():
    assert offered("cóbrale a la mesa 4")[0] == "sale.sale.complete"


@pytest.mark.parametrize(
    ("asked", "language", "first"),
    [
        ("mete un menú", "es", {"add"}),
        ("añade un menú", "es", {"add", "create"}),
        ("ponle un menú", "es", {"add", "set", "update"}),
        ("get rid of the menu", "en", {"delete", "remove"}),
        ("delete the menu", "en", {"delete", "remove"}),
        ("borra el menú", "es", {"delete", "remove"}),
        ("borremos todos sus datos del menú", "es", {"erase"}),
        ("erase the menu", "en", {"erase"}),
        ("set up the menu", "en", {"update"}),
        ("does the menu add up?", "en", {"check", "stats"}),
        ("¿cuadran los menús?", "es", {"check", "stats"}),
        ("how many menus are there?", "en", {"count", "list"}),
        ("¿cuántos menús hay?", "es", {"count", "list"}),
        ("exporta los menús", "es", {"export"}),
        ("descárgame los menús", "es", {"export"}),
        ("download the menus", "en", {"export"}),
        ("importa los menús", "es", {"import"}),
        ("súbeme los menús", "es", {"import"}),
        ("import the menus", "en", {"import"}),
        ("cambia el nombre del menú", "es", {"rename", "set", "update"}),
        ("change the name of the menu", "en", {"rename", "set", "update"}),
        ("rename the menu", "en", {"rename"}),
        ("ordena el menú", "es", {"update"}),
        ("reorder the menu", "en", {"update"}),
        ("apunta un menú", "es", {"add", "create"}),
        ("empieza un menú", "es", {"open", "start"}),
        ("start a menu", "en", {"open", "start"}),
        ("ponle de nombre «Carta de verano» al menú", "es", {"rename"}),
        # The name put with what it names in between (ERPlora/live#47): as a rename as «ponle el nombre» in a row.
        ("pon al menú que estamos usando ahora el nombre «Carta de verano»", "es", {"rename", "set", "update"}),
        ("ponle al menú el nombre «Carta de verano»", "es", {"rename", "set", "update"}),
        ("cámbiale al menú de la terraza el nombre", "es", {"rename", "set", "update"}),
        ("hay que ponerle al menú el nombre «Carta de verano»", "es", {"rename", "set", "update"}),
        ("pon el nombre «Carta de verano» al menú", "es", {"rename"}),
        # In English too: «change … the name», «change … its name».
        ("change for this menu the name to Summer", "en", {"rename", "set", "update"}),
        ("change on the menu we use now its name to Summer", "en", {"rename", "set", "update"}),
        # «Quiero empezar con…» starts from something (a template): it opens nothing.
        ("quiero empezar con el menú", "es", {"aaa"}),
    ],
)
def test_the_action_asked_is_the_one_people_mean(asked, language, first):
    """«Get rid of» is a delete, never a ``get``; «set up» never a ``set``; «add up» checks, it adds nothing."""
    actions = [name.split(".")[-1] for name in ranked(MENU, asked, language)]
    assert set(actions[: len(first)]) == first, actions[:4]


def test_a_question_word_is_no_list_verb():
    """«How» and «which» ask to know: they are no «list» that every list of the catalogue answers."""
    tools = [
        tool("printing.settings.get", "The printing settings: the default printer, the paper width and the copies of "
             "each ticket.", "query"),
        tool("printing.printer.list", "Lists the printers of the business.", "query"),
        *NOISE,
    ]
    assert ranked(tools, "how is the printer set up?", "en")[0] == "printing.settings.get"
    assert ranked(tools, "which printer settings do I have?", "en")[0] == "printing.settings.get"


def test_how_many_counts_what_it_names_not_every_list():
    """«How many» and «cuántos» ask to count the thing named: the lists of other things share the verb, nothing else."""
    tools = [*NOISE, tool("zz.dish.stats", "Counts the dishes served today.", "query")]
    for asked, language in (("how many dishes were served?", "en"), ("¿cuántos platos se sirvieron hoy?", "es"),
                            ("enséñame los datos de los platos de hoy", "es")):
        assert ranked(tools, asked, language)[0] == "zz.dish.stats", asked


DOCS = tool("zz.docs.search", "Searches ERPlora's help for how something is done.", "query")
INVITE = [
    DOCS,
    tool("hubs.member.invite", "Invites a person to one of the account's businesses by email, with a role."),
    tool("hubs.member.list", "Lists the people of a business and their roles.", "query"),
    *NOISE,
]


@pytest.mark.parametrize(
    ("asked", "language"),
    [
        ("how do I invite someone to my business?", "en"),
        ("¿cómo invito a alguien a mi negocio?", "es"),
        ("¿Cómo configuro la impresora?", "es"),
        ("how can I set up the printer?", "en"),
        ("¿cómo se cierra la caja?", "es"),
    ],
)
def test_a_how_to_question_reaches_the_documentation_by_its_words(asked, language):
    """A how-to question is answered from the help (``howto``): it comes among the first by being one, not only because
    a project keeps it always at hand."""
    assert DOCS.name not in ranked(INVITE, asked, language)[:3]
    assert DOCS.name in ranked(INVITE, asked, language, howto=[DOCS.name])[:3]


@pytest.mark.parametrize(
    ("asked", "language"),
    [("how many people are in my business?", "en"), ("¿cómo van las ventas?", "es"), ("invita a Luis", "es")],
)
def test_what_is_no_how_to_question_does_not_bring_the_documentation(asked, language):
    assert ranked(INVITE, asked, language, howto=[DOCS.name]) == ranked(INVITE, asked, language)


SALE_SETTINGS = tool("sale.settings.get", "The till settings: whether a customer is required to charge, the default "
                     "payment method and the tip options.", "query")


@pytest.mark.parametrize(
    ("asked", "language"),
    [("do I need a customer to charge?", "en"), ("¿hace falta poner cliente para cobrar?", "es")],
)
def test_a_yes_or_no_question_asks_to_know(asked, language):
    """«Do I need a customer to charge?» asks how the till works: its reads come before charging."""
    names = ranked([*HUB_SLICE, SALE_SETTINGS, *NOISE], asked, language)
    assert "sale.sale.complete" not in names[:3]
    assert names.index("sale.settings.get") < names.index("sale.sale.complete")


def test_what_can_be_refunded_reaches_the_options_not_the_history():
    tools = [
        tool("sale.refund.options", "What a sale can still give back, for each tender and each line.", "query"),
        tool("sale.refund.list", "List the refunds of a sale, newest first.", "query"),
        *NOISE,
    ]
    assert ranked(tools, "Check what can be refunded", "en")[0] == "sale.refund.options"


def test_a_reorder_reaches_the_operation_that_reorders():
    """«Reorder» and «ordena» put things in a new order: the operation that does only that (``reorder``) comes before
    the write that changes anything of them (``update``), which they reach where nothing reorders («ordena el menú»,
    ``test_the_action_asked_is_the_one_people_mean``)."""
    tools = [
        tool("combo.group.reorder", "Put the courses of a menu in a new order (the order the till asks them in): give "
             "every course id, in order."),
        tool("combo.group.update", "Change a course: its name, minimum and maximum picks, or whether a choice may "
             "repeat. Only the fields sent change; it keeps its place."),
        tool("combo.option.reorder", "Put the choices of a course in a new order (the order the till shows them in): "
             "give every choice id, in order."),
        tool("combo.option.update", "Change a choice: its supplement, mark it sold out or back on offer, or replace "
             "its product. It keeps its place."),
        *NOISE,
    ]
    for asked, language, thing in (("reorder the courses of the menu", "en", "group"),
                                   ("reorder the choices of the first course", "en", "option"),
                                   ("ordena los platos del menú", "es", "group")):
        names = ranked(tools, asked, language)
        assert names.index(f"combo.{thing}.reorder") < names.index(f"combo.{thing}.update"), (asked, names[:4])
    assert ranked(tools, "reorder the courses of the menu", "en")[0] == "combo.group.reorder"


def test_a_que_inside_a_sentence_asks_nothing():
    """«Marta dice que sí»: a conjunction, not «¿qué…?». The read and the write of the same thing tie, by name."""
    tools = [tool("a.consent.set", "Saves the answer.", asks={}), tool("b.consent.list", "Lists the answers.", "query")]
    assert ranked(tools, "Marta dice que sí")[0] == "a.consent.set"
    assert ranked(tools, "que Marta pueda decir que no")[0] == "a.consent.set"
    assert ranked(tools, "¿Qué dijo Marta?")[0] == "b.consent.list"
    assert ranked(tools, "¿que dijo Marta?")[0] == "b.consent.list"


def test_a_reason_after_a_command_is_no_question():
    """«Anula el ticket 12, que me equivoqué de mesa»: the «que» after the comma says why; the void is asked."""
    tools = [tool("a.ticket.list", "Lists the tickets.", "query"), tool("b.ticket.void", "Voids a ticket.")]
    assert ranked(tools, "anula el ticket 12, que me equivoqué de mesa")[0] == "b.ticket.void"


@pytest.mark.parametrize(
    ("said", "language", "action"),
    [
        ("sienta a dos personas en la mesa 3", "es", "open"),
        ("siéntalos en la mesa 3", "es", "open"),
        ("hay que sentar a cuatro en la terraza", "es", "open"),
        ("seat two people at table 3", "en", "open"),
        ("traslada la cuenta de la mesa 1 a la 2", "es", "transfer"),
        ("trasládalos a la mesa 2", "es", "transfer"),
        ("hay que trasladar la mesa 1 a la terraza", "es", "transfer"),
        ("transfiere la cuenta de la mesa 1 a la 2", "es", "transfer"),
        ("hay que transferir la cuenta de la mesa 1 a la 2", "es", "transfer"),
        ("transfer the check of table 1 to table 2", "en", "transfer"),
    ],
)
def test_the_words_of_a_dining_room_ask_for_their_action(said, language, action):
    """Seating a party opens its check and a check taken to another table is transferred (ERPlora/live#48): «sienta»,
    «traslada» and «transfiere» are what a waiter says, with their pronouns too."""
    assert action in assistant.asked([said]).verbs


@pytest.mark.parametrize(
    ("said", "actions"),
    [
        ("vuelve a sentar la cuenta aparcada en la mesa 9", {"open", "restore"}),
        ("siéntame la cuenta aparcada en la 5", {"open", "restore"}),
        ("seat the parked check at table 9", {"open", "restore"}),
        ("restaura la cuenta aparcada", {"restore"}),
        ("hay que restaurar la cuenta aparcada", {"restore"}),
        ("restore the parked check", {"restore"}),
    ],
)
def test_seating_a_parked_check_restores_it(said, actions):
    """Seating is opening a table or putting a parked check back at one: the thing named says which."""
    assert assistant.asked([said]).verbs == actions


def test_the_forms_of_seating_are_one_word():
    """«Sienta» and «sentar» cut to two stems (its «ie»): they, and «seat», still name the same, as asks say it."""
    names = lambda said: assistant._concept(assistant._plain(said))  # noqa: E731
    assert names("sienta") == names("sentar") == names("seat")
    assert names("siéntalos") == names("sienta")


class SeatIn(Schema):
    table: str | None = None
    zone: str | None = None
    guests_count: int | None = None


class TransferIn(Schema):
    table: str | None = None
    to_table: str | None = None


class GuestsIn(Schema):
    table: str | None = None
    guests_count: int


class RestoreIn(Schema):
    id: str
    table: str | None = None


#: What a waiter does to a table's check, against the till's checks that open, are retitled and take lines.
DINING_ROOM = [
    tool("sale.order.add", "Add lines to an open check.", asks={"es": ("apunta dos cafés en la cuenta de Ana",)}),
    tool("sale.order.open", "Open a check (an open ticket), empty or with lines."),
    tool("sale.order.set_label", "Retitle an open check."),
    tool("sale.order.set_note", "Write a note on an open check."),
    tool("table.session.open", "Seat a party at a free or reserved table: its check opens in Sales titled with the "
         "table.", input=SeatIn,
         asks={"en": ("a party of two just sat down at table 7",), "es": ("han llegado dos para la mesa 7",)}),
    tool("table.session.park", "Park a table's open check: the table frees and the check waits, parked."),
    tool("table.session.restore", "Seat a parked check at a free table again, with its guests.", input=RestoreIn,
         asks={"en": ("bring the check we parked back to table 2",), "es": ("la cuenta aparcada vuelve a la mesa 2",)}),
    tool("table.session.set_guests", "Correct how many guests sit at a table's open check.", input=GuestsIn),
    tool("table.session.transfer", "Move a table's check to a free or reserved table: same check of Sales.",
         input=TransferIn),
    *NOISE,
]


@pytest.mark.parametrize(
    ("asked", "language", "first"),
    [
        ("sienta a dos personas en la mesa 3", "es", "table.session.open"),
        ("traslada la segunda cuenta de la mesa 1 a la mesa 2", "es", "table.session.transfer"),
        ("transfer the second check of table 1 to table 2", "en", "table.session.transfer"),
        ("en la mesa 1 corrige los comensales a tres", "es", "table.session.set_guests"),
        ("en la mesa 1 corrige los comensales a tres, ha llegado uno más", "es", "table.session.set_guests"),
    ],
)
def test_what_a_waiter_does_to_a_table_comes_before_the_tills_checks(asked, language, first):
    """«Sienta», «traslada» and «comensales» reach the table's operation as «guests» does; Sales' writes of a check
    (named by «cuenta») came first, as no action and no thing of the table was asked (live#48). Seating people is
    opening the table, not restoring a parked check."""
    names = ranked(DINING_ROOM, asked, language, synonyms=CHECK)
    assert names[0] == first, names[:4]


@pytest.mark.parametrize(
    ("asked", "language"),
    [("vuelve a sentar la cuenta aparcada en la mesa 9", "es"), ("seat the parked check at table 9", "en")],
)
def test_a_parked_check_seated_again_is_restored(asked, language):
    """Its check is Sales' (a «cuenta» is ``sale.order``), yet it is parked at a table: seating it is the table's
    restore, never opening another check."""
    names = ranked(DINING_ROOM, asked, language, synonyms=CHECK)
    assert names[0] == "table.session.restore", names[:4]
