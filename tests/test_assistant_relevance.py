"""The few tools a turn offers of a catalogue of hundreds (``live.assistant.relevant``): what a person asks, in their
everyday words in Spanish or English, reaches the operation that does it.

The QA battery of the assistant with the real model (2026-10-31; ERPlora/live issue of the selection) found three
questions of an owner that never reached their tool: «Da de alta al empleado…» (``staff.member.create``), «¿Qué
vendí hoy?» (a read of ``sale``) and «Activa la app de clientes» (``base.app.enable``). The catalogue below is a
slice of the Hub's, with its real descriptions, drowned in tools that share the verb and nothing else, as the
Hub's 700 do.
"""

import time
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
