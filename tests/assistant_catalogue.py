"""The catalogue the relevance tests rank: a slice of the Hub's tools drowned in tools that share the verb, and the
slices more than one of those tests ranks."""

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


def takes(*fields: str) -> type[Schema]:
    """An input that takes ``fields``, none of them required."""
    return create_model("In", __base__=Schema, **{field: (str | None, None) for field in fields})


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

def ranked(tools, asked: str, language: str = "es", **kwargs) -> list[str]:
    return [op.name for op in assistant.relevant({op.name: op for op in tools}, [asked], language, **kwargs)]


MENU_ACTIONS = {
    "add": "command", "check": "query", "count": "query", "create": "command", "delete": "command",
    "erase": "command", "export": "query", "get": "query", "import": "command", "list": "query",
    "open": "command", "remove": "command", "rename": "command", "set": "command", "start": "command",
    "stats": "query", "update": "command",
}
#: A write that does nothing asked comes first by name: what the verb asks has to earn its place.
MENU = [tool("menu.menu.aaa", "Does it to a menu."),
        *(tool(f"menu.menu.{action}", "Does it to a menu.", kind) for action, kind in MENU_ACTIONS.items())]
#: The Hub's own words (``base.assistant.SYNONYMS``): a «cuenta» is a table's check, ``sale.order``.
CHECK = (("cuenta", "check", "tab", "order"),)


class MovementIn(Schema):
    type: str
    amount: int
    description: str | None = None


class CustomerIn(Schema):
    name: str | None = None
    phone: str | None = None
TILL_APPS = {
    "cash_register": "caja cash register", "printing": "impresión printing", "sale": "ventas sale tpv notas rápidas",
    "appointment": "citas appointments", "staff": "personal staff turnos", "customer": "clientes customers",
}


def till_apps(label: str, language: str) -> frozenset[str]:
    return frozenset(assistant.stems(TILL_APPS.get(label, label)))


#: The movement of the till as the Hub says it is asked for («apunta una salida de 35 € de la caja»), beside the shifts
#: of the staff, which share the word «turno», the creates of what «registra» also writes down and the writes of things
#: nobody names.
REGISTERED_AT_THE_TILL = [
    tool("cash_register.movement.add", "Record cash brought into the drawer or taken out of it in the open session.",
         input=MovementIn, asks={"es": ("apunta una salida de 35 € de la caja", "mete 50 € de cambio en la caja")}),
    tool("cash_register.movement.list", "List the money put in or taken out of a session.", "query"),
    tool("staff.schedule.create", "Create a shift of the schedule for a member."),
    tool("staff.schedule.update", "Change a shift of the schedule: its hours or its member."),
    tool("staff.schedule.detail", "Show a shift of the schedule: its member, its hours.", "query"),
    tool("staff.schedule.list", "List the shifts of the schedule, by day.", "query"),
    tool("staff.schedule.delete", "Delete a shift of the schedule."),
    tool("customer.customer.create", "Creates a new customer; only the name is required.", input=CustomerIn),
    tool("inventory.product.create", "Create a product of the catalog with its name and its price.", input=ProductIn),
    *NOISE,
]


#: What «desactiva» and «activa» ask for: switching a thing off or on, as an app's switch does, or deactivating and
#: activating it, as a member, a price list or a rule are; the thing named says which.
SWITCHING_OFF = {"disable", "deactivate"}
SWITCHING_ON = {"enable", "activate"}


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
