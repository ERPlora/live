"""What a switch changes when no tool does it: a datum a write takes, only when it is what the switch turns on or off,
never one named in passing in what is said around it (ERPlora/live#76)."""

import pytest
from ninja import Schema

from live import assistant
from tests.assistant_catalogue import CHECK, ranked, tool


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


def test_what_is_asked_and_the_words_read_once_rank_as_lists():
    """``relevant`` takes any iterable: read once, as a generator is, they rank as the lists they hold."""
    asked = "activa el envío real a la AEAT, comprobando antes que la cuenta y la autorización estén listas"
    tools = {op.name: op for op in CHECKS_AND_GOING_LIVE}
    once = assistant.relevant(tools, (text for text in [asked]), "es", synonyms=(group for group in CHECK))
    assert [op.name for op in once] == ranked(CHECKS_AND_GOING_LIVE, asked, "es", synonyms=CHECK)
