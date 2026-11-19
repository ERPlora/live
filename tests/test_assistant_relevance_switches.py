"""What a turn offers when it approves, confirms or switches something on or off: an app, a rule, a payment method,
an automation or the theme."""

import pytest
from ninja import Schema
from pydantic import create_model

from live import assistant
from tests.assistant_catalogue import APPROVED_OR_SWITCHED, HUB_WORDS, NOISE, SWITCHING_OFF, SWITCHING_ON, ranked, tool


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
        ("the lights will turn the bookings on at nine", set()),
    ],
)
def test_a_command_or_a_request_with_will_still_asks(said, verbs):
    """What «will» leaves out is the verb right after it, one said in words too («will turn on»): a command asks, and
    «will you…?» is a request."""
    assert assistant.asked([said]).verbs == verbs


@pytest.mark.parametrize(
    ("apart", "in_a_row"),
    [
        ("turn the bookings off", "turn off the bookings"),
        ("switch the kitchen app on", "switch on the kitchen app"),
        ("Turn the appointment reminders off", "turn off the appointment reminders"),
        ("can you switch the bookings module off? Nobody uses it.",
         "can you switch off the bookings module? Nobody uses it."),
        ("turn the online bookings off for the weekend", "turn off the online bookings for the weekend"),
        ("turn the sale on table 4 off", "turn off the sale on table 4"),
        ("turn the bookings off and switch the kitchen app on", "turn off the bookings and switch on the kitchen app"),
    ],
)
def test_a_switch_said_around_what_it_switches_reads_as_said_in_a_row(apart, in_a_row):
    """English puts what «turn off» and «switch on» switch between the verb and its particle as often as after them:
    «turn the bookings off» asks and names what «turn off the bookings» does, and «turn» names no shift (ERPlora/live#69;
    before, it asked for nothing and its «turn» was the «turno»)."""
    heard = assistant.asked([apart])
    assert heard == assistant.asked([in_a_row])
    assert not any("turn" in concept or "off" in concept for concept in heard.concepts), heard.concepts


@pytest.mark.parametrize(
    ("said", "actions"),
    [
        ("turn them back on", SWITCHING_ON),
        ("turn it off", SWITCHING_OFF),
        # What may come after the particle and is no thing it is said of: another clause, when, how or a request.
        ("turn the bookings off and close the till", SWITCHING_OFF),
        ("switch the kitchen app on then print the menu", SWITCHING_ON),
        ("switch the alerts on also on Sundays", SWITCHING_ON),
        ("turn the bookings off but keep the waiting list", SWITCHING_OFF),
        ("turn the reminders off or send them later", SWITCHING_OFF),
        ("turn the bookings off so nobody books on Monday", SWITCHING_OFF),
        ("switch the kitchen app on if it is off", SWITCHING_ON),
        ("turn the reminders off when the shop is closed", SWITCHING_OFF),
        ("switch the bookings off while we are on holiday", SWITCHING_OFF),
        ("turn the kitchen app off because we close the kitchen", SWITCHING_OFF),
        ("turn the bookings off until Monday", SWITCHING_OFF),
        ("switch the reminders off till next week", SWITCHING_OFF),
        ("switch the kitchen app on at nine", SWITCHING_ON),
        ("turn the bookings off from tomorrow", SWITCHING_OFF),
        ("switch the reminders on in the evening", SWITCHING_ON),
        ("turn the bookings off on Sundays", SWITCHING_OFF),
        ("turn the reminders off during August", SWITCHING_OFF),
        ("switch the bookings off since nobody uses them", SWITCHING_OFF),
        ("turn the bookings off before the holidays", SWITCHING_OFF),
        ("switch the kitchen app on after lunch", SWITCHING_ON),
        ("switch the reminders on by default", SWITCHING_ON),
        ("turn the kitchen app on now", SWITCHING_ON),
        ("switch the reminders on again", SWITCHING_ON),
        ("turn the bookings off please", SWITCHING_OFF),
        ("switch the online bookings off today", SWITCHING_OFF),
        ("turn the kitchen app off tonight", SWITCHING_OFF),
        ("switch the bookings on tomorrow", SWITCHING_ON),
        ("turn the reminders off too", SWITCHING_OFF),
        ("switch the kitchen app on already", SWITCHING_ON),
        ("turn the bookings off first", SWITCHING_OFF),
        ("switch the reminders back on later", SWITCHING_ON),
        ("turn the kitchen app on right now", SWITCHING_ON),
    ],
)
def test_a_switch_said_apart_from_its_particle_asks_for_its_action(said, actions):
    """«Turn … off», «switch … on»: the particle after what is switched asks what it asks said in a row, at the end of
    the sentence or before a word that cannot be what it is said of (ERPlora/live#69)."""
    assert actions <= assistant.asked([said]).verbs


@pytest.mark.parametrize(
    "said",
    [
        "turn the page",
        "switch tables",
        "switch me to English",
        "switch the kitchen printer to 58 mm paper",
        # An «on» or an «off» before what it is said of says where or when, not what is switched.
        "switch the order on table 4 to table 6",
        "switch Ana's shift on Monday with Marta",
        "switch the wine on the bill for a beer",
        # Nor is a particle of another command.
        "switch the order to table 6 and leave the lights on",
        # Nor one after a verb that has its own particle right after it («turn down» rejects).
        "turn down Ana's request to take the afternoon off",
        "turn down Ana's pending time off",
        "turn up the music they put on",
        "turn over the bill she signed off",
        "switch out the printer that keeps cutting off",
        "switch around the shifts Ana is on",
        "switch back the menu we had on",
        "turn away the guests we can't take on",
        "it is Ana's turn",
        # Nor the «off» of a leave: «time off», «a day off».
        "switch Ana's time off",
        "switch Ana's day off",
        "switch Marta's days off",
        "switch Ana's night off",
        "switch Pablo's week off",
    ],
)
def test_a_turn_or_a_switch_with_no_particle_of_its_own_switches_nothing(said):
    """«Turn the page», «switch tables» or «switch the order on table 4 to table 6» turn nothing on or off: only the
    verb's own particle makes it a switch (ERPlora/live#69)."""
    assert assistant.asked([said]).verbs.isdisjoint(SWITCHING_ON | SWITCHING_OFF)


def test_a_switch_said_in_a_row_has_no_other_particle_later():
    """A verb with its particle right after it has its own: «turn off the screens we left on» turns them off, and the
    «on» of «left on» turns nothing on (ERPlora/live#69)."""
    assert assistant.asked(["turn off the screens we left on"]).verbs == SWITCHING_OFF


def test_a_name_someone_will_put_is_not_put_by_the_verb():
    """«I'll change on the price list its name» renames nothing either: what someone will do puts no name."""
    assert "rename" not in assistant.asked(["I'll change on this list its name"]).verbs
    assert "rename" in assistant.asked(["change on this list its name"]).verbs


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
        # With what is switched between the verb and its particle (ERPlora/live#69).
        ("turn the summer price list off", "en", "pricing.price_list.deactivate"),
        ("switch the summer price list on again", "en", "pricing.price_list.activate"),
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
        ("turn the sales off", "en", "base.app.disable"),
        ("switch the sales on again", "en", "base.app.enable"),
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
        # With what is switched between the verb and its particle (ERPlora/live#69).
        ("turn the appointment reminders off", {concepts_of("appointment", "reminders")}),
        ("switch the reminders of the bookings on", {concepts_of("reminders")}),
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
