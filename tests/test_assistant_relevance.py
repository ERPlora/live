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
from pydantic import create_model

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


class MovementIn(Schema):
    type: str
    amount: int
    description: str | None = None


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


class CustomerIn(Schema):
    name: str | None = None
    phone: str | None = None


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
TILL_APPS = {
    "cash_register": "caja cash register", "printing": "impresión printing", "sale": "ventas sale tpv notas rápidas",
    "appointment": "citas appointments", "staff": "personal staff turnos", "customer": "clientes customers",
}


def till_apps(label: str, language: str) -> frozenset[str]:
    return frozenset(assistant.stems(TILL_APPS.get(label, label)))


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
        # «Del» and «al» say where with their article; «en» and «a» before a determiner too.
        ("anota del turno una salida de 15 €", "salida"),
        ("apunta en esta caja una salida de 15 €", "salida"),
        # With nothing named in a phrase of its own before another clause or command, where it is done is what the
        # command acts on («anota en la cita de Ana…»: it writes on her appointment).
        ("anota en la cita de Ana que use mascarilla", "cita"),
        ("anota en la caja y luego una salida de 15 €", "caja"),
        ("hay que anotarlo en la caja", "caja"),
        # «A» before a name is whom it is done to, no place: what follows is no thing of its own.
        ("apúntale a Ana el teléfono nuevo", "ana"),
        # Only a verb that puts something somewhere: where another verb acts, said first, is what it acts on.
        ("borra del historial la cuenta de la mesa 4", "historial"),
        ("pon en la web el horario de verano", "web"),
        ("crea en la carpeta Facturas un documento", "carpeta"),
        ("anota una salida de 15 € en el turno", "salida"),
    ],
)
def test_what_a_command_acts_on_is_named_after_where_it_is_done(said, thing):
    """Where a command is done, said before what it does it to («anota en el turno una salida de 50 €»), is no thing it
    acts on: the shift is where the money taken out is noted, as in «anota una salida de 50 € en el turno»
    (ERPlora/live#94: read as the shift, the writes and reads of the staff's shifts came before noting the movement)."""
    assert assistant.asked([said]).objects == {assistant._concept(thing)}


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
        # «Turn off» and «switch off», «turn on» and «switch on» say what «desactiva» and «activa» do (ERPlora/live#82).
        ("turn off the summer discount rule", "en", SWITCHING_OFF),
        ("switch off the summer discount rule", "en", SWITCHING_OFF),
        ("turn on the summer discount rule again", "en", SWITCHING_ON),
        ("switch on the summer discount rule", "en", SWITCHING_ON),
        # «Apaga» and «enciende» too, as «desactiva» and «activa» (ERPlora/live#79): with their infinitive and pronouns.
        ("apaga la tarifa de verano", "es", SWITCHING_OFF),
        ("hay que apagar el método Bizum", "es", SWITCHING_OFF),
        ("apágala hasta el verano", "es", SWITCHING_OFF),
        ("enciende la tarifa de verano", "es", SWITCHING_ON),
        ("hay que encender el método Bizum", "es", SWITCHING_ON),
        ("enciéndela otra vez", "es", SWITCHING_ON),
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
    or deactivate and activate it, which the thing named says — ERPlora/live#50 —, as «apaga» and «enciende» do
    (ERPlora/live#79) and «turn off» and «turn on» (ERPlora/live#82). In the infinitive, as a command, in
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
        # In English as «desactiva» and «activa» (ERPlora/live#82).
        ("turn off the summer price list", "en", "pricing.price_list.deactivate"),
        ("switch off the summer price list", "en", "pricing.price_list.deactivate"),
        ("turn on the summer price list again", "en", "pricing.price_list.activate"),
        ("switch on the summer price list again", "en", "pricing.price_list.activate"),
        # «Apaga» and «enciende» as «desactiva» and «activa» (ERPlora/live#79).
        ("apaga la tarifa de verano", "es", "pricing.price_list.deactivate"),
        ("enciende otra vez la tarifa de verano", "es", "pricing.price_list.activate"),
        ("apaga la app de reservas", "es", "base.app.disable"),
        ("enciende la app de reservas", "es", "base.app.enable"),
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
        ("switch off the sales", "en", "base.app.disable"),
        ("turn on the sales", "en", "base.app.enable"),
        ("switch on the sales", "en", "base.app.enable"),
        ("apaga las ventas", "es", "base.app.disable"),
        ("enciende las ventas", "es", "base.app.enable"),
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


class ProductImageIn(Schema):
    product: str
    image: str | None = None


#: The rules of two apps, as the Hub's say of themselves: Taxes', whose menu says «Reglas», and Pricing's discount
#: rules, beside what a rule is of (Products, the Kitchen), a write that takes a product, a discount and the apps'
#: switches.
RULES_OF_TWO_APPS = [
    *APPROVED_OR_SWITCHED,
    tool("tax.rule.activate", "Bring a deactivated tax rule back so it applies to new operations again.",
         asks={"es": ("reactiva la regla de IVA de los libros",
                      "vuelve a poner en marcha en España la regla de impuestos de la comida")}),
    tool("tax.rule.deactivate", "Deactivate a tax rule so it no longer applies to new operations.",
         asks={"es": ("desactiva la regla de IVA de los libros", "deja de aplicar por ahora la regla fiscal del 10 %")}),
    tool("tax.rule.list", "List the tax rules.", "query"),
    tool("pricing.rule.activate", "Bring a deactivated discount rule (by its id, code or name) back, so it applies to "
         "new sales.", asks={"es": ("reactiva la promoción de verano",
                                    "vuelve a aplicar el descuento de verano en las ventas nuevas")}),
    tool("pricing.rule.deactivate", "Deactivate a discount rule (by its id, code or name) so it no longer takes "
         "anything off new sales.", asks={"es": ("apaga el 2x1 de zumos hasta el año que viene",)}),
    tool("inventory.product.set_image", "Put a product's image.", input=ProductImageIn),
    tool("kitchen.station.deactivate", "Stop sending orders to a kitchen station."),
    tool("sale.order.set_discount", "Give an open check a discount."),
]
RULE_APPS = {
    "tax": "tax taxes impuestos reglas", "pricing": "pricing tarifas precios",
    "inventory": "inventory products productos", "kitchen": "kitchen cocina", "sale": "sale sales ventas",
}


def rule_apps(label: str, language: str) -> frozenset[str]:
    return frozenset(assistant.stems(RULE_APPS.get(label, label)))


@pytest.mark.parametrize(
    ("asked", "rules", "switch"),
    [
        ("vuelve a activar la regla de los productos", {"tax.rule.activate", "pricing.rule.activate"},
         "base.app.enable"),
        ("desactiva la regla española de los productos sin perder su porcentaje",
         {"tax.rule.deactivate", "pricing.rule.deactivate"}, "base.app.disable"),
        ("desactiva la regla de la cocina", {"tax.rule.deactivate", "pricing.rule.deactivate"}, "base.app.disable"),
    ],
)
def test_a_rule_switched_is_a_rule_before_the_switch_of_an_app(asked, rules, switch):
    """«Vuelve a activar la regla de los productos» reactivates a rule: «regla» is a rule in either language, so the
    rules' own switches come first, before turning an app on and before a write of what the rule is of
    (ERPlora/live#73: «regla» only named Taxes by its menu, and beside «los productos», a thing, that only broke ties;
    turning Taxes on and putting a product's image came first)."""
    offered_ = ranked(RULES_OF_TWO_APPS, asked, app_words=rule_apps)
    place = {name: at for at, name in enumerate(offered_)}
    assert offered_[0] in rules, offered_[:4]
    assert all(place.get(name, len(offered_)) < place.get(switch, len(offered_)) for name in rules), offered_[:6]


@pytest.mark.parametrize(
    ("asked", "first"),
    [
        ("reactiva la regla de descuento", "pricing.rule.activate"),
        ("vuelve a activar la regla de precios de los martes", "pricing.rule.activate"),
        ("desactiva la regla de descuento del 10 %", "pricing.rule.deactivate"),
    ],
)
def test_the_rule_of_a_discount_is_pricings(asked, first):
    """«La regla de descuento», «la regla de precios»: what the rule is of says whose rule it is, Pricing's
    (ERPlora/live#73 and its review: Taxes' rule, by its menu, must not take its place)."""
    offered_ = ranked(RULES_OF_TWO_APPS, asked, app_words=rule_apps)
    assert offered_[0] == first, offered_[:4]


#: The apps the switch of an app names after a word that names nothing of the catalogue («el punto de venta»), beside
#: a read of each, a write that takes its thing, as the Hub's do (``customer.customer.set_groups`` takes the customer),
#: and what turns on or off another thing (a recurring series): they compete with the app's own switch.
THINGS_OF_APPS = (("sale", "sale"), ("appointment", "appointment"), ("customer", "customer"),
                  ("reservation", "booking"), ("inventory", "stock"), ("kitchen", "ticket"))
APPS_BY_A_PART = [
    tool("base.app.enable", "Turns on one of this business's apps, with the apps it needs."),
    tool("base.app.disable", "Turns off one of this business's apps."),
    tool("appointment.recurring.activate", "Bring a recurring series back."),
    tool("appointment.recurring.deactivate", "Stop a recurring series for now."),
    *(tool(f"{app}.{thing}.list", f"Lists the {thing}s of the business.", "query") for app, thing in THINGS_OF_APPS),
    *(tool(f"{app}.{thing}.set_note", f"Puts a note on a {thing}.", input=create_model(f"{thing}In", **{thing: (str, ...)}))
      for app, thing in THINGS_OF_APPS),
    *NOISE,
]
PART_APPS = {
    "sale": "sale sales ventas", "appointment": "appointments citas", "customer": "customers clientes",
    "reservation": "reservations bookings reservas", "inventory": "inventory inventario", "kitchen": "kitchen cocina",
}


def part_apps(label: str, language: str) -> frozenset[str]:
    return frozenset(assistant.stems(PART_APPS.get(label, label)))


@pytest.mark.parametrize(
    ("asked", "language", "switch"),
    [
        ("activa el punto de venta", "es", "base.app.enable"),
        ("turn on the point of sale", "en", "base.app.enable"),
        ("activa el sistema de citas", "es", "base.app.enable"),
        ("desactiva la gestión de clientes", "es", "base.app.disable"),
        ("desactiva la función de reservas", "es", "base.app.disable"),
        ("activa la parte de reservas", "es", "base.app.enable"),
        ("turn on the management of bookings", "en", "base.app.enable"),
        ("activa la funcionalidad de cocina", "es", "base.app.enable"),
        ("activa la gestión de inventario", "es", "base.app.enable"),
    ],
)
def test_an_app_named_after_a_word_that_names_nothing_is_the_app_switched(asked, language, switch):
    """«El punto de venta», «la gestión de clientes»: a word that names nothing of the catalogue only leads to the app
    named after «de» or «of», and that is the app switched (the review of ERPlora/live#73: read as what another thing
    is of, the switch of the app fell behind)."""
    names_ = ranked(APPS_BY_A_PART, asked, language, app_words=part_apps)
    assert switch in names_[:2], names_[:4]


#: The payment methods of the Hub's Payments, whose menu says «Pagos» and «Métodos», as theirs say of themselves,
#: beside the till's own methods of Sales, the apps' switches and a price list's: what a switch of a method competes
#: with.
PAYMENT_METHODS = [
    tool("base.app.enable", "Turns on one of this business's apps, with the apps it needs."),
    tool("base.app.disable", "Turns off one of this business's apps: it leaves everyone's menu and its screens."),
    tool("payment.method.activate", "Activate a deactivated payment method again (named by its id or its name), so "
         "new payments can use it.", asks={"es": ("reactiva la cuenta bancaria del Sabadell para los pagos",),
                                           "en": ("reactivate the Santander bank account for outgoing payments",)}),
    tool("payment.method.deactivate", "Deactivate a payment method (named by its id or its name): a new payment can "
         "no longer use it; the payments that used it keep it. It is never deleted.",
         asks={"es": ("que la cuenta del Sabadell ya no se use en pagos nuevos",),
               "en": ("stop using the Sabadell bank account for new payments",)}),
    tool("payment.method.create", "Create a payment method the business pays with: a bank account or a card."),
    tool("payment.method.update", "Change a payment method: its name or its details."),
    tool("payment.method.list", "List the payment methods.", "query"),
    tool("payment.payment.create", "Register an outgoing payment."),
    tool("payment.payment.list", "List the outgoing payments.", "query"),
    tool("sale.payment_method.create", "Adds a payment method the till charges with (cash, card, transfer)."),
    tool("sale.payment_method.list", "List the active payment methods of the charge sheet.", "query"),
    tool("sale.sale.list", "Lists the sales of a day.", "query"),
    tool("kitchen.ticket.list", "Lists the kitchen's tickets.", "query"),
    tool("pricing.price_list.activate", "Bring a price list back into use for new sales."),
    tool("pricing.price_list.deactivate", "Stop using a price list for new sales; its prices stay."),
    *NOISE,
]
PAYMENT_APPS = {
    "payment": "payment payments pagos methods métodos", "sale": "sale sales ventas", "kitchen": "kitchen cocina",
    "pricing": "pricing tarifas precios",
}


def payment_apps(label: str, language: str) -> frozenset[str]:
    return frozenset(assistant.stems(PAYMENT_APPS.get(label, label)))


@pytest.mark.parametrize(
    ("asked", "language", "first"),
    [
        ("vuelve a activar el método de pago de Bizum", "es", "payment.method.activate"),
        ("reactiva el método de pago de Bizum", "es", "payment.method.activate"),
        ("activa el método de pago Bizum", "es", "payment.method.activate"),
        ("habilita el método de pago Transferencia", "es", "payment.method.activate"),
        ("vuelve a activar los métodos de pago de tarjeta y Bizum", "es", "payment.method.activate"),
        ("desactiva el método de pago de Bizum", "es", "payment.method.deactivate"),
        ("deshabilita el método de pago de tarjeta", "es", "payment.method.deactivate"),
        ("apaga el método de pago Bizum", "es", "payment.method.deactivate"),
        ("enciende el método de pago Bizum", "es", "payment.method.activate"),
        ("vuelve a encender el método de pago de Bizum", "es", "payment.method.activate"),
        ("reactivate the payment method of Bizum", "en", "payment.method.activate"),
        ("turn off the Bizum payment method", "en", "payment.method.deactivate"),
        # The app named by its name, or as an app, is still the one switched.
        ("activa la app de pagos", "es", "base.app.enable"),
        ("desactiva el módulo de pagos", "es", "base.app.disable"),
        ("activa Pagos", "es", "base.app.enable"),
        ("apaga la cocina", "es", "base.app.disable"),
        ("enciende la cocina", "es", "base.app.enable"),
        ("turn on the payments app", "en", "base.app.enable"),
    ],
)
def test_a_payment_method_switched_is_a_method_before_the_switch_of_its_app(asked, language, first):
    """«Vuelve a activar el método de pago de Bizum» reactivates a payment method: «método» is a method in either
    language, so the method's own switch comes first, before turning on Payments, which «pago» and its menu
    «Métodos» name; «apaga» and «enciende» switch it as «desactiva» and «activa» do (ERPlora/live#79: «método» named
    only the app, and «apaga» only switched apps off, so turning Payments on or off came first)."""
    assert ranked(PAYMENT_METHODS, asked, language, app_words=payment_apps)[0] == first


class AppointmentRefIn(Schema):
    appointment: str


class CustomerActiveIn(Schema):
    customer: str
    is_active: bool | None = None


#: The switches of the ready-made automations an app brings (the Hub's Flows recipes), whose asks name the appointment
#: reminders as people say them, beside what competes with them in the Hub: the apps' switches, a write that takes an
#: appointment, a read of past appointments, the switches of a recurring series, the business's records (VeriFactu's
#: and the clock-ins'), a staff member's switch, a customer's write, a tax rule's switch whose asks say «aplicar» (a
#: stem «aplicación» shares) and two other things switched that only their asks name (a promotion of Pricing, a card of
#: Payments).
SWITCHED_BY_THEIR_ASKS = [
    tool("base.app.enable", "Turns on one of this business's apps, with the apps it needs."),
    tool("base.app.disable", "Turns off one of this business's apps: it leaves everyone's menu and its screens."),
    tool("flow.recipe.enable", "Turn on a ready-made automation an app brings, with the permissions it asks for.",
         asks={"es": ("activa la receta de recordatorio de citas",),
               "en": ("activate the ready-made reminder automation",)}),
    tool("flow.recipe.disable", "Turn off a ready-made automation an app brings: it is paused, never deleted.",
         asks={"es": ("apaga la receta del recordatorio de citas",), "en": ("turn off the appointment reminder recipe",)}),
    tool("flow.recipe.bulk_disable", "Turn off several ready-made automations at once.",
         asks={"es": ("apaga de golpe todas las recetas de recordatorio",)}),
    tool("flow.recipe.list", "List the ready-made automations the apps bring.", "query"),
    tool("appointment.appointment.list", "List the appointments of some days.", "query"),
    tool("appointment.appointment.update", "Change an appointment: its day, its time, its notes."),
    tool("appointment.appointment.history", "List a customer's past appointments.", "query",
         asks={"es": ("¿qué citas ha tenido Carmen este año?", "¿le llegó el recordatorio de su última cita?")}),
    tool("appointment.recurring.activate", "Bring a recurring series of appointments back.",
         asks={"es": ("reanuda la cita fija de Teresa",)}),
    tool("appointment.recurring.deactivate", "Stop a recurring series of appointments for now.",
         asks={"es": ("desactiva la cita semanal de Carmen en verano",)}),
    tool("sale.order.set_appointment", "Link an open check to the appointment it charges.", input=AppointmentRefIn),
    tool("reservation.reservation.list", "Lists the reservations of a day.", "query"),
    tool("verifactu.record.list", "List the VeriFactu records of the invoices.", "query"),
    tool("verifactu.record.get", "Get one VeriFactu record.", "query"),
    tool("attendance.record.list", "List the clock-in records of the staff.", "query"),
    tool("tax.rule.deactivate", "Deactivate a tax rule so it no longer applies to new operations.",
         asks={"es": ("deja de aplicar por ahora la regla fiscal del 10 %",
                      "desactiva de momento la regla de impuestos de la comida")}),
    tool("pricing.price_list.deactivate", "Deactivate a price list: no new sale takes its prices.",
         asks={"es": ("quita la de verano por ahora, hasta el año que viene",)}),
    tool("pricing.rule.activate", "Bring a deactivated discount rule back.",
         asks={"es": ("reactiva la promoción de verano", "que el descuento por pagar con tarjeta vuelva a valer")}),
    tool("pricing.rule.deactivate", "Deactivate a discount rule.",
         asks={"es": ("apaga el 2x1 de zumos hasta el año que viene", "quita de momento el descuento de los jueves")}),
    tool("payment.method.activate", "Activate a deactivated payment method again.",
         asks={"es": ("que la tarjeta de empresa vuelva a servir para pagar a proveedores",)}),
    tool("payment.method.deactivate", "Deactivate a payment method: a new payment can no longer use it.",
         asks={"es": ("la tarjeta de empresa antigua ya no vale para los pagos salientes",)}),
    tool("staff.member.deactivate", "Deactivate a member of the staff: they no longer sign in.",
         asks={"es": ("desactiva a Ana mientras esté de baja",)}),
    tool("customer.customer.update", "Change a customer: their data, active or not.", input=CustomerActiveIn),
    *NOISE,
]
SWITCHED_APPS = {
    "appointment": "appointments citas agenda", "reservation": "reservations bookings reservas",
    "flow": "flows automations automatizaciones", "sale": "sale sales ventas", "pricing": "pricing tarifas precios",
    "payment": "payments pagos", "staff": "staff personal", "customer": "customers clientes",
    "verifactu": "verifactu", "attendance": "attendance fichaje", "tax": "taxes impuestos reglas",
}
#: The Hub's own words: «desactiva» names a deactivation, and a ready-made automation is a «receta».
SWITCHED_WORDS = (("desactiva", "desactivar", "deactivate"), ("receta", "recetas", "recipe", "recipes"))


def switched_apps(label: str, language: str) -> frozenset[str]:
    return frozenset(assistant.stems(SWITCHED_APPS.get(label, label)))


def switched(asked: str, language: str = "es") -> list[str]:
    return ranked(SWITCHED_BY_THEIR_ASKS, asked, language, app_words=switched_apps, synonyms=SWITCHED_WORDS)


@pytest.mark.parametrize(
    ("asked", "language", "first"),
    [
        ("desactiva los recordatorios de citas", "es", "flow.recipe.disable"),
        ("apaga los recordatorios de las citas", "es", "flow.recipe.disable"),
        ("desactiva el recordatorio de las citas", "es", "flow.recipe.disable"),
        ("deshabilita los recordatorios de citas", "es", "flow.recipe.disable"),
        ("quiero desactivar los recordatorios de las citas", "es", "flow.recipe.disable"),
        ("activa los recordatorios de citas", "es", "flow.recipe.enable"),
        ("enciende los recordatorios de las citas", "es", "flow.recipe.enable"),
        ("vuelve a activar los recordatorios de citas", "es", "flow.recipe.enable"),
        ("reactiva los recordatorios de citas", "es", "flow.recipe.enable"),
        ("desactiva los recordatorios de las reservas", "es", "flow.recipe.disable"),
        ("apaga los recordatorios de la agenda", "es", "flow.recipe.disable"),
        ("apaga los recordatorios", "es", "flow.recipe.disable"),
        ("turn off the appointment reminders", "en", "flow.recipe.disable"),
        ("switch off the appointment reminders", "en", "flow.recipe.disable"),
        ("deactivate the appointment reminders", "en", "flow.recipe.disable"),
        ("turn off the reminders of the bookings", "en", "flow.recipe.disable"),
        ("turn on the appointment reminders", "en", "flow.recipe.enable"),
        ("switch on the reminders of the appointments", "en", "flow.recipe.enable"),
        ("turn off the booking and appointment reminders", "en", "flow.recipe.disable"),
        # Another app's thing that only the asks of its switches name, beside the app named.
        ("reactiva la promoción de verano de las ventas", "es", "pricing.rule.activate"),
        ("desactiva la tarjeta de empresa de pagos", "es", "payment.method.deactivate"),
        ("desactiva la tarjeta de las ventas", "es", "payment.method.deactivate"),
    ],
)
def test_a_thing_only_the_asks_of_its_switch_name_is_switched_before_its_app(asked, language, first):
    """«Desactiva los recordatorios de citas» turns the reminders off, not the Appointments app: what a switch turns off
    names no thing of the catalogue but by the app said with it, and the asks of the switch that turns it off name it,
    with that app — that is its switch (ERPlora/live#89: «recordatorios» read as records, and the app named as whose
    they are turned the app off first)."""
    names = switched(asked, language)
    assert names[0] == first, names[:4]


@pytest.mark.parametrize(
    ("asked", "language", "first"),
    [
        ("desactiva la app de citas", "es", "base.app.disable"),
        ("desactiva la app de reservas", "es", "base.app.disable"),
        ("desactiva ahora la app de reservas", "es", "base.app.disable"),
        ("desactiva el módulo de citas", "es", "base.app.disable"),
        ("apaga la app de citas", "es", "base.app.disable"),
        ("enciende la app de citas", "es", "base.app.enable"),
        ("desactiva Reservas", "es", "base.app.disable"),
        ("activa otra vez las reservas", "es", "base.app.enable"),
        ("turn off the bookings app", "en", "base.app.disable"),
        ("turn on the appointment app", "en", "base.app.enable"),
    ],
)
def test_the_app_named_as_what_is_switched_is_still_switched_beside_those_switches(asked, language, first):
    """The app itself, named as what the command switches, is still turned on or off by its own switch beside the
    switches whose asks name it (ERPlora/live#89): «app» is a thing of the catalogue, so a tax rule's asks that say
    «aplicar» do not make that rule what «desactiva la app de reservas» turns off."""
    names = switched(asked, language)
    assert names[0] == first, names[:4]


@pytest.mark.parametrize(
    ("asked", "language"),
    [
        ("desactiva al cliente Ana", "es"),
        ("apaga al cliente Ana", "es"),
    ],
)
def test_a_name_said_beside_a_thing_switched_is_no_switch_of_another_thing(asked, language):
    """«Desactiva al cliente Ana»: «Ana» is whom, beside «cliente», and the asks of a member's switch that only say
    «Ana» do not make it the thing switched — a switch's asks name the thing only with the app said beside it."""
    names = switched(asked, language)
    assert names.index("customer.customer.update") < names.index("staff.member.deactivate"), names[:4]


def test_a_read_whose_asks_name_what_is_switched_off_is_no_switch_of_it():
    """«Apaga a Carmen»: only the asks of a switch of that action name what it turns off; a read whose asks say «Carmen»
    is not what is turned off, and the member's switch still comes before it (ERPlora/live#89)."""
    names = switched("apaga a Carmen")
    assert names.index("staff.member.deactivate") < names.index("appointment.appointment.history"), names[:4]


@pytest.mark.parametrize(
    ("asked", "first"),
    [
        ("desactiva de momento la regla de descuento", "pricing.rule.deactivate"),
        ("desactiva de momento los recordatorios de citas", "flow.recipe.disable"),
        ("desactiva por ahora los recordatorios de citas", "flow.recipe.disable"),
        # Two things of one app say it («hasta el año que viene»: a discount and a price list of Pricing).
        ("desactiva hasta el año que viene los recordatorios de citas", "flow.recipe.disable"),
    ],
)
def test_a_word_the_switches_of_several_things_say_is_none_of_them(asked, first):
    """«Desactiva de momento la regla de descuento»: «de momento» and «por ahora» say for how long, and the asks of the
    switches of several things say them (a tax rule's, a discount's, a price list's); such a word is the thing of no
    switch, so the tax rule whose asks say «de momento la regla» does not come before the discount rule, nor before
    the reminders' recipe (ERPlora/live#89). The things are counted, not their tools (the recipes' two switches that
    turn off say «recordatorio»), and only by the switches of the action asked: a read that says «recordatorio» or a
    discount brought back that says «tarjeta» leaves the reminders and the card what is turned off."""
    names = switched(asked)
    assert names[0] == first, names[:4]


def test_the_switch_of_another_action_is_no_switch_of_what_is_turned_off():
    """«Apaga los recordatorios»: the switch that turns them on says them too, and is not the one asked for; it comes
    after every switch that turns something off (ERPlora/live#89)."""
    names = switched("apaga los recordatorios")
    off = [name for name in names if name.rsplit(".", 1)[1] in {"disable", "deactivate"}]
    assert len(off) > 5  # positive control
    assert all(names.index(name) < names.index("flow.recipe.enable") for name in off), names[:6]


class ThemeIn(Schema):
    language: str
    theme_mode: str
    palette: str
    ui_scale: int


class DeviceModeIn(Schema):
    mode: str


#: The person's own look and the device in hand made shared or personal, as the Hub's say them, beside the switches of
#: the Hub's things.
THEME_AND_SWITCHES = [
    *SWITCHED_BY_THEIR_ASKS,
    tool("base.profile.preferences_set", "Sets the person's own language (Spanish, English or the business's) and "
         "appearance.", input=ThemeIn,
         asks={"es": ("ponme el idioma en inglés", "quiero el modo oscuro", "cámbiame la apariencia a clara"),
               "en": ("switch me to English", "put the app in dark mode", "change my language to Spanish")}),
    tool("base.device.mode_set", "Makes the device the person is using shared (a till several people use: PIN, a "
         "shift) or personal (one person's: no PIN, 30 days).", input=DeviceModeIn,
         asks={"es": ("pon esta tablet como caja compartida",), "en": ("make this tablet a shared till",)}),
]
SWITCHES = {"enable", "disable", "activate", "deactivate"}


def themed(asked: str, language: str = "es") -> list[str]:
    return ranked(THEME_AND_SWITCHES, asked, language, app_words=switched_apps, synonyms=SWITCHED_WORDS)


@pytest.mark.parametrize(
    "asked",
    [
        "desactiva el modo oscuro",
        "activa el modo oscuro",
        "apaga el modo oscuro",
        "enciende el modo oscuro",
        "quiero desactivar el modo oscuro",
        "desactiva el modo claro",
        "enciende el modo claro",
        "activa el tema oscuro",
        "apaga el tema oscuro",
        "activa el tema claro",
        "deshabilita el tema claro",
    ],
)
def test_the_dark_or_light_mode_switched_is_the_persons_theme(asked):
    """«Desactiva el modo oscuro» changes the person's theme: «modo oscuro» and «tema oscuro» (and their light ones) are
    how Spanish names the theme a person's preferences take, as «dark mode» and «theme» name it in English, so that
    change comes first (ERPlora/live#91: they named nothing it takes, and every switch of the Hub came before it)."""
    names = themed(asked)
    assert names[0] == "base.profile.preferences_set", names[:4]


@pytest.mark.parametrize(
    ("asked", "language"),
    [
        ("desactiva el modo oscuro", "es"),
        ("enciende el modo claro", "es"),
        ("apaga el tema oscuro", "es"),
        ("turn off the dark mode", "en"),
        ("switch on the dark mode", "en"),
        ("enable the dark theme", "en"),
    ],
)
def test_the_theme_switched_comes_before_every_switch_of_another_thing(asked, language):
    """What turns the theme on or off is the change of the person's preferences, in either language: no switch of a
    member, a rule, a series or an app comes before it (ERPlora/live#91)."""
    names = themed(asked, language)
    off_or_on = [name for name in names if name.rsplit(".", 1)[1] in SWITCHES]
    assert len(off_or_on) >= 4  # positive control
    assert all(names.index("base.profile.preferences_set") < names.index(name) for name in off_or_on), names[:6]


def theme_named(said: str) -> bool:
    return any("them" in concept for concept in assistant.asked([said]).concepts)


@pytest.mark.parametrize(
    ("said", "theme"),
    [
        ("activa el modo oscuro", True),
        ("pon el modo claro", True),
        ("activa el tema oscuro", True),
        ("quiero el tema claro", True),
        ("change the theme", True),
        # «Tema» alone is also the matter, and «modo» a way: only the phrases name the theme.
        ("desactiva el tema de los recordatorios", False),
        ("cierra la caja, de modo que nadie cobre", False),
        ("pon esta tablet en modo compartido", False),
    ],
)
def test_only_the_dark_or_light_mode_or_theme_names_the_theme(said, theme):
    """``asked``: «modo oscuro», «modo claro», «tema oscuro» and «tema claro» name the theme as «theme» does."""
    assert theme_named(said) is theme


def concepts_of(*said: str) -> frozenset[frozenset[str]]:
    return frozenset(assistant._concept(assistant._plain(word)) for word in said)


@pytest.mark.parametrize(
    ("said", "heads"),
    [
        ("desactiva los recordatorios de las citas", {concepts_of("recordatorios")}),
        ("apaga los recordatorios de citas", {concepts_of("recordatorios")}),
        ("turn off the appointment reminders", {concepts_of("appointment", "reminders")}),
        ("turn off the reminders of the bookings", {concepts_of("reminders")}),
        ("apaga los recordatorios del salón", {concepts_of("recordatorios")}),
        ("reactiva la promoción de verano para las ventas", {concepts_of("promoción")}),
        ("turn on the reminders for the appointments", {concepts_of("reminders")}),
        # A verb said inside names nothing, as anywhere else: the sale «charge» names is not what is turned off.
        ("turn off the reminders when I charge", {concepts_of("reminders")}),
        # What says of what or for what is said before the thing named («de momento») ends nothing.
        ("desactiva de momento los recordatorios de citas", {concepts_of("momento", "recordatorios")}),
        # Up to another command; each switch its own.
        ("desactiva los recordatorios y lista las citas", {concepts_of("recordatorios")}),
        ("apaga la cocina y enciende la barra", {concepts_of("cocina"), concepts_of("barra")}),
        ("turn on the reminders and turn off the bookings", {concepts_of("reminders"), concepts_of("bookings")}),
        # The pronouns of a command switch too; what a switch is not asked to do turns nothing off.
        ("desactívalos ya, los recordatorios", set()),
        ("cambia la cita sin desactivar los recordatorios", set()),
        ("lista los recordatorios de citas", set()),
        ("cambia el nombre de los recordatorios", set()),
    ],
)
def test_what_a_switch_turns_on_or_off_is_named_up_to_what_it_is_of(said, heads):
    """``Asked.switched``: of each switch said («desactiva», «turn off»), the things named after it up to the first word
    that says what they are of or for («de», «of», «para», «for») or another command (ERPlora/live#89)."""
    assert assistant.asked([said]).switched == heads


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
        ("sella sellar sellado sellamos sellan séllalo sello sellos selló selle sellen sellemos selléis", "sellar"),
        ("existe existen existir existiera existía exist exists existing existed existence", "existir"),
        ("producción producciones production productions", "produccion"),
        ("comprueba compruebo comprobar comprobando comprobado comprobación comprobante compruébalo", "comprobar"),
        ("recordatorio recordatorios", "recordatori"),
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
