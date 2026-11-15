"""What a turn offers when it names an app by its own name, in a project's own words or among the SaaS panel's tools."""

import time
import unicodedata

import pytest
from ninja import Schema

from live import assistant
from tests.assistant_catalogue import DEVICES, HUB_SLICE, NOISE, offered, ranked, tool


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
