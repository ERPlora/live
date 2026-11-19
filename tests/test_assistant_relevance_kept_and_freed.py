"""What a turn offers when it empties, assigns, archives, redeems, holds or releases something: a cart, the routing of
the kitchen, a professional's services, a voucher's sessions or a table set aside."""

import pytest

from live import assistant
from tests.assistant_catalogue import NOISE, ranked, tool


#: A write of each of those things that does nothing asked comes first by name: what the verb asks has to earn its place.
FIRST_BY_NAME = [
    tool(f"{name}.aaa", f"Does it to {what}.")
    for name, what in (
        ("cart_checkout.cart", "a shopping cart"), ("kitchen.routing", "the routing of the kitchen"),
        ("service.assignment", "a professional's assignment to a service"), ("service.service", "a service"),
        ("service.grant", "a voucher sold"), ("service.session", "a session of a voucher"), ("table.hold", "a table"),
    )
]
#: The Hub's tools of those things, beside the reads and the other writes of the same things.
KEPT_AND_FREED = [
    *FIRST_BY_NAME,
    tool("cart_checkout.cart.clear", "Empty an active shopping cart: every line goes, the cart stays."),
    tool("cart_checkout.cart.create", "Create a shopping cart for a customer."),
    tool("cart_checkout.cart.delete", "Delete a shopping cart in any status."),
    tool("cart_checkout.cart.get", "Get one shopping cart with all its lines.", "query"),
    tool("cart_checkout.cart.list", "List the shopping carts with their status.", "query"),
    tool("kitchen.routing.clear", "Take away where a product or a category goes: from now on it goes by its category."),
    tool("kitchen.routing.list", "Which products and categories go to which station.", "query"),
    tool("kitchen.routing.set", "Send a product or a category of the catalogue to a station."),
    tool("service.assignment.assign", "Assign a professional of Staff to a service, with their own duration and price."),
    tool("service.assignment.list", "List who performs each service.", "query"),
    tool("service.assignment.remove", "Remove a professional from a service: they no longer perform it."),
    tool("service.assignment.update", "Change who performs a service: their own duration or price."),
    tool("service.service.archive", "Archive a service: it is no longer offered nor bookable; its history stays."),
    tool("service.service.create", "Create a service of the catalogue with its duration and price."),
    tool("service.service.list", "List the services of the catalogue.", "query"),
    tool("service.service.update", "Change a service: its name, duration or price."),
    tool("service.grant.create", "Grant (sell) a voucher of the catalogue to a customer."),
    tool("service.grant.list", "List the vouchers sold, the ones a customer owns.", "query"),
    tool("service.grant.redeem", "Spend one session of a voucher sold, optionally on a service it covers."),
    tool("service.grant.void", "Void a voucher sold by mistake, with the reason."),
    tool("service.session.get", "Get one session of a voucher sold: the voucher, its owner, the service.", "query"),
    tool("service.session.hold", "Reserve one session of a customer's voucher for a line of an open check."),
    tool("service.session.release", "Give back a session held for a line that is undone."),
    tool("table.hold.place", "Set a table aside by hand for a party."),
    tool("table.hold.release", "Release a table set aside: its name is forgotten."),
    *NOISE,
]
#: The Hub's words for these things: a «carrito» is a cart, the «enrutado» the routing, a «bono» a voucher sold and an
#: «asignación» (what one «asigna») a professional's assignment to a service.
HUB_WORDS = (
    ("cesta", "carrito", "cart", "basket"),
    ("enrutado", "enrutados", "enrutar", "enruta", "enrutamiento", "routing", "route", "routes"),
    ("bono", "bonos", "voucher", "vouchers", "grant", "grants"),
    ("asignacion", "asignaciones", "assignment", "assignments"),
)


@pytest.mark.parametrize(
    ("said", "action"),
    [
        ("vacía el carrito", "clear"),
        ("hay que vaciar la cesta de Carmen", "clear"),
        ("vacíala, que la clienta se lo ha pensado", "clear"),
        ("empty the cart", "clear"),
        ("clear Carmen's cart", "clear"),
        ("asigna a Marta la depilación", "assign"),
        ("hay que asignar los tintes a Raquel", "assign"),
        ("asígnale la depilación a Marta", "assign"),
        ("assign waxing to Marta", "assign"),
        ("archiva el servicio de tinte", "archive"),
        ("hay que archivar las permanentes", "archive"),
        ("ya no hacemos permanentes, archívalo", "archive"),
        ("archive the dye service", "archive"),
        ("canjea una sesión del bono de Ana", "redeem"),
        ("gasta una sesión del bono de Ana", "redeem"),
        ("consume una sesión del bono de Ana", "redeem"),
        ("hay que canjear una sesión del bono de Ana", "redeem"),
        ("redeem a session of Ana's voucher", "redeem"),
        ("retén la sesión de Ana", "hold"),
        ("aparta una sesión del bono de Ana", "hold"),
        ("hay que retener una sesión del bono de Ana", "hold"),
        ("hold Ana's session", "hold"),
        ("libera la sesión de Ana", "release"),
        ("suelta la sesión retenida del bono de Ana", "release"),
        ("hay que liberar la sesión de Ana", "release"),
        ("libérala, que ya no la usa", "release"),
        ("release Ana's session", "release"),
    ],
)
def test_emptying_assigning_archiving_redeeming_holding_or_releasing_is_asked(said, action):
    """Each is the action of the tools that do it (``cart_checkout.cart.clear``, ``service.assignment.assign``,
    ``service.service.archive``, ``service.grant.redeem``, ``service.session.hold``, ``service.session.release``), in
    either language, its infinitive and its pronouns too. Before, none was a verb but «asigna», only a ``set``, and the
    action was read as the thing the tool acts on."""
    assert action in assistant.asked([said]).verbs


@pytest.mark.parametrize(
    ("asked", "language", "first"),
    [
        ("vacía el carrito", "es", "cart_checkout.cart.clear"),
        ("vacía la cesta de Carmen", "es", "cart_checkout.cart.clear"),
        ("empty Carmen's shopping cart", "en", "cart_checkout.cart.clear"),
        ("borra el enrutado de los zumos", "es", "kitchen.routing.clear"),
        ("elimina el enrutado que tienen las ensaladas", "es", "kitchen.routing.clear"),
        ("quita el enrutado de los postres", "es", "kitchen.routing.clear"),
        ("clear the routing of the juices", "en", "kitchen.routing.clear"),
        ("asigna a Marta la depilación", "es", "service.assignment.assign"),
        ("asígnale la depilación a Marta", "es", "service.assignment.assign"),
        ("assign waxing to Marta", "en", "service.assignment.assign"),
        ("archiva el servicio de tinte", "es", "service.service.archive"),
        ("archive the dye service", "en", "service.service.archive"),
        ("canjea una sesión del bono de Ana", "es", "service.grant.redeem"),
        ("gasta una sesión del bono de Ana", "es", "service.grant.redeem"),
        ("redeem a session of Ana's voucher", "en", "service.grant.redeem"),
        ("retén la sesión de Ana", "es", "service.session.hold"),
        ("hold Ana's session", "en", "service.session.hold"),
        ("libera la sesión de Ana", "es", "service.session.release"),
        ("release Ana's session", "en", "service.session.release"),
    ],
)
def test_what_is_emptied_assigned_archived_redeemed_held_or_released_comes_first(asked, language, first):
    """The action asked of the thing named comes before its other writes and its reads; taking the routing away
    («borra», «quita», «elimina») is clearing it, for there is no other tool that takes it away. Before, these came
    behind the tools that only named the same thing."""
    names = ranked(KEPT_AND_FREED, asked, language, synonyms=HUB_WORDS)
    assert names[0] == first, names[:4]


@pytest.mark.parametrize(
    ("asked", "language", "first"),
    [
        ("borra el carrito de Carmen", "es", "cart_checkout.cart.delete"),
        ("delete Carmen's cart", "en", "cart_checkout.cart.delete"),
        ("quita la asignación de Marta a la depilación", "es", "service.assignment.remove"),
        ("remove Marta's assignment to waxing", "en", "service.assignment.remove"),
    ],
)
def test_deleting_a_thing_that_can_be_emptied_still_deletes_it(asked, language, first):
    """A cart deleted is deleted, not emptied: the tool that does the action asked comes before the one that does it
    said another way."""
    names = ranked(KEPT_AND_FREED, asked, language, synonyms=HUB_WORDS)
    assert names[0] == first, names[:4]
