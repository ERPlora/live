"""The action asked reaches a tool whose name says it another way: «activa» turns on what ``set_enabled`` switches,
«renombra» is a change that takes a name, and «permite a…», «dale permiso» and «concede» grant (ERPlora/live#53: an
automation named by its own name was offered none of the three)."""

import pytest
from ninja import Schema
from pydantic import create_model

from live import assistant
from tests.assistant_catalogue import NOISE, ranked, tool


def takes(*fields: str) -> type[Schema]:
    return create_model("In", __base__=Schema, **{field: (str | None, None) for field in fields})


#: The Hub's tools of an automation, as Automations describes them and asks for them.
AUTOMATIONS = [
    tool("flow.flow.set_enabled", "Turn an automation on or pause it, by its id or its name («activate the welcome "
         "automation», «pause the cash close one»). A schedule turned on counts from now. Turning on one that lacks "
         "permissions leaves it doing nothing until they are granted: say so.", input=takes("id", "flow", "enabled"),
         asks={"en": ("turn on the welcome automation", "pause the birthday automation"),
               "es": ("enciende la automatización que salta al cobrar una venta",
                      "pausa la automatización de cumpleaños", "vuelve a encender la automatización de reseñas")}),
    tool("flow.flow.update", "Change an automation, by its id or its name: its name, what starts it or its steps (to "
         "turn it on or pause it, `flow.flow.set_enabled`). Only what is sent changes; its permissions stay.",
         input=takes("id", "flow", "name", "trigger", "steps"),
         asks={"en": ("change the name of the welcome automation to «New customers»",
                      "change the steps of the birthday automation"),
               "es": ("cambia el nombre de la automatización de bienvenida a «Clientes nuevos»",
                      "modifica los pasos de la automatización de cumpleaños")}),
    tool("flow.flow.grant", "Set the whole list of actions and reads an automation may run, by name: what is not in "
         "the list is withdrawn. An automation does nothing it was not allowed.",
         input=takes("id", "flow", "operations"),
         asks={"en": ("grant the welcome automation the permission to create tasks",
                      "give the birthday automation permission to send WhatsApp messages"),
               "es": ("dale permiso a la automatización de bienvenida para crear tareas",
                      "deja que la automatización de cumpleaños mande WhatsApp a los clientes",
                      "autoriza a la automatización de las ventas cobradas a leer los clientes")}),
    tool("flow.flow.detail", "One automation by its id or its name: its trigger, its steps, the permissions it needs "
         "and the ones it lacks, and its last run.", "query", input=takes("id", "flow"),
         asks={"en": ("what permissions is the birthday automation missing?",),
               "es": ("dime los pasos y los permisos de la automatización de cumpleaños",)}),
    tool("flow.flow.duplicate", "Copy an automation: «Copy of …», paused, with the same trigger and steps and none of "
         "its permissions or history.", input=takes("id", "flow")),
    tool("flow.recipe.enable", "Turn on a ready-made automation an app brings. The first time it is built and left on "
         "with exactly the permissions the recipe asks for.", input=takes("recipe"),
         asks={"en": ("activate the ready-made reminder automation",),
               "es": ("activa la receta de recordatorio de citas",)}),
    tool("flow.recipe.disable", "Turn off a ready-made automation an app brings: it is paused, never deleted; its "
         "permissions and its history stay.", input=takes("recipe")),
]
#: The Hub's tools that outran them: another app's switches, grants and changes that take a name, and what a request
#: names besides the automation (the sale it may read, the WhatsApp it may send).
OTHERS = [
    tool("base.app.enable", "Turns on one of this business's apps (by its name as the person says it, or its id), "
         "with the apps it needs: it shows in the menu and can be used, with the data it had.", input=takes("app")),
    tool("pricing.rule.activate", "Bring a deactivated discount rule (by its id, code or name) back, so it applies "
         "to new sales.", input=takes("id", "rule")),
    tool("payment.method.activate", "Activate a deactivated payment method again (named by its id or its name), so "
         "new payments can use it.", input=takes("id", "method")),
    tool("customer.consent.grant", "Records that a customer gave consent for a purpose, marketing by default, on a "
         "channel (email, SMS, WhatsApp, phone or post), as a new fact with its evidence.",
         input=takes("customer_id", "customer", "channel", "notice_text", "purpose", "source", "evidence"),
         asks={"en": ("Ana says yes to WhatsApp offers",), "es": ("Marta nos da permiso para los SMS",)}),
    tool("customer.consent.state", "Whether a customer agreed to be sent marketing by email, SMS, WhatsApp, phone or "
         "post: the consent in force, granted or withdrawn.", "query", input=takes("customer_id", "customer"),
         asks={"en": ("has Marta agreed to WhatsApp messages?",), "es": ("¿qué permisos nos ha dado Carmen?",)}),
    tool("customer.customer.update", "Updates a customer's card, by its id or its exact name, phone or email: only "
         "the fields sent change.", input=takes("id", "customer", "name", "email", "phone", "address", "notes")),
    tool("pricing.price_list.update", "Change a price list, named by its id, code or name: only the fields sent "
         "(code, name, currency, first and last day).",
         input=takes("id", "price_list", "code", "name", "currency", "valid_from", "valid_until")),
    tool("sale.sale.get", "Get a sale by its id or its number: header, lines with their VAT, tenders, what was "
         "refunded and, if voided, why.", "query", input=takes("sale_id", "sale"),
         asks={"en": ("what was on the last ticket?",), "es": ("enséñame la venta 20261014-0007",)}),
    tool("sale.sale.issue_documents", "Issue now the fiscal documents of a sale (by its id or number) that wait "
         "because Invoicing could not issue them in the charge, the void or a refund.", input=takes("sale_id", "sale"),
         asks={"en": ("issue the invoice that got stuck for sale 12",),
               "es": ("emite ya la factura pendiente de la venta 12",)}),
    tool("sale.sale.print", "Print a sale's receipt (or its full invoice) again on the receipt printer, by the sale's "
         "id or number.", input=takes("sale_id", "sale", "duplicate"),
         asks={"en": ("reprint the receipt of sale 7",), "es": ("vuelve a imprimir la factura de esa venta",)}),
    tool("sale.sale.refund", "Refund a charged sale (by its id or number), whole or in part, with a mandatory reason.",
         input=takes("sale_id", "sale", "reason", "note", "lines"),
         asks={"en": ("refund the last sale",), "es": ("devuélvele el dinero de la última venta",)}),
    tool("sale.sale.void", "Void a charged sale (by its id or number) with a mandatory reason, before any money went "
         "back.", input=takes("sale_id", "sale", "reason"),
         asks={"en": ("void the last sale, I charged it twice",),
               "es": ("anula la última venta, la cobré dos veces",)}),
    tool("sale.refund.options", "Refund options: what a sale can still give back, for each tender and each line.",
         "query", input=takes("sale_id", "sale"),
         asks={"en": ("how much can I still give back on that sale?",),
               "es": ("¿cuánto se puede devolver todavía de esa venta?",)}),
    tool("inventory.product.set_sold_out", "Mark a product sold out (the till stops offering it, it stays active) or "
         "put it back on sale, named by its id, SKU or name.", input=takes("id", "product", "sold_out"),
         asks={"en": ("put the coffee back on sale",), "es": ("vuelve a poner a la venta el café",)}),
    tool("whatsapp_inbox.message.send", "Sends a WhatsApp message to a customer: free text within 24 hours of the "
         "customer's last message, otherwise an approved template with its variables.",
         input=takes("id", "to", "conversation", "template", "text"),
         asks={"en": ("write to Jorge on WhatsApp that we open at 9",),
               "es": ("escríbele a Jorge por WhatsApp que abrimos a las 9",)}),
    tool("whatsapp_inbox.message.notify", "Tells a customer something by WhatsApp, only in the live conversation of "
         "exactly that international number. What an automation is granted to write to a customer.",
         input=takes("phone", "template", "text"),
         asks={"en": ("let Nuria know on WhatsApp that her order is ready",),
               "es": ("manda un aviso por WhatsApp a Nuria: ya puede recoger su pedido",)}),
    tool("whatsapp_inbox.message.get", "One WhatsApp message by its id (the one an automation started on): what it "
         "says, who said it and when.", "query", input=takes("id"),
         asks={"en": ("what did that WhatsApp message say and when did it arrive?",),
               "es": ("abre el mensaje que acaba de mandar Nuria",)}),
    tool("whatsapp_inbox.template.create", "Creates a WhatsApp message template and sends it to Meta for review.",
         input=takes("category", "header", "body", "footer", "buttons", "name", "language"),
         asks={"en": ("create a WhatsApp template to remind appointments",),
               "es": ("crea una plantilla de WhatsApp para recordar citas",)}),
]


def offered(asked: str, language: str) -> list[str]:
    return ranked([*AUTOMATIONS, *OTHERS, *NOISE], asked, language)


@pytest.mark.parametrize(
    ("said", "language"),
    [
        ("permite a Bienvenida leer la venta", "es"),
        ("permítele a Bienvenida leer la venta", "es"),
        ("concede a Bienvenida leer la venta", "es"),
        ("dale permiso a la de reseñas para mandar WhatsApp", "es"),
        ("allow Welcome to read the sale", "en"),
        ("grant the reviews one permission to send WhatsApp", "en"),
    ],
)
def test_letting_something_do_an_action_asks_to_grant(said, language):
    assert "grant" in assistant.asked([said]).verbs


def test_the_permission_given_is_still_named():
    """As the name is in «cambia el nombre», the permission is what «dale permiso» gives."""
    concepts = assistant.asked(["dale permiso a la de reseñas para mandar WhatsApp"]).concepts
    assert any(assistant.stem("permisos") in concept for concept in concepts)


@pytest.mark.parametrize(
    ("asked", "language"),
    [
        ("activa Bienvenida ya que tiene sus permisos", "es"),
        ("turn on Welcome now that it has its permissions", "en"),
    ],
)
def test_turning_on_an_automation_named_by_its_name_offers_its_switch_first(asked, language):
    names = offered(asked, language)
    assert names[0] == "flow.flow.set_enabled", names[:5]


@pytest.mark.parametrize(("asked", "language"), [("desactiva Bienvenida", "es"), ("turn off Welcome", "en")])
def test_pausing_it_offers_the_same_switch_before_its_other_tools(asked, language):
    """``set_enabled`` takes whether it is on: it turns off too."""
    names = offered(asked, language)
    assert "flow.flow.set_enabled" in names, names[:8]
    ahead = names[: names.index("flow.flow.set_enabled")]
    assert not [name for name in ahead if name.startswith("flow.flow.")], ahead


@pytest.mark.parametrize(
    ("asked", "language"),
    [
        ("renombra Bienvenida como «Primera visita»", "es"),
        ("rename Welcome to «First visit»", "en"),
    ],
)
def test_renaming_an_automation_named_by_its_name_offers_the_change_that_takes_its_name_first(asked, language):
    names = offered(asked, language)
    assert names[0] == "flow.flow.update", names[:5]


@pytest.mark.parametrize(
    ("asked", "language"),
    [
        ("permite a Bienvenida leer la venta", "es"),
        ("allow Welcome to read the sale", "en"),
    ],
)
def test_letting_an_automation_named_by_its_name_read_offers_its_permissions_first(asked, language):
    names = offered(asked, language)
    assert names[0] == "flow.flow.grant", names[:5]


@pytest.mark.parametrize(
    ("asked", "language"),
    [
        ("dale permiso a la de reseñas para mandar WhatsApp", "es"),
        ("grant the reviews one permission to send WhatsApp", "en"),
    ],
)
def test_a_permission_to_send_whatsapp_offers_the_grants_first(asked, language):
    """«La de reseñas» may be a customer's consent to WhatsApp or an automation: both grants come before the rest."""
    names = offered(asked, language)
    assert set(names[:2]) == {"flow.flow.grant", "customer.consent.grant"}, names[:5]


DEVICES = [
    tool("base.device.rename", "Names a device of the hub after its place («Bar», «Kitchen»).",
         input=takes("id", "name")),
    tool("printing.device.update", "Change the name and the printers of a device set up to print.",
         input=takes("id", "name", "printers")),
    tool("printing.device.retire", "Retire a device set up to print: its jobs go back to the queue."),
    *NOISE,
]


@pytest.mark.parametrize(
    ("asked", "language"), [("renombra esta tablet como Barra", "es"), ("rename this tablet to Bar", "en")]
)
def test_the_tool_that_renames_comes_before_a_change_that_takes_a_name(asked, language):
    names = ranked(DEVICES, asked, language)
    assert names[:2] == ["base.device.rename", "printing.device.update"], names[:4]
