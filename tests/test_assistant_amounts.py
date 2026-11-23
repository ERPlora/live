"""The amounts of a tool's result, told in their currency (``run_tool``'s ``money``).

An amount travels in the minor unit of its currency (``json_schema_extra={"money": True}``: 360 is 3.60 €), and the
model, which never sees the result's schema, repeated it as it read it: the assistant told a bar «360,00 €» for the
3.60 € its customers had spent. Given ``money``, every amount the result's schema marks reaches the model as the
screens write it, in the currency its object names (``currency``, with the ``currency_decimals`` it answers) or else the
business's, with the decimals ``money`` gives for it; everything else reads as ``model_dump_json`` writes it.
"""

import datetime as dt
import json
from zoneinfo import ZoneInfo

from live import assistant
from ninja import Field, Schema

from tests.test_assistant import ctx, op

MONEY = {"money": True}
#: The decimals of each currency, as the project knows them (ISO 4217).
DECIMALS = {"EUR": 2, "ISK": 0, "JPY": 0, "KWD": 3}


def euros(named: str | None) -> tuple[str, int]:
    currency = named or "EUR"
    return currency, DECIMALS[currency]


class LineOut(Schema):
    label: str
    unit_price: int = Field(json_schema_extra=MONEY)
    quantity: int


class PriceListOut(Schema):
    currency: str
    price: int = Field(json_schema_extra=MONEY)


class InvoiceOut(Schema):
    currency: str
    currency_decimals: int
    total_amount: int = Field(json_schema_extra=MONEY)
    lines: list[LineOut]


class FiguresOut(Schema):
    total: int
    total_revenue: int | None = Field(json_schema_extra=MONEY)
    refunded: int | None = Field(json_schema_extra=MONEY)
    difference: int = Field(json_schema_extra={**MONEY, "signed": True})
    spent_cents: int
    closed: bool
    at: dt.datetime
    lines: list[LineOut]
    invoices: list[InvoiceOut]
    price_list: PriceListOut


FIGURES = {
    "total": 4,
    "total_revenue": 360,
    "refunded": None,
    "difference": -150,
    # A whole number its schema does not mark is no amount, whatever its name says.
    "spent_cents": 360,
    "closed": True,
    "at": dt.datetime(2026, 11, 22, 15, 18, tzinfo=dt.UTC),
    "lines": [{"label": "Café", "unit_price": 150, "quantity": 2}],
    "invoices": [
        {"currency": "JPY", "currency_decimals": 0, "total_amount": 1250, "lines": [{"label": "Té", "unit_price": 1250, "quantity": 1}]},
        {"currency": "KWD", "currency_decimals": 3, "total_amount": 1250, "lines": []},
        # The decimals it answers, even where the currency's own say others: as its card writes it.
        {"currency": "ISK", "currency_decimals": 2, "total_amount": 1250, "lines": []},
    ],
    # A currency named without its decimals: the project says them.
    "price_list": {"currency": "JPY", "price": 1999},
}


def read(**kwargs) -> dict:
    figures = op("testapp.probe.figures", kind="query", output=FiguresOut, fn=lambda ctx, data: FIGURES)
    outcome = assistant.run_tool(ctx("testapp.manage"), figures, "{}", **kwargs)
    assert outcome.outcome == "ok"
    return json.loads(outcome.content)


def test_an_amount_reaches_the_model_in_its_currency_never_in_its_minor_unit():
    told = read(money=euros)
    assert told["total_revenue"] == "3.60 EUR"
    assert told["difference"] == "-1.50 EUR"
    assert told["lines"][0]["unit_price"] == "1.50 EUR"


def test_an_amount_inside_an_object_that_names_its_currency_is_in_that_one():
    told = read(money=euros)
    assert told["invoices"][0]["total_amount"] == "1250 JPY"
    assert told["invoices"][0]["lines"][0]["unit_price"] == "1250 JPY"
    assert told["invoices"][1]["total_amount"] == "1.250 KWD"
    assert told["invoices"][2]["total_amount"] == "12.50 ISK"
    assert told["price_list"]["price"] == "1999 JPY"


def test_only_the_amounts_change():
    told = read(money=euros)
    assert (told["total"], told["spent_cents"], told["closed"], told["refunded"]) == (4, 360, True, None)
    assert told["lines"][0]["quantity"] == 2
    assert told["invoices"][0]["currency_decimals"] == 0
    assert told["at"] == "2026-11-22T15:18:00Z"


def test_on_a_clock_and_in_a_currency_at_once():
    told = read(money=euros, zone=ZoneInfo("Europe/Madrid"))
    assert (told["at"], told["total_revenue"]) == ("2026-11-22T16:18:00+01:00", "3.60 EUR")


def test_without_a_currency_a_result_reads_as_its_operation_wrote_it():
    assert read() == json.loads(FiguresOut.model_validate(FIGURES).model_dump_json())
