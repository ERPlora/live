"""The few tools a turn offers of a catalogue of hundreds (``live.assistant.relevant``): what a person asks, in their
everyday words in Spanish or English, reaches the operation that does it.

The QA battery of the assistant with the real model (2026-10-31; ERPlora/live issue of the selection) found three
questions of an owner that never reached their tool: «Da de alta al empleado…» (``staff.member.create``), «¿Qué
vendí hoy?» (a read of ``sale``) and «Activa la app de clientes» (``base.app.enable``). The catalogue below is a
slice of the Hub's, with its real descriptions, drowned in tools that share the verb and nothing else, as the
Hub's 700 do.
"""

import time
import unicodedata
from collections import Counter

import pytest
from ninja import Schema

from live import assistant
from live.operations import AI, Operation
from tests.test_assistant import Done, NoIn


class ProductIn(Schema):
    name: str | None = None
    price: int | None = None


class ReservationIn(Schema):
    guest_name: str
    party_size: int
    table: str | None = None


def tool(name: str, description: str, kind: str = "command", input: type[Schema] = NoIn, asks=None) -> Operation:
    return Operation(
        name=name,
        kind=kind,
        permission=f"{name.split('.')[0]}.manage",
        input=input,
        output=Done,
        expose_api=False,
        ai=AI(description=description, asks=asks or {}),
        fn=lambda ctx, data: {"done": True},
        database=False,
    )


HUB_SLICE = [
    tool("base.app.enable", "Turns on one of this business's apps (by its id in base.app.list), with the apps it "
         "needs, which come along: it shows in the menu and can be used, with the data it had."),
    tool("base.app.disable", "Turns off one of this business's apps (by its id in base.app.list): it leaves "
         "everyone's menu and its screens."),
    tool("base.person.list", "Lists the people of this business: name, role, how each one gets in.", "query"),
    tool("customer.customer.create", "Creates a new customer; only the name is required. The phone is saved in "
         "international format."),
    tool("customer.customer.delete", "Deletes a customer's card: it leaves every list, the till and the phone "
         "lookup, but keeps its data, purchases and orders."),
    tool("customer.customer.list", "Lists the business's customers, 50 per page, with a search over name, email, "
         "phone, tax id and company.", "query"),
    tool("inventory.product.create", "Create a product of the catalog with its tax category, its categories and, "
         "if given, its initial stock."),
    tool("inventory.product.update", "Change a product, named by its id, SKU or name: its data, active or not, its "
         "stock control and its categories.", input=ProductIn),
    tool("pricing.price_list.list", "List the price lists (the active ones by default): code, name, currency.",
         "query"),
    tool("pricing.rule.list", "List the automatic discount rules (the active ones by default).", "query"),
    tool("reservation.reservation.create", "Takes a reservation («a table for 4 tomorrow at 21:00 for Ana»): the "
         "guest, the day and time, the party size and, if said, the table.", input=ReservationIn),
    tool("reservation.reservation.list", "Lists reservations of some days, or of a guest.", "query"),
    tool("sale.sale.complete", "Charge a sale: an open check (all its lines, or some for a partial charge) or loose "
         "lines, with its payments."),
    tool("sale.order.open", "Open a check (an open ticket), empty or with lines."),
    tool("sale.order.void", "Void (delete) an open check before it is charged: it is kept as voided."),
    tool("sale.sale.list", "List the sales, newest first: search by number or customer; filter by status.", "query"),
    tool("sale.sale.today", "What was sold today (business day) in cents, refunds taken off, and how many tickets.",
         "query"),
    tool("staff.member.bulk_create", "Adds several staff members at once (up to 100); a row with a problem is "
         "skipped with its reason and the rest go in."),
    tool("staff.member.create", "Adds a staff member (a person who works in the business)."),
    tool("staff.member.list", "Lists the staff members (the directory) with their status and role; never their pay.",
         "query"),
    tool("staff.shift.list", "Lists the shifts of the schedule, by day.", "query"),
    tool("table.table.create", "Creates a table of the floor plan with its name and seats."),
    tool("table.table.list", "Lists the tables of the floor plan with their seats.", "query"),
]
#: What drowned them: tools of other apps that share a verb, or a word of the business, and nothing else; their names
#: come first in alphabetical order, as ``appointment``'s do in the Hub.
NOISE = [
    tool(f"appointment.thing{i:02}.{action}", f"{action.capitalize()}s an appointment thing of the business.", kind)
    for i in range(30)
    for action, kind in (("create", "command"), ("list", "query"), ("update", "command"))
]
CATALOGUE = {op.name: op for op in [*HUB_SLICE, *NOISE]}


def offered(*asked: str, language: str = "es") -> list[str]:
    return [op.name for op in assistant.relevant(CATALOGUE, list(asked), language)]


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
    monkeypatch.setattr(assistant, "asks_of", lambda op: read.update([op.name]) or real(op))
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


def ranked(tools, asked: str, language: str = "es", **kwargs) -> list[str]:
    return [op.name for op in assistant.relevant({op.name: op for op in tools}, [asked], language, **kwargs)]


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


MENU_ACTIONS = {
    "add": "command", "check": "query", "count": "query", "create": "command", "delete": "command",
    "erase": "command", "export": "query", "get": "query", "import": "command", "list": "query",
    "open": "command", "remove": "command", "rename": "command", "set": "command", "start": "command",
    "stats": "query", "update": "command",
}
#: A write that does nothing asked comes first by name: what the verb asks has to earn its place.
MENU = [tool("menu.menu.aaa", "Does it to a menu."),
        *(tool(f"menu.menu.{action}", "Does it to a menu.", kind) for action, kind in MENU_ACTIONS.items())]


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
#: The Hub's own words (``base.assistant.SYNONYMS``): a «cuenta» is a table's check, ``sale.order``.
CHECK = (("cuenta", "check", "tab", "order"),)


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
    ],
)
def test_what_is_noted_brings_the_write_that_books_it_and_the_one_that_changes_it(asked):
    """«Anota una cita para Ana» books one and «anota en la cita de Ana…» writes on hers: the words do not say which,
    so both writes of the thing named come before its reads and every other write — the model chooses. Read as
    changing only, «anota una reserva para 4…» left the booking at the end of what a turn offers (live#64)."""
    names = ranked(NOTED_OR_TAKEN_AWAY, asked, synonyms=CHECK)
    assert set(names[:2]) == {"appointment.appointment.create", "appointment.appointment.update"}, names[:4]


#: What «desactiva» and «activa» ask for: switching a thing off or on, as an app's switch does, or deactivating and
#: activating it, as a member, a price list or a rule are; the thing named says which.
SWITCHING_OFF = {"disable", "deactivate"}
SWITCHING_ON = {"enable", "activate"}
#: What «da de baja» asks for: a member leaves the business, or a customer leaves a mailing; the thing named says which.
DEREGISTERING = {"terminate", "withdraw"}


@pytest.mark.parametrize(
    ("said", "language", "actions"),
    [
        ("aprueba las vacaciones de Lucía", "es", {"approve"}),
        ("hay que aprobar la ausencia de Ana", "es", {"approve"}),
        ("apruebo la ausencia de Ana del lunes", "es", {"approve"}),
        ("apruébasela a Ana", "es", {"approve"}),
        ("approve Ana's time off", "en", {"approve"}),
        ("rechaza la ausencia de Ana", "es", {"reject"}),
        ("hay que rechazar la ausencia de Ana", "es", {"reject"}),
        ("rechazo la ausencia de Ana del lunes", "es", {"reject"}),
        ("recházala a Ana", "es", {"reject"}),
        ("reject Ana's time off", "en", {"reject"}),
        ("solicita el lunes libre para Ana", "es", {"request"}),
        ("quiero solicitar el lunes libre", "es", {"request"}),
        ("solicito el lunes libre", "es", {"request"}),
        ("pido yo un día libre el 25", "es", {"request"}),
        ("solicítalo para el lunes", "es", {"request"}),
        ("request Monday off for Ana", "en", {"request"}),
        ("confirma la reserva de Ana", "es", {"confirm"}),
        ("hay que confirmar la cita de Ana", "es", {"confirm"}),
        ("confirmo la reserva de Ana", "es", {"confirm"}),
        ("confírmala para mañana", "es", {"confirm"}),
        ("confirm Ana's booking", "en", {"confirm"}),
        ("desactiva a Pablo", "es", SWITCHING_OFF),
        ("hay que desactivar la tarifa de verano", "es", SWITCHING_OFF),
        ("desactivo la regla de descuento", "es", SWITCHING_OFF),
        ("desactívala hasta el verano", "es", SWITCHING_OFF),
        ("deshabilita el método Bizum", "es", SWITCHING_OFF),
        ("hay que deshabilitar el método Bizum", "es", SWITCHING_OFF),
        ("deactivate the summer discount rule", "en", SWITCHING_OFF),
        ("activa la tarifa de verano", "es", SWITCHING_ON),
        ("vuelve a activar la regla de descuento", "es", SWITCHING_ON),
        ("actívala otra vez", "es", SWITCHING_ON),
        ("reactiva la regla de descuento", "es", SWITCHING_ON),
        ("hay que reactivar la regla de descuento", "es", SWITCHING_ON),
        ("vuelve a habilitar el método Bizum", "es", SWITCHING_ON),
        ("habilita otra vez el método Bizum", "es", SWITCHING_ON),
        ("activate the summer discount rule", "en", SWITCHING_ON),
        ("reactivate the summer discount rule", "en", SWITCHING_ON),
        ("da de baja a Pablo", "es", DEREGISTERING),
        ("hay que dar de baja a Pablo", "es", DEREGISTERING),
        ("doy de baja a Pablo hoy", "es", DEREGISTERING),
        # With each pronoun «dar» carries: me, le, lo, la, nos, les, los, las.
        ("dame de baja de la publicidad", "es", DEREGISTERING),
        ("dale de baja hoy", "es", DEREGISTERING),
        ("dalo de baja hoy", "es", DEREGISTERING),
        ("hay que darla de baja hoy", "es", DEREGISTERING),
        ("danos de baja de los avisos", "es", DEREGISTERING),
        ("dales de baja hoy", "es", DEREGISTERING),
        ("hay que darlos de baja hoy", "es", DEREGISTERING),
        ("darlas de baja hoy", "es", DEREGISTERING),
        ("terminate Pablo from Friday", "en", {"terminate"}),
    ],
)
def test_approving_rejecting_requesting_confirming_and_terminating_ask_for_their_action(said, language, actions):
    """«Aprueba», «rechaza», «solicita» (and «pido»), «confirma» and «da de baja» (terminating a member or withdrawing
    from a mailing) ask for their action; «desactiva» and «activa» (and «reactiva», «habilita») switch a thing off or on
    or deactivate and activate it, which the thing named says — ERPlora/live#50. In the infinitive, as a command, in
    the first person and with their pronouns; in English, as their actions are called. Before, none was a verb but
    «desactiva» and «activa», only as a switch."""
    assert assistant.asked([said]).verbs == actions


@pytest.mark.parametrize("said", ["los clientes activos", "¿qué tarifas están activas?", "the active price lists"])
def test_being_active_is_no_verb(said):
    """«Activo» is the first person of «activar» and, far more often, what a thing is («los clientes activos»): it asks
    to switch nothing on (ERPlora/live#50)."""
    assert assistant.asked([said]).verbs.isdisjoint(SWITCHING_ON)


def test_a_leave_given_still_names_the_leave():
    """«Da de baja» asks to terminate or withdraw, and its «baja» still names the leave a member or a stock takes, as
    «cambia el nombre» names a name: «da de baja 2 cafés» is still a write-off (ERPlora/live#50)."""
    assert any("baja" in concept for concept in assistant.asked(["da de baja 2 cafés que se han roto"]).concepts)


@pytest.mark.parametrize(
    "said",
    [
        "la mesa 4 pide la cuenta",
        "cancela la cuenta de la mesa 5, que se fueron sin pedir",
        "¿qué suele pedir Ana?",
        "la mesa 4 quiere pedir la cuenta",
    ],
)
def test_what_a_customer_orders_is_no_request(said):
    """«Pide» and «pedir» are, at a table, what a customer orders («pide la cuenta», «se fueron sin pedir»): only
    «solicita», «solicitar», «solicito», «pido» and «request» ask for a request (ERPlora/live#50)."""
    assert "request" not in assistant.asked([said]).verbs


@pytest.mark.parametrize(
    ("said", "named"),
    [
        ("knock 60% off the wine, I'll approve it", "appro"),
        ("I will approve it tomorrow", "appro"),
        ("we will open in the morning after all", "open"),
    ],
)
def test_what_someone_will_do_is_not_asked(said, named):
    """«I'll approve it» says what the speaker will do, not what the assistant is asked: a verb after «'ll» or «will»
    asks for nothing and names what it names, as any other word (ERPlora/live#50: read as asked, «knock 60% off the
    wine, I'll approve it» lost the over-the-limit discount to every time off)."""
    heard = assistant.asked([said])
    assert heard.verbs == frozenset(), heard.verbs
    assert any(named in concept for concept in heard.concepts), heard.concepts


@pytest.mark.parametrize(
    ("said", "verbs"),
    [
        ("approve it", {"approve"}),
        ("approve it if you will", {"approve"}),
        ("will you approve Ana's time off?", {"approve"}),
        ("the lights will turn on at nine", set()),
    ],
)
def test_a_command_or_a_request_with_will_still_asks(said, verbs):
    """What «will» leaves out is the verb right after it, one said in words too («will turn on»): a command asks, and
    «will you…?» is a request."""
    assert assistant.asked([said]).verbs == verbs


def test_a_name_someone_will_put_is_not_put_by_the_verb():
    """«I'll change on the price list its name» renames nothing either: what someone will do puts no name."""
    assert "rename" not in assistant.asked(["I'll change on this list its name"]).verbs
    assert "rename" in assistant.asked(["change on this list its name"]).verbs


#: Time off, a member's deactivation and termination, a booking's confirmation, a price list switched off and on and an
#: app's switch, beside the reads and the other writes of the same things.
APPROVED_OR_SWITCHED = [
    tool("appointment.appointment.cancel", "Cancel an appointment."),
    tool("appointment.appointment.confirm", "Confirm a pending appointment."),
    tool("appointment.appointment.list", "List the appointments of some days.", "query"),
    tool("base.app.disable", "Turns off one of this business's apps: it leaves everyone's menu and its screens."),
    tool("base.app.enable", "Turns on one of this business's apps, with the apps it needs."),
    tool("customer.consent.grant", "Record that a customer gives their consent to marketing by a channel."),
    tool("customer.consent.list", "List a customer's consents, given or withdrawn.", "query"),
    tool("customer.consent.withdraw", "Record that a customer withdraws their consent to marketing by a channel."),
    tool("pricing.price_list.activate", "Bring a price list back into use for new sales."),
    tool("pricing.price_list.deactivate", "Stop using a price list for new sales; its prices stay."),
    tool("pricing.price_list.list", "List the price lists.", "query"),
    tool("pricing.price_list.update", "Change a price list: its name, its dates."),
    tool("reservation.reservation.cancel", "Cancel a reservation."),
    tool("reservation.reservation.confirm", "Confirm a pending reservation."),
    tool("reservation.reservation.list", "List the reservations of a day.", "query"),
    tool("reservation.settings.update", "Change how reservations work: their length, their reminders."),
    tool("staff.member.deactivate", "Deactivate a member of the staff: they no longer sign in; their card stays."),
    tool("staff.member.list", "List the members of the staff.", "query"),
    tool("staff.member.terminate", "Terminate a member of the staff from a date: their card is closed."),
    tool("staff.member.update", "Change a member of the staff."),
    tool("staff.time_off.approve", "Approve a pending time off of a member of the staff."),
    tool("staff.time_off.list", "List the time off of the staff.", "query"),
    tool("staff.time_off.reject", "Reject a pending time off of a member of the staff."),
    tool("staff.time_off.request", "Request time off for a member of the staff."),
    *NOISE,
]
#: A project's words for time off and for a customer's consent to marketing, as the Hub's own synonyms say them.
HUB_WORDS = (("ausencia", "ausencias", "vacaciones", "time"), ("publicidad", "promociones", "consent"))


@pytest.mark.parametrize(
    ("asked", "language", "first"),
    [
        ("aprueba las vacaciones de Lucía", "es", "staff.time_off.approve"),
        ("rechaza la ausencia de Ana del lunes", "es", "staff.time_off.reject"),
        ("solicito unas vacaciones para el lunes", "es", "staff.time_off.request"),
        ("approve Ana's time off", "en", "staff.time_off.approve"),
        ("confirma la reserva de Ana", "es", "reservation.reservation.confirm"),
        ("confirma la cita de Ana de mañana", "es", "appointment.appointment.confirm"),
        ("desactiva al empleado Pablo", "es", "staff.member.deactivate"),
        ("da de baja al empleado Pablo", "es", "staff.member.terminate"),
        ("Carmen se da de baja de la publicidad", "es", "customer.consent.withdraw"),
        ("desactiva la tarifa de verano", "es", "pricing.price_list.deactivate"),
        ("vuelve a activar la tarifa de verano", "es", "pricing.price_list.activate"),
        ("reactivate the summer price list", "en", "pricing.price_list.activate"),
        ("desactiva la app de reservas", "es", "base.app.disable"),
        ("activa la app de reservas", "es", "base.app.enable"),
    ],
)
def test_what_is_approved_confirmed_or_switched_comes_first(asked, language, first):
    """Time off approved, rejected or asked for, a booking confirmed, a member deactivated or terminated and a price
    list switched off or on: the action of the thing named, before its other writes and its reads; an app named is
    still switched by its own switch (ERPlora/live#50). Before, the action was no verb and these came behind."""
    names = ranked(APPROVED_OR_SWITCHED, asked, language, synonyms=HUB_WORDS)
    assert names[0] == first, names[:4]


#: A price list and a payment method named only by their names, beside an app named by its own name («las ventas»).
SWITCHED_BY_NAME = [*APPROVED_OR_SWITCHED, tool("sale.sale.list", "Lists the sales of a day.", "query")]


@pytest.mark.parametrize(
    ("asked", "language", "first"),
    [
        ("vuelve a activar Mayorista para las próximas ventas", "es", "pricing.price_list.activate"),
        ("activate Wholesale again for the new sales", "en", "pricing.price_list.activate"),
        ("activa las ventas", "es", "base.app.enable"),
        ("desactiva las ventas", "es", "base.app.disable"),
        ("turn off the sales", "en", "base.app.disable"),
        # With words between the verb and the app, or the app named in the sentence before: still the app's switch.
        ("activa otra vez las ventas", "es", "base.app.enable"),
        ("activa también las ventas", "es", "base.app.enable"),
        ("quiero activar ya mismo las ventas", "es", "base.app.enable"),
        ("desactiva de momento las ventas", "es", "base.app.disable"),
        ("ya no usamos las ventas, desactívalas", "es", "base.app.disable"),
        ("deactivate the sales for now", "en", "base.app.disable"),
    ],
)
def test_an_app_is_switched_when_it_is_what_the_command_switches(asked, language, first):
    """An app named is switched when it is what the command switches («activa las ventas», «activa otra vez las
    ventas»); named for what something is, after «para» or «for» («vuelve a activar Mayorista para las próximas
    ventas»: a price list named by its name), it is not the thing switched on, and the activation of the thing comes
    first (ERPlora/live#50; before, turning an app on did)."""
    names = ranked(SWITCHED_BY_NAME, asked, language, synonyms=HUB_WORDS)
    assert names[0] == first, names[:4]


@pytest.mark.parametrize(
    ("asked", "language", "first"),
    [
        ("desactiva las ventas", "es", "base.app.disable"),
        ("hay que desactivar las ventas", "es", "base.app.disable"),
        ("deactivate the sales", "en", "base.app.disable"),
        ("desactiva al empleado Pablo", "es", "staff.member.deactivate"),
    ],
)
def test_an_app_is_switched_off_also_when_a_project_makes_the_verb_a_thing(asked, language, first):
    """A project may say «desactiva» names a deactivation (its ``synonyms``, as the Hub's do): the verb is then the
    thing the command acts on, and an app named by its name is still the one switched off (ERPlora/live#50)."""
    synonyms = (*HUB_WORDS, ("desactiva", "desactivar", "deactivate"))
    names = ranked(SWITCHED_BY_NAME, asked, language, synonyms=synonyms)
    assert names[0] == first, names[:4]


@pytest.mark.parametrize(
    ("said", "direct"),
    [
        ("vuelve a activar Mayorista para las próximas ventas", False),
        ("activate Wholesale again for the new sales", False),
        ("activa otra vez las ventas", True),
        ("activa las ventas para el turno de noche", True),
    ],
)
def test_a_thing_named_after_para_is_named_for_what_another_is(said, direct):
    """``Asked.direct`` holds what is named outside what something is for: «ventas» after «para» or «for» is not."""
    heard = assistant.asked([said])
    assert any("venta" in concept or "sale" in concept for concept in heard.concepts)  # positive control: it is named
    assert any("venta" in concept or "sale" in concept for concept in heard.direct) is direct


def names(concepts: frozenset[frozenset[str]], word: str) -> bool:
    return any(not concept.isdisjoint(assistant.stems(word)) for concept in concepts)


@pytest.mark.parametrize(
    ("said", "word", "direct"),
    [
        # What says of what the thing named is: after «de», «del» or «of» and their articles, behind a word that names.
        ("vuelve a activar la regla de los productos", "productos", False),
        ("desactiva la regla española de los productos", "productos", False),
        ("desactiva la tarifa del producto", "producto", False),
        ("vuelve a activar la regla de IVA de los productos", "productos", False),
        ("reactivate the rule of the products", "products", False),
        # An app named as one is the app («la app de clientes»), in either language; a «de» behind the verb, or after
        # the app named, says nothing of another thing.
        ("activa la app de clientes", "clientes", True),
        ("activa la aplicación de clientes", "clientes", True),
        ("desactiva el módulo de reservas", "reservas", True),
        ("turn on the module of bookings", "bookings", True),
        ("desactiva de momento las ventas", "ventas", True),
        ("activa las ventas del turno de noche", "ventas", True),
    ],
)
def test_what_says_of_what_a_thing_is_is_not_named_directly(said, word, direct):
    """``Asked.direct`` holds no thing named only to say of what another is: «los productos» in «vuelve a activar la
    regla de los productos» is what the rule is of, not what the command switches (ERPlora/live#73)."""
    heard = assistant.asked([said])
    assert names(heard.concepts, word)  # positive control: it is named
    assert names(heard.direct, word) is direct


class ProductImageIn(Schema):
    product: str
    image: str | None = None


#: A tax rule named beside the app its rule is of: the Hub's Taxes and Products, whose «regla» is no synonym of «rule»
#: (the Hub's asks say it), beside the switches of an app and a write that takes a product.
RULE_OF_AN_APP = [
    *APPROVED_OR_SWITCHED,
    tool("inventory.product.set_image", "Put a product's image.", input=ProductImageIn),
    tool("tax.rule.activate", "Bring a deactivated tax rule back so it applies to new operations again.",
         asks={"es": ("reactiva la regla de IVA de los libros",
                      "vuelve a poner en marcha en España la regla de impuestos de la comida",
                      "recupera la regla fiscal de Portugal que está desactivada")}),
    tool("tax.rule.deactivate", "Deactivate a tax rule so it no longer applies to new operations.",
         asks={"es": ("desactiva la regla de IVA de los libros", "deja de aplicar por ahora la regla fiscal del 10 %",
                      "desactiva de momento la regla de impuestos de España para la comida")}),
    tool("tax.rule.list", "List the tax rules.", "query"),
]
PRODUCTS_APP = {"inventory": "inventory products productos", "tax": "tax taxes impuestos", "sale": "sale sales ventas",
                "reservation": "reservation reservations reservas"}


def products_app(label: str, language: str) -> frozenset[str]:
    return frozenset(assistant.stems(PRODUCTS_APP.get(label, label)))


@pytest.mark.parametrize(
    ("asked", "first", "switch"),
    [
        ("vuelve a activar la regla de los productos", "tax.rule.activate", "base.app.enable"),
        ("desactiva la regla española de los productos sin perder su porcentaje", "tax.rule.deactivate",
         "base.app.disable"),
    ],
)
def test_what_a_thing_switched_is_of_is_neither_the_app_switched_nor_the_thing_changed(asked, first, switch):
    """«Vuelve a activar la regla de los productos» reactivates the rule: the app of the products is not the one turned
    on, nor a write that takes a product what the command changes (ERPlora/live#73; before, turning the app on and
    putting a product's image came first)."""
    offered_ = ranked(RULE_OF_AN_APP, asked, app_words=products_app)
    assert offered_[0] == first, offered_[:4]
    assert switch in offered_ and "inventory.product.set_image" in offered_  # positive control: both are offered


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
        ("las etiquetas", "tag"), ("el portátil", "device"), ("este ordenador", "device"), ("la tablet", "device"),
        ("los comensales", "guest"), ("un comensal", "guest"),
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
    ],
)
def test_the_forms_of_a_word_kept_apart_still_join(words, stem):
    assert assistant.stems(words) == {stem}


ATTENDANCE_AND_CUSTOMER = [
    tool("attendance.record.clock_in", "Clocks a member in («ficha la entrada de Ana»): opens the working day."),
    tool("customer.customer.get", "A customer's card: data, notes and purchases.", "query"),
]


def test_the_customers_card_is_not_clocking_in():
    assert ranked(ATTENDANCE_AND_CUSTOMER, "abre la ficha de Marta")[0] == "customer.customer.get"
    assert ranked(ATTENDANCE_AND_CUSTOMER, "ficha la entrada de Ana")[0] == "attendance.record.clock_in"


class NameIn(Schema):
    name: str


#: A device renamed among the writes that take a ``name`` and change it (``update``/``set``), as the Hub's forty.
DEVICES = [
    tool("base.app.enable", "Turns on one of this business's apps, with the apps it needs.",
         asks={"es": ("vuelve a dejar disponible la app de tareas",)}),
    tool("base.device.list", "Lists the devices that use this business: tablets, laptops, phones.", "query"),
    tool("base.device.prune", "Removes the devices that have not been used for a month."),
    tool("base.device.rename", "Names a device of this business («Barra», «Cocina»).", input=NameIn),
    *(tool(f"appointment.thing{i:02}.{action}", f"{action.capitalize()}s an appointment thing.", input=NameIn)
      for i in range(25) for action in ("set", "update")),
]


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


class SortedIn(Schema):
    name: str | None = None
    sort_order: int | None = None


def test_what_is_not_to_be_changed_does_not_drown_the_delete_asked():
    """The QA probe of ERPlora/live#60: «pedidos» names an order, which every update that takes a ``sort_order``
    takes; with «sin cambiar» asked as a change, each of them came before the delete asked."""
    updates = [tool(f"{app}.{entity}.update", f"Change a {entity}: its name and its place in the list.", input=SortedIn)
               for app, entity in (("inventory", "category"), ("modifier", "option"), ("menu", "section"),
                                   ("table", "zone"), ("service", "category"))]
    tools = [
        tool("modifier.group.delete", "Delete a modifier group with its options and its assignments.",
             asks={"es": ("borra el grupo de suplementos Salsas",)}),
        *updates,
        *HUB_SLICE,
        *NOISE,
    ]
    names = ranked(tools, "elimina Endulzante QA con su opción y sus asignaciones, sin cambiar los pedidos antiguos")
    assert all(names.index("modifier.group.delete") < names.index(update.name) for update in updates), names[:8]


def test_being_available_is_no_device():
    """«Quiero volver a tener Reservas disponible» names no device: the app's own «disponible» brings it, before every
    device (ERPlora/live#47: 34th in the Hub, behind ``base.device.*``)."""
    names = ranked(DEVICES, "quiero volver a tener Reservas disponible")
    assert names[0] == "base.app.enable", names[:4]


def test_receiving_goods_is_not_a_receipt():
    tools = [tool("kitchen.ticket.print", "Prints the receipt of a ticket."),
             tool("purchase.order.receive", "Receives the goods of a purchase order into the stock.")]
    assert ranked(tools, "recibe la mercancía del proveedor")[0] == "purchase.order.receive"
    assert ranked(tools, "imprime el recibo")[0] == "kitchen.ticket.print"


#: The kitchen's two writes of a dish done, with the Hub's descriptions, amid the slice's lists.
KITCHEN_AMID_LISTS = [
    tool("kitchen.item.bump", "Mark dishes ready: some of a ticket, or all of it on one station («the burgers of "
         "table 4 are ready»). The first one starts the ticket; with nothing left to do it goes to the pass.",
         asks={"es": ("el plato de la mesa 2 ya está listo", "marca como hechas las patatas de la plancha")}),
    tool("kitchen.item.recall", "Bring back dishes marked ready by mistake; a ticket at the pass goes back to "
         "preparing.", asks={"es": ("me he equivocado con el plato de la 4: déjalo otra vez pendiente",)}),
    *HUB_SLICE,
    *NOISE,
]


@pytest.mark.parametrize(
    ("asked", "kitchen"),
    [
        ("marca como listos los dos cafés de la mesa 4", "kitchen.item.bump"),
        ("el café de la mesa 4 ya está listo", "kitchen.item.bump"),
        ("devuelve a pendientes los cafés que acabo de marcar listos", "kitchen.item.recall"),
    ],
)
def test_dishes_said_ready_are_the_kitchens_not_a_list(asked, kitchen):
    """«Listo» and «listos» say a dish is done: they reach the kitchen's writes before any tool that lists (each
    ``*.list`` was a thing named, and the kitchen's tools fell out of the ones offered, live#54)."""
    names = ranked(KITCHEN_AMID_LISTS, asked)
    assert kitchen in names, names[:4]
    assert not any(name.endswith(".list") for name in names[: names.index(kitchen)]), names[:4]


def test_a_list_is_still_said_lista():
    """«Lista» is the command to list and a list («las listas de precios»): «listo», kept apart, takes none of it."""
    assert assistant.stems("lista listas listar") == {"list"}


def test_what_a_word_names_may_be_the_projects_own():
    """«Cuenta» is the check of a table in the Hub and the person's account in the SaaS: each project says it."""
    tools = [tool("accounts.profile.get", "The person's account: name, email and language.", "query"),
             tool("sale.order.get", "An open check of a table with its lines.", "query"), *NOISE]
    hub = (("cuenta", "check", "order"),)
    saas = (("cuenta", "account"),)
    assert ranked(tools, "enséñame la cuenta", synonyms=hub)[0] == "sale.order.get"
    assert ranked(tools, "enséñame la cuenta", synonyms=saas)[0] == "accounts.profile.get"
    assert ranked(tools, "enséñame la cuenta")[:2] == ranked(tools, "enséñame la nada")[:2]


# The app words of the SaaS's panel and the Hub's apps the tests below rank with: an app's name in both languages.
APP_NAMES = {
    "accounts": "accounts account cuenta", "hubs": "hubs businesses negocios",
    "customer": "customer customers clientes",
    "sale": "sale sales ventas quick notes notas rapidas", "files": "files archivos", "invoice": "invoice facturas",
    "kitchen": "kitchen cocina pedidos orders", "base": "base", "reservation": "reservation reservations reservas",
}


def app_names(label: str, language: str) -> frozenset[str]:
    return frozenset(assistant.stems(APP_NAMES.get(label, label)))


class PreferencesIn(Schema):
    theme_mode: str | None = None
    language: str | None = None
    hub_alerts: bool | None = None


class BusinessIn(Schema):
    name: str | None = None
    country: str | None = None
    time_zone: str | None = None


SAAS_SLICE = [
    tool("accounts.preferences.get", "The account's theme, language and alerts of its businesses.", "query"),
    tool("accounts.preferences.update", "Changes the account's theme, language or alerts of its businesses.",
         input=PreferencesIn),
    tool("accounts.profile.update", "Changes the account's name and photo."),
    tool("hubs.business.create", "Creates a business of the account."),
    tool("hubs.business.delete", "Deletes a business of the account."),
    tool("hubs.business.get", "A business of the account: its name, plan and state.", "query"),
    tool("hubs.business.list", "Lists the account's businesses.", "query"),
    tool("hubs.business.notify_people", "Sends a notice to every person of a business."),
    tool("hubs.business.update", "Changes the name, country, language or time zone of a business.", input=BusinessIn),
    tool("hubs.invitation.list_mine", "Lists the invitations to businesses the account received.", "query"),
    tool("hubs.member.invite", "Invites a person to a business."),
    tool("hubs.member.list", "Lists the people of a business.", "query"),
    tool("hubs.member.remove", "Removes a person from a business."),
]


@pytest.mark.parametrize(
    ("asked", "language"),
    [("turn off the alerts from my businesses", "en"), ("desactiva los avisos de mis negocios", "es")],
)
def test_the_thing_turned_off_beats_the_app_named_beside_it(asked, language):
    """«Businesses» names the whole ``hubs`` app; what is turned off is the alerts the account's preferences take."""
    assert ranked(SAAS_SLICE, asked, language, app_words=app_names)[0] == "accounts.preferences.update"


CUSTOMER_AND_SALE = [
    *(tool(f"customer.customer.{action}", "A customer of the business.", kind)
      for action, kind in (("create", "command"), ("delete", "command"), ("get", "query"), ("list", "query"),
                           ("stats", "query"), ("update", "command"))),
    tool("customer.group.list", "Lists the customer groups.", "query"),
    tool("customer.note.add", "Adds a note to a customer's card."),
    tool("customer.note.list", "Lists the notes of a customer's card.", "query"),
    tool("customer.tag.list", "Lists the customer tags.", "query"),
    tool("sale.payment_method.list", "List the active payment methods in the order of the charge sheet, with their "
         "type (cash, card, transfer, other).", "query"),
    tool("sale.sale.complete", "Charge a sale: an open check or loose lines, with its payments."),
    tool("sale.sale.list", "List the sales, newest first.", "query"),
    tool("sale.order.get", "An open check (an order) of a table with its lines.", "query"),
    tool("sale.order.list", "Lists the open checks.", "query"),
]


@pytest.mark.parametrize(
    ("asked", "language"),
    [("what can customers pay with?", "en"), ("¿con qué pueden pagar los clientes?", "es")],
)
def test_what_is_asked_about_beats_the_app_of_who_does_it(asked, language):
    """«Customers» names the whole ``customer`` app; what is asked is how they pay: the payment methods."""
    assert ranked(CUSTOMER_AND_SALE, asked, language, app_words=app_names)[0] == "sale.payment_method.list"


def test_a_customers_notes_are_not_the_quick_notes_app():
    """The till's quick notes make «notas» a word of the whole ``sale`` app: a customer's notes are still asked."""
    names = ranked(CUSTOMER_AND_SALE, "¿qué notas tiene la ficha de Ana?", app_words=app_names)
    assert names[0] == "customer.note.list"


def test_another_apps_data_named_does_not_bring_that_app():
    """A folder called «Facturas» is a folder, not the invoices app."""
    tools = [tool("files.folder.create", "Creates a folder."), tool("files.file.list", "Lists the files.", "query"),
             *(tool(f"invoice.invoice.{action}", "An invoice.", kind)
               for action, kind in (("create", "command"), ("list", "query"), ("void", "command")))]
    assert ranked(tools, "crea la carpeta Facturas", app_words=app_names)[0] == "files.folder.create"


def test_what_a_command_acts_on_is_the_first_thing_it_names():
    """«Crea la carpeta Facturas»: the folder is created, «Facturas» is its name — though it names the invoices app and
    its invoice, and ``invoice.invoice.create`` is the very verb asked."""
    tools = [tool("base.file.create_folder", "Makes a new, empty folder in the business's files."),
             tool("base.file.list", "Lists the business's files.", "query"),
             *(tool(f"invoice.{entity}.{action}", "An invoice.", kind)
               for entity, action, kind in (("invoice", "create", "command"), ("invoice", "list", "query"),
                                            ("series", "create", "command")))]
    assert ranked(tools, "crea la carpeta Facturas", app_words=app_names)[0] == "base.file.create_folder"
    assert ranked(tools, "crea una factura en la carpeta", app_words=app_names)[0] == "invoice.invoice.create"


def test_the_thing_named_beats_the_other_tools_of_its_app():
    """«¿Qué clientes tengo?» names the ``customer`` app and its customers: the customers' list, not its groups."""
    names = ranked(CUSTOMER_AND_SALE, "¿qué clientes tengo?", app_words=app_names)
    assert names[0] == "customer.customer.list"
    assert names.index("customer.customer.get") < names.index("customer.group.list")


def test_how_many_also_asks_for_the_figures():
    names = ranked(CUSTOMER_AND_SALE, "¿cuántos clientes VIP hay?", app_words=app_names)
    assert set(names[:2]) == {"customer.customer.list", "customer.customer.stats"}


def test_what_an_action_is_for_is_not_what_it_acts_on():
    """``list_for_customer`` lists appointments, ``by_reservation`` holds tables: the customer and the reservation they
    name say for what, not what is listed or held."""
    tools = [tool("appointment.appointment.list_for_customer", "Lists a customer's appointments.", "query"),
             *(tool(f"customer.customer.{action}", "A customer of the business.", kind)
               for action, kind in (("get", "query"), ("list", "query"), ("stats", "query"))),
             tool("customer.group.list", "Lists the customer groups.", "query")]
    names = ranked(tools, "¿cuántos clientes tengo este mes?", app_words=app_names)
    assert names.index("appointment.appointment.list_for_customer") > 2, names


def test_a_write_of_a_record_named_brings_the_read_that_finds_it():
    """«Borra el cliente «Ana QA»»: the delete needs the customer's id, which its list finds, among many deletes."""
    deletes = [tool(f"app{i:02}.thing.delete", "Deletes a thing of the business.") for i in range(45)]
    tools = [*deletes, *CUSTOMER_AND_SALE]
    names = ranked(tools, "Borra el cliente «Ana QA»", app_words=app_names)
    assert names[0] == "customer.customer.delete"
    assert names.index("customer.customer.list") < 10, names[:12]


def test_booking_a_table_is_a_reservation_not_its_tables():
    """«Reserva una mesa para 4»: a reservation made, though the reservations' free tables name the table too."""
    tools = [*HUB_SLICE, tool("reservation.availability.tables", "The tables free for a reservation of a party at a "
                              "time.", "query")]
    for asked, language in (("reserva una mesa para 4 personas", "es"), ("book a table for 4", "en")):
        assert ranked(tools, asked, language, app_words=app_names)[0] == "reservation.reservation.create", asked
    assert ranked(tools, "cancela la reserva de Ana", app_words=app_names)[0] != "reservation.reservation.create"


def test_a_filter_of_a_read_is_not_what_it_reads():
    """A read that takes a customer (``customer_id``) is not the customers' read: «¿cuántos clientes…?» is not it."""

    class ForCustomerIn(Schema):
        customer_id: str | None = None

    tools = [tool("appointment.appointment.list_for_customer", "Lists a customer's appointments.", "query",
                  input=ForCustomerIn),
             tool("customer.activity.list", "Lists the activity of a customer.", "query", input=ForCustomerIn),
             tool("customer.customer.list", "Lists the customers.", "query")]
    names = ranked(tools, "¿cuántos clientes tengo este mes?", app_words=app_names)
    assert names[-1] == "appointment.appointment.list_for_customer", names


@pytest.mark.parametrize(
    ("asked", "language"),
    [("show me Carmen's card", "en"), ("give me Carmen's card", "en"), ("tell me about Carmen's card", "en"),
     ("enséñame la ficha de Carmen", "es"), ("dame la ficha de Carmen", "es"), ("dime la ficha de Carmen", "es")],
)
def test_the_words_that_ask_name_nothing(asked, language):
    """«Show me», «dame», «dime» ask; they name no thing: the tools whose phrases also say «show me…» gain nothing."""
    tools = [
        *(tool(f"base.{entity}.list", f"Lists the {entity}s of the business.", "query",
               asks={"en": (f"show me the {entity}s", f"give me the {entity}s", f"tell me the {entity}s"),
                     "es": (f"enséñame los {entity}s", f"dame los {entity}s", f"dime los {entity}s")})
          for entity in ("device", "file", "user")),
        tool("customer.customer.detail", "A customer's card: data, notes and purchases.", "query"),
    ]
    assert ranked(tools, asked, language)[0] == "customer.customer.detail"


def test_give_me_and_tell_me_ask_but_give_alone_names():
    """«Give me» and «tell me» only ask; «give table 4 10% off» says what is given."""
    concepts = lambda said: set().union(*assistant.asked([said]).concepts)  # noqa: E731
    assert "give" not in concepts("give me Carmen's card") | concepts("tell me the total")
    assert "give" in concepts("give table 4 10% off")


def test_a_command_that_names_no_record_brings_no_reads():
    """«Quiero cobrar también por transferencia»: charging names a sale but no sale to find; the new payment method is
    asked, not the reads of the sales."""
    tools = [*(tool(f"sale.sale.{action}", "A sale of the till.", "query") for action in ("get", "list", "stats",
                                                                                         "today", "last_7_days")),
             tool("sale.sale.complete", "Charge a sale with its payments."),
             tool("sale.payment_method.create", "Adds a payment method the till charges with (cash, card, transfer).",
                  asks={"es": ("añade Bizum como forma de pago",)})]
    names = ranked(tools, "quiero cobrar también por transferencia")
    assert names.index("sale.payment_method.create") < names.index("sale.sale.get"), names


def test_leaving_the_publicity_is_no_delete():
    """«Se da de baja de la publicidad» withdraws a consent: «de baja» deletes nothing."""
    tools = [tool("a.thing.delete", "Deletes a thing."),
             tool("b.consent.withdraw", "Records that a customer leaves the publicity («se da de baja»).")]
    assert ranked(tools, "Carmen se da de baja de la publicidad")[0] == "b.consent.withdraw"


def test_the_order_named_beats_the_app_whose_name_it_is():
    """«Pedido» is the kitchen's app name and a check's entity: the check named is what is asked."""
    tools = [*CUSTOMER_AND_SALE, *(tool(f"kitchen.ticket.{action}", "A kitchen ticket.", kind)
                                   for action, kind in (("bump", "command"), ("list", "query"), ("recall", "command")))]
    assert ranked(tools, "¿qué lleva el pedido de la mesa 4?", app_words=app_names)[0] == "sale.order.get"


APPS = [
    tool("base.app.enable", "Turns on one of this business's apps, with the apps it needs."),
    tool("base.app.disable", "Turns off one of this business's apps."),
    *(tool(f"customer.customer.{action}", "A customer of the business.", kind)
      for action, kind in (("create", "command"), ("list", "query"), ("update", "command"))),
]


@pytest.mark.parametrize(
    "asked", ["activa los clientes", "enciéndeme clientes", "quiero el módulo de clientes", "ponme la app de clientes",
              "instala la app de clientes"],
)
def test_an_app_turned_on_by_its_name_is_turned_on(asked):
    assert ranked(APPS, asked, app_words=app_names)[0] == "base.app.enable"


def test_a_turn_ranks_a_catalogue_of_750_tools_with_every_kind_of_question():
    """The Hub with every app on: each kind of question ranks in the same few milliseconds."""
    many = {op.name: op for op in (
        tool(f"app{i % 28}.thing{i}.{('create', 'list', 'update', 'delete', 'get')[i % 5]}",
             f"Does thing {i} of the business with its name, price and tax category.",
             "query" if i % 5 in (1, 4) else "command",
             asks={"es": (f"créame la cosa {i}", f"¿cuántas cosas {i} hay?"), "en": (f"add thing {i}",)})
        for i in range(750))}
    asked = ["cóbrale a la mesa 4", "¿cómo invito a alguien?", "do I need a customer to charge?",
             "turn off the alerts from my businesses", "get rid of the menu"]
    for one in asked:
        assistant.relevant(many, [one], "es", howto=["app0.thing0.get"], synonyms=(("cuenta", "check"),))
    timings = []
    for _ in range(3):
        start = time.perf_counter()
        for one in asked:
            assistant.relevant(many, [one], "es", howto=["app0.thing0.get"], synonyms=(("cuenta", "check"),))
        timings.append((time.perf_counter() - start) / len(asked))
    assert min(timings) < 0.100


# ── Review of live#22: what a question is, an app named by its own name ─────────────────────────────────────────


@pytest.mark.parametrize(
    ("asked", "language"),
    [
        ("hola puedes cobrar la mesa 4?", "es"),
        ("hey charge table 4?", "en"),
        ("Cobra la mesa 4 y dime cuánto es", "es"),
        ("charge table 4 and tell me how much it is", "en"),
        ("Do a charge for table 4", "en"),
    ],
)
def test_a_command_with_a_question_mark_or_a_question_after_it_still_does(asked, language):
    """A greeting or a request before the verb, a «?» at the end, a question after the command: the verb is asked."""
    assert offered(asked, language=language)[0] == "sale.sale.complete"
    assert assistant.asked([asked]).verbs >= {"complete"}


def test_a_question_whose_verb_comes_later_still_asks_to_know():
    assert "complete" not in assistant.asked(["¿hace falta poner cliente para cobrar?"]).verbs
    assert "complete" not in assistant.asked(["do I need a customer to charge?"]).verbs


@pytest.mark.parametrize(
    ("asked", "language"),
    [("dime cómo invito a alguien a mi negocio", "es"), ("tell me how to invite someone to my business", "en"),
     ("explícame cómo se cierra la caja", "es")],
)
def test_a_how_to_question_after_a_word_that_asks_is_one(asked, language):
    assert assistant.asked([asked]).howto


def test_initials_are_no_command():
    """«Iniciales» (initials) is no «inicia» with «les»: no verb asked."""
    assert assistant.asked(["las iniciales de Ana"]).verbs == frozenset()
    assert assistant.asked(["inicia la caja"]).verbs >= {"open"}


def test_a_question_written_with_decomposed_accents_is_one():
    decomposed = unicodedata.normalize("NFD", "Marta dice qué")
    assert decomposed != "Marta dice qué"
    assert assistant.asked([decomposed]).reading


@pytest.mark.parametrize(
    ("asked", "app"),
    [("¿qué hay en la cocina?", "kitchen"), ("ver la cocina", "kitchen"), ("¿cómo va la caja?", "cash_register"),
     ("ver caja", "cash_register")],
)
def test_an_app_named_by_its_own_name_brings_its_tools_before_a_mention(asked, app):
    """«Cocina» names the kitchen app, whose entities are tickets and stations; «caja» the cash register, of sessions:
    a tool of another app (first by name) that only mentions the word in its description comes after them."""
    tools = [
        tool("bar.drink.list", "Lists the drinks, each sent to the kitchen with its till price.", "query"),
        tool("bar.drink.fire", "Sends a drink to the kitchen and charges it at the till."),
        tool("kitchen.ticket.list", "Lists the open tickets.", "query"),
        tool("kitchen.station.list", "Lists the stations.", "query"),
        tool("cash_register.session.list", "Lists the sessions.", "query"),
        tool("cash_register.session.open", "Opens a session."),
    ]
    names = {"kitchen": "kitchen cocina", "cash_register": "cash register caja", "bar": "bar"}
    words = lambda label, language: frozenset(assistant.stems(names[label]))  # noqa: E731
    assert ranked(tools, asked, app_words=words)[0].startswith(f"{app}."), ranked(tools, asked, app_words=words)


def test_an_app_name_beside_a_thing_named_is_no_thing():
    """«Enséñame el registro de eventos»: the events are the thing; «registro» also names the attendance app (its
    «Registro horario»), which only breaks ties then."""
    tools = [*(tool(f"attendance.{entity}.list", "Lists them.", "query")
               for entity in ("correction", "person", "presence")),
             tool("base.event.list", "Lists the events of the business.", "query")]
    words = lambda label, language: frozenset(  # noqa: E731
        assistant.stems({"attendance": "attendance registro horario", "base": "base"}[label]))
    assert ranked(tools, "enséñame el registro de eventos", app_words=words)[0] == "base.event.list"


def test_a_command_on_an_app_named_by_its_name_is_of_that_app():
    """«Abre la caja con 100 €» opens the till's session; «abre la cocina» opens no other app's thing."""
    tools = [tool("bar.drink.open", "Opens a drink order sent to the kitchen."),
             tool("cash_register.session.open", "Opens a session with its float."),
             tool("cash_register.session.list", "Lists the sessions.", "query"),
             tool("kitchen.ticket.list", "Lists the open tickets.", "query")]
    names = {"kitchen": "kitchen cocina", "cash_register": "cash register caja", "bar": "bar"}
    words = lambda label, language: frozenset(assistant.stems(names[label]))  # noqa: E731
    assert ranked(tools, "abre la caja con 100 €", app_words=words)[0] == "cash_register.session.open"
    assert ranked(tools, "abre la cocina", app_words=words)[0] == "kitchen.ticket.list"


def test_a_command_whose_thing_has_no_such_action_still_brings_the_others():
    """«Create a 10% discount»: the discount is set on checks, never created there; the discount rules are created."""
    tools = [*(tool(f"aaa.order.{action}", "A check of the till.") for action in ("set_discount", "set_line_discount")),
             tool("pricing.rule.create", "Creates an automatic discount rule.", asks={"en": ("new happy hour rule",)}),
             *(tool(f"app{i}.thing.create", "Creates a thing.") for i in range(12))]
    assert ranked(tools, "create a 10% discount", "en")[0] == "pricing.rule.create"
