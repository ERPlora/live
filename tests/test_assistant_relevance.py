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
        ("cambia el nombre del menú", "es", {"rename"}),
        ("rename the menu", "en", {"rename"}),
        ("apunta un menú", "es", {"add", "create"}),
        ("empieza un menú", "es", {"open", "start"}),
        ("start a menu", "en", {"open", "start"}),
        ("ponle de nombre «Carta de verano» al menú", "es", {"rename"}),
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
    ("said", "english"),
    [
        ("los avisos", "alert"), ("las notificaciones", "alert"), ("the notices", "notification"),
        ("los grupos", "group"), ("las compras", "purchase"), ("sus datos", "data"), ("las descargas", "download"),
        ("los dispositivos", "device"), ("este aparato", "device"), ("la carpeta", "folder"), ("mi perfil", "profile"),
        ("mi foto de perfil", "avatar"), ("la ficha", "card"), ("recibir", "receive"), ("la devolución", "refund"),
        ("el reembolso", "refund"), ("las cuentas aparcadas", "park"),
        ("las etiquetas", "tag"), ("el portátil", "device"), ("este ordenador", "device"), ("la tablet", "device"),
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


def test_receiving_goods_is_not_a_receipt():
    tools = [tool("kitchen.ticket.print", "Prints the receipt of a ticket."),
             tool("purchase.order.receive", "Receives the goods of a purchase order into the stock.")]
    assert ranked(tools, "recibe la mercancía del proveedor")[0] == "purchase.order.receive"
    assert ranked(tools, "imprime el recibo")[0] == "kitchen.ticket.print"


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
