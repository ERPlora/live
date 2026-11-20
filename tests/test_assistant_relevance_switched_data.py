"""What a switch changes when no tool does it: a datum a write takes, only when it is what the switch turns on or off,
never one named in passing in what is said around it (ERPlora/live#76)."""

import pytest
from ninja import Schema

from live import assistant
from live.assistant.ranking import _one_app_switched
from tests.assistant_catalogue import CHECK, NOISE, ranked, tool


class LabelIn(Schema):
    order: str
    label: str


class DiscountIn(Schema):
    order: str
    percent: int


class GroupIn(Schema):
    name: str | None = None
    order: int | None = None


GOING_LIVE = "verifactu.config.go_live"
#: Going live with VeriFactu, as the Hub says it, beside the writes that take a check (its ``order``, a «cuenta» in the
#: Hub) and one that takes a place in a list (its ``order`` too).
CHECKS_AND_GOING_LIVE = [
    tool(
        GOING_LIVE,
        "Go live: from now on every VeriFactu record goes to the real AEAT. It needs a route ready for production (the "
        "own valid certificate, or ERPlora's approved signed authorisation) and an active ERPlora account.",
        asks={
            "es": ("con la autorización firmada, pasa al envío real a Hacienda",
                   "quiero remitir de verdad a la AEAT a partir de ahora"),
            "en": ("file for real with the AEAT from now on", "with the signed authorisation, take VeriFactu out of testing"),
        },
    ),
    tool("sale.order.set_label", "Puts a label on an open check.", input=LabelIn),
    tool("sale.order.set_discount", "Puts a discount on an open check.", input=DiscountIn),
    tool("customer.group.update", "Changes a customer group: its name and its place in the list.", input=GroupIn),
]


@pytest.mark.parametrize(
    ("asked", "language"),
    [
        ("activa el envío real a la AEAT a partir de ahora, comprobando antes que la cuenta y la autorización estén "
         "listas", "es"),
        ("turn on real filing with the AEAT from now on, checking first that the account and the authorisation are "
         "ready", "en"),
    ],
)
def test_a_check_named_in_passing_is_no_datum_the_switch_changes(asked, language):
    """What is checked first is not what is turned on: the writes that take a check go after going live."""
    assert ranked(CHECKS_AND_GOING_LIVE, asked, language, synonyms=CHECK)[0] == GOING_LIVE


class StockSettingsIn(Schema):
    allow_sell_without_stock: bool | None = None
    low_stock_threshold: int | None = None
    track_stock: bool | None = None


STOCK_SETTINGS = [
    tool("inventory.config.update", "Change the inventory settings: allow selling without stock, the default low-stock "
         "threshold and whether stock is tracked.", input=StockSettingsIn),
    tool("base.app.disable", "Turns off one of this business's apps: it leaves everyone's menu and its screens."),
    tool("pricing.rule.deactivate", "Turns off an automatic discount rule."),
]


@pytest.mark.parametrize("asked", ["desactiva el control de stock", "desactiva las alertas de stock bajo"])
def test_what_is_turned_off_is_said_with_what_it_is_of(asked):
    """«De stock» says what is turned off is of the stock, in the same sentence: the settings that take it change it."""
    assert ranked(STOCK_SETTINGS, asked, "es")[0] == "inventory.config.update"


class PreferencesIn(Schema):
    language: str | None = None
    hub_alerts: bool | None = None


ALERTS = [
    tool("accounts.preferences.update", "Changes the account's language or alerts of its businesses.",
         input=PreferencesIn),
    tool("hubs.business.notify_people", "Sends a notice to every person of a business."),
    tool("hubs.business.update", "Changes the name or time zone of a business."),
]


@pytest.mark.parametrize(
    ("asked", "language"),
    [
        ("turn off the alerts, all the alerts from my businesses", "en"),
        ("desactiva los avisos, todos los avisos de mis negocios", "es"),
        ("desactiva los avisos, comprobando que no llegue ningún aviso a mis negocios", "es"),
        ("turn off the alerts, making sure no alert reaches my businesses", "en"),
        # With only a pronoun before the comma, what follows it is what is turned off.
        ("desactívalos ya, los avisos", "es"),
        ("turn them off now, the alerts", "en"),
    ],
)
def test_what_is_turned_off_said_again_after_the_comma_is_still_what_it_changes(asked, language):
    """The alerts said after the comma, again, for a pronoun or in what is checked, are still what is turned off: the
    preferences that take them change it."""
    assert ranked(ALERTS, asked, language)[0] == "accounts.preferences.update"


class SoldOutIn(Schema):
    product: str
    sold_out: bool


class RushIn(Schema):
    ticket: str
    rush: bool


class SaleSettingsIn(Schema):
    ticket_footer: str | None = None
    allow_discount: bool | None = None


#: The Sales app's switches beside the Hub's writes that take what «las ventas» names: marking a product sold out (or
#: back on sale), rushing a kitchen ticket and the sales' settings, which take the ticket's footer.
SALES_AND_WHAT_THEY_NAME = [
    tool("base.app.disable", "Turns off one of this business's apps: it leaves everyone's menu and its screens."),
    tool("base.app.enable", "Turns on one of this business's apps, with the apps it needs."),
    tool(
        "inventory.product.set_sold_out",
        "Mark a product sold out (the till stops offering it, it stays active) or put it back on sale.",
        input=SoldOutIn,
        asks={"en": ("mark the Tea as sold out for today", "put the coffee back on sale"),
              "es": ("marca el té con hielo como agotado", "vuelve a poner a la venta el café")},
    ),
    tool("kitchen.ticket.set_rush", "Rush a ticket that is being cooked, or take the rush away.", input=RushIn),
    tool("sale.settings.update", "Change how the sales work: the ticket's footer, the discounts allowed.",
         input=SaleSettingsIn),
    tool("sale.sale.list", "Lists the sales of a day.", "query"),
    tool("base.app.list", "Lists this business's apps, on or off.", "query"),
    tool("staff.shift.list", "Lists the shifts of the staff.", "query"),
    *NOISE,
]
SALES_APPS = {"sale": "ventas sales tpv", "kitchen": "cocina kitchen comandas tickets", "inventory": "inventario"}
#: The Hub's own words: in English a ticket is also a sale, and «desactiva» names a deactivation.
SALES_WORDS = (("ticket", "tique", "recibo", "receipt", "sale"), ("desactiva", "desactivar", "deactivate"))


def sales_apps(label: str, language: str) -> frozenset[str]:
    return frozenset(assistant.stems(SALES_APPS.get(label, label)))


def sales_ranked(asked: str, language: str) -> list[str]:
    return ranked(SALES_AND_WHAT_THEY_NAME, asked, language, app_words=sales_apps, synonyms=SALES_WORDS)


@pytest.mark.parametrize(
    ("asked", "language", "first"),
    [
        ("desactiva las ventas", "es", "base.app.disable"),
        ("apaga las ventas", "es", "base.app.disable"),
        ("activa las ventas", "es", "base.app.enable"),
        ("turn off the sales", "en", "base.app.disable"),
        ("switch off the sales", "en", "base.app.disable"),
        ("turn the sales off", "en", "base.app.disable"),
        ("turn on the sales", "en", "base.app.enable"),
        ("desactiva las ventas, ya no las usamos", "es", "base.app.disable"),
        ("vuelve a activar las ventas", "es", "base.app.enable"),
        # Whom it is for (``Asked.direct``) is no other thing switched with it.
        ("activa las ventas para el turno de noche", "es", "base.app.enable"),
        ("turn on the sales for the night shift", "en", "base.app.enable"),
    ],
)
def test_an_app_switched_by_its_name_comes_before_the_writes_that_take_what_it_names(asked, language, first):
    """«Desactiva las ventas» turns the Sales app off: the app named by its name is what the switch turns off, not a
    product's «sold out» nor a datum a write takes (ERPlora/live#77: marking a product sold out came first in Spanish,
    and in English rushing a kitchen ticket and the sales' settings, as a ticket is also a sale)."""
    names = sales_ranked(asked, language)
    assert names[0] == first, names[:4]


@pytest.mark.parametrize(
    ("asked", "language", "first"),
    [
        ("mark the coffee as sold out", "en", "inventory.product.set_sold_out"),
        ("the croissants are sold out, stop offering them", "en", "inventory.product.set_sold_out"),
        ("we've run out of custard", "en", "inventory.product.set_sold_out"),
        ("marca el café como agotado", "es", "inventory.product.set_sold_out"),
        ("lista las ventas", "es", "sale.sale.list"),
    ],
)
def test_sold_out_still_marks_a_product_and_the_sales_listed_are_no_app(asked, language, first):
    """«Sold out» (no stock left) still marks a product so, as running out of it does; the sales listed are the sales,
    not the list of apps: an app is named for its switch only by a switch."""
    names = sales_ranked(asked, language)
    assert names[0] == first, names[:4]


#: Stopping or going back to selling a product said by its name, with a switch too («desactiva la venta del café»):
#: what marking it sold out or back on sale does, never the Sales app's switch (ERPlora/live#77).
SELLING_A_PRODUCT = [
    ("deja de vender el café", "es"), ("quita el café de la venta", "es"), ("que no se venda más el gazpacho hoy", "es"),
    ("el café ya no está a la venta", "es"), ("vuelve a vender el café", "es"), ("pon el café otra vez a la venta", "es"),
    ("stop selling the coffee", "en"), ("take the coffee off sale", "en"), ("start selling the coffee again", "en"),
    ("the coffee is back on sale", "en"), ("put the tea on sale again", "en"),
    ("desactiva la venta del café", "es"), ("apaga la venta de cruasanes", "es"), ("activa la venta del gazpacho", "es"),
    ("desactiva las ventas del café", "es"), ("desactiva la venta de este producto", "es"),
    ("turn off sales of the coffee", "en"), ("turn off the sales of the coffee", "en"), ("turn off coffee sales", "en"),
    ("turn off sales of this product", "en"),
]


@pytest.mark.parametrize(("asked", "language"), SELLING_A_PRODUCT)
def test_stopping_or_going_back_to_selling_a_product_named_marks_it(asked, language):
    """«Deja de vender el café» and «desactiva la venta del café» stop selling the coffee, and «vuelve a vender el café»
    sells it again: the sales of a product, not the Sales app named alone."""
    names = sales_ranked(asked, language)
    assert names[0] == "inventory.product.set_sold_out", names[:4]


def test_an_app_named_beside_another_thing_is_not_switched_alone():
    """«En la cocina, apaga la impresora» names the kitchen and the printer: no app is what the switch turns off alone,
    although the kitchen is no thing of the catalogue."""
    kitchen, printer = assistant._concept("cocina"), assistant._concept("impresora")
    said = assistant.asked(["en la cocina, apaga la impresora"])
    assert frozenset({printer}) in said.switched  # positive control: the printer alone is what is switched
    assert not _one_app_switched(said, frozenset({kitchen, printer}), frozenset(printer), frozenset())


class KitchenDisplayIn(Schema):
    show_timer: bool | None = None
    sound_enabled: bool | None = None
    sound_volume: int | None = None


class DrawerIn(Schema):
    enable_cash_register: bool | None = None
    require_blind_count: bool | None = None
    auto_close_enabled: bool | None = None


#: The settings of the Hub's apps that a person says with the app's name («stock», «kitchen», «arqueo»), beside the
#: apps' switches.
SETTINGS_SAID_WITH_THEIR_APP = [
    tool("base.app.disable", "Turns off one of this business's apps: it leaves everyone's menu and its screens."),
    tool("base.app.enable", "Turns on one of this business's apps, with the apps it needs."),
    tool("inventory.config.update", "Change the inventory settings: allow selling without stock, the default low-stock "
         "threshold and whether stock is tracked.", input=StockSettingsIn,
         asks={"en": ("stop tracking stock",), "es": ("no quiero controlar el stock",)}),
    tool("kitchen.settings.update", "Change the kitchen display settings: the clock, the sound and its volume.",
         input=KitchenDisplayIn, asks={"en": ("mute the display",), "es": ("pon más bajo el sonido de la pantalla",)}),
    tool("cash_register.settings.update", "Change how the drawer works: cash register on, blind count, daily "
         "auto-close.", input=DrawerIn, asks={"en": ("turn on the blind count",), "es": ("activa el arqueo ciego",)}),
    tool("attendance.entry.list", "Lists the clock-ins of the staff.", "query"),
    *NOISE,
]
APPS_OF_THE_SETTINGS = {"inventory": "inventario inventory stock", "kitchen": "cocina kitchen",
                        "cash_register": "caja arqueo cash register", "attendance": "control horario fichaje"}


def apps_of_the_settings(label: str, language: str) -> frozenset[str]:
    return frozenset(assistant.stems(APPS_OF_THE_SETTINGS.get(label, label)))


@pytest.mark.parametrize(
    ("asked", "language", "first"),
    [
        ("turn off stock control", "en", "inventory.config.update"),
        ("turn off the kitchen sound alert", "en", "kitchen.settings.update"),
        ("activa el arqueo ciego", "es", "cash_register.settings.update"),
        # What it is of, after «de», is named too: «control» alone would be the clock-ins' app.
        ("desactiva el control de stock", "es", "inventory.config.update"),
        ("turn off the kitchen", "en", "base.app.disable"),
        ("apaga la cocina", "es", "base.app.disable"),
    ],
)
def test_an_app_is_what_a_switch_turns_off_only_when_named_alone(asked, language, first):
    """«Turn off stock control» and «desactiva el control de stock» turn off a setting of the stock, not an app: only an
    app named alone by its name, with no other app nor thing named («turn off the kitchen»), is what the switch turns
    off."""
    names = ranked(SETTINGS_SAID_WITH_THEIR_APP, asked, language, app_words=apps_of_the_settings)
    assert names[0] == first, names[:4]


def test_what_is_asked_and_the_words_read_once_rank_as_lists():
    """``relevant`` takes any iterable: read once, as a generator is, they rank as the lists they hold."""
    asked = "activa el envío real a la AEAT, comprobando antes que la cuenta y la autorización estén listas"
    tools = {op.name: op for op in CHECKS_AND_GOING_LIVE}
    once = assistant.relevant(tools, (text for text in [asked]), "es", synonyms=(group for group in CHECK))
    assert [op.name for op in once] == ranked(CHECKS_AND_GOING_LIVE, asked, "es", synonyms=CHECK)
