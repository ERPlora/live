"""The lists a card says item by item (``NAMED``) when each line is all words or figures beside its words.

A person who confirms a write sees what it will save: a select field's options («Terraza, Dentro»), the value of a
custom field, the hours of a day, the products received by the names the person said («agua · 48»), what a manual
invoice bills, the dishes of a ticket, the special days of a year — never «2 items». A text is said one by one only
when its app marks it as the person's own words (``OWN_WORDS``); one without the mark is a code nobody names.
"""

import datetime as dt
import uuid
from decimal import Decimal
from typing import Annotated, Literal

import pytest
from live import assistant
from ninja import Field, Schema

from tests.test_assistant import CREATE, SpokenWords, StockIn, fields, op

OWN = {"own_words": True}
REFERS = {"refers": {"read": "testapp.probe.get", "by": "id"}}


class FieldValueIn(Schema):
    field_id: uuid.UUID = Field(json_schema_extra=REFERS)
    value: str = Field(json_schema_extra=OWN)


class IntervalIn(Schema):
    open_time: dt.time
    close_time: dt.time


class SpecialDayIn(Schema):
    date: dt.date
    name: str = Field(json_schema_extra=OWN)
    is_closed: bool = True
    intervals: list[IntervalIn] = []
    notes: str = Field("", json_schema_extra=OWN)


class InvoiceLineIn(Schema):
    description: str = Field(json_schema_extra=OWN)
    quantity: Decimal
    unit_price: int = Field(json_schema_extra={"money": True})
    tax_category: str | None = Field(None, json_schema_extra={"refers": {"read": "testapp.probe.get", "by": "key"}})
    tax_rate: Decimal | None = None


class DishIn(Schema):
    product_id: uuid.UUID | None = Field(None, json_schema_extra=REFERS)
    product: str | None = Field(None, json_schema_extra={"name_of": "product_id"})
    name: str = Field("", json_schema_extra=OWN)
    quantity: Decimal = Decimal("1")
    notes: str = Field("", json_schema_extra=OWN)


class CourseIn(Schema):
    course: Literal[1, 2]
    dish: str = Field(json_schema_extra=OWN)


class WrittenIn(Schema):
    options: list[Annotated[str, Field(json_schema_extra=OWN)]] = []
    codes: list[str] = []
    field_values: list[FieldValueIn] = []
    intervals: list[IntervalIn] = []
    special_days: list[SpecialDayIn] = []
    lines: list[InvoiceLineIn] = []
    items: list[DishIn] = []
    courses: list[CourseIn] = []


@pytest.fixture
def written():
    return op("testapp.probe.written", ai=CREATE, input=WrittenIn)


@pytest.fixture
def stock():
    return op("testapp.probe.stock", ai=CREATE, input=StockIn)


def said(write, name, items, words=None) -> tuple:
    words = SpokenWords(write, "en") if words is None else words
    shown = fields(assistant.card(write, {name: items}, words.language, words))[name]
    return shown["value"], shown.get(assistant.NAMED, False)


def test_texts_its_app_marks_as_the_persons_own_words_are_named_as_written(written):
    """A select field's options («Terraza», «Dentro») are what the person wrote: the screen says them. A list of texts
    without the mark is still a code nobody names (an automation's permissions, «sale.sale.create»)."""
    assert said(written, "options", ["Terraza", "Dentro"]) == (["Terraza", "Dentro"], True)
    assert said(written, "codes", ["sale.sale.create"]) == (["sale.sale.create"], False)


@pytest.mark.parametrize("text", ["", "   ", str(uuid.uuid4())])
def test_own_words_that_say_nothing_or_are_an_id_are_never_said(written, text):
    """Blanks show nothing, and a card never says an id: the screen says how many the list carries."""
    assert said(written, "options", ["Terraza", text])[1] is False


def test_a_line_of_a_record_and_the_words_written_beside_it_is_named(written):
    """The value of a custom field: the field by its name and what the person wrote in it, «Preferencia de mesa ·
    Terraza». A record the card cannot name would leave the words alone, as if they said which field: the screen says
    how many."""
    line = [{"field_id": str(uuid.uuid4()), "value": "Terraza"}]
    assert said(written, "field_values", line) == ([{"field_id": "Table 5", "value": "Terraza"}], True)
    assert said(written, "field_values", line, assistant.PlainWords(written, "en")) == ([{"value": "Terraza"}], False)


def test_a_line_of_moments_is_named_by_them(written):
    """The hours of a day, «12:00 · 23:30»: each one said as the person's language writes it. One that is no moment
    stays as sent, so the line is not said."""
    hours = [{"open_time": "12:00", "close_time": "23:30"}, {"open_time": "09:00", "close_time": "14:00"}]
    value, named = said(written, "intervals", hours)
    assert (value[0], named) == ({"open_time": "time:12:00", "close_time": "time:23:30"}, True)
    plain = assistant.PlainWords(written, "en")
    assert said(written, "intervals", [{"open_time": "12:00", "close_time": "23:30"}], plain)[1] is True
    assert said(written, "intervals", [{"open_time": "noon", "close_time": "23:30"}], plain)[1] is False


def test_a_moment_its_words_write_as_it_was_sent_is_still_in_words(written):
    """Spanish writes noon as «12:00», the same text the write sends: it is a moment said in words all the same, so the
    hours of a day are said, never «1 elemento»."""
    plain = assistant.PlainWords(written, "es")
    hours = [{"open_time": "12:00", "close_time": "23:30"}]
    assert said(written, "intervals", hours, plain) == (hours, True)
    assert said(written, "intervals", [{"open_time": "12:00", "close_time": "mediodía"}], plain)[1] is False
    # And one its words write though JSON writes no such date: a day without its year, as a birthday is sent.
    assert said(written, "special_days", [{"date": "--12-25", "name": "Christmas", "intervals": []}])[1] is True


def test_a_line_by_the_name_a_person_said_and_figures_beside_it_is_named(stock):
    """A reception by the names the person said, «agua · 48, cerveza · 24»: the name is said as it was, the quantity as
    a figure (a number or the text of a decimal)."""
    sent = [{"thing": "agua", "qty": "48"}, {"thing": "cerveza", "qty": 24}]
    shown = fields(assistant.card(stock, {"items": sent}, "en", SpokenWords(stock, "en")))["items"]
    assert (shown["value"], shown.get(assistant.NAMED)) == (sent, True)


def test_a_line_of_two_records_the_card_names_is_named_by_both(stock):
    """A line that names two records, one by its number, is said by both names and its figures; a record by its
    number is never one of its figures, so a line of it and a quantity is said by that record."""
    line = [{"thing_id": str(uuid.uuid4()), "table": 4, "qty": "6"}]
    shown = fields(assistant.card(stock, {"items": line}, "en", SpokenWords(stock, "en")))["items"]
    assert (shown["value"], shown.get(assistant.NAMED)) == ([{"thing_id": "Table 5", "table": "Table 5", "qty": "6"}], True)
    shown = fields(assistant.card(stock, {"items": [{"table": 4, "qty": "6"}]}, "en", SpokenWords(stock, "en")))["items"]
    assert (shown["value"], shown.get(assistant.NAMED)) == ([{"table": "Table 5", "qty": "6"}], True)


def test_a_value_of_a_closed_list_in_a_line_is_said_by_its_label_never_as_a_figure(written, monkeypatch):
    """A course of a menu by its number («1»): by the label its app gives it, as a word of its line; without one it is
    a code, never a quantity, and the line is not said."""
    monkeypatch.setattr(assistant.cards, "choice_label", lambda app, entity, name, value: {1: "Starter"}.get(value))
    assert said(written, "courses", [{"course": 1, "dish": "Salmorejo"}]) == ([{"course": "Starter", "dish": "Salmorejo"}], True)
    assert said(written, "courses", [{"course": 2, "dish": "Flan"}])[1] is False


def test_a_line_with_a_record_the_card_leaves_out_is_not_named(stock):
    """One of its two records unnamed: the line would read by the other as if it were the only one."""
    one = str(uuid.uuid4())

    class Unnamed(SpokenWords):
        def reference(self, value, prop):
            return "Table 5" if value == one else assistant.LEFT_OUT

    line = [{"thing_id": one, "table": 4, "qty": "6"}]
    shown = fields(assistant.card(stock, {"items": line}, "en", Unnamed(stock, "en")))["items"]
    assert (shown["value"], shown.get(assistant.NAMED, False)) == ([{"thing_id": "Table 5", "qty": "6"}], False)


def test_a_manual_invoice_line_is_named_by_what_it_bills_and_its_figures(written):
    """What is invoiced, its tax category by its name, its quantity, its price as money and its rate."""
    line = {"description": "Menú de cumpleaños", "quantity": "30", "unit_price": 2273, "tax_category": "food", "tax_rate": None}
    value, named = said(written, "lines", [line])
    assert value == [{"description": "Menú de cumpleaños", "quantity": "30", "unit_price": "22.73 $", "tax_category": "Table 5", "tax_rate": None}]
    assert named is True
    assert said(written, "lines", [{**line, "tax_category": None, "tax_rate": "10"}])[1] is True


def test_the_dishes_of_a_ticket_are_named_by_their_product_or_their_name(written):
    """A dish by the product's name the person said, or by what to cook when it is no product, with its quantity and
    the cook's note; its product by its id, by that product."""
    dishes = [
        {"product": "Espresso", "quantity": "2"},
        {"name": "Café con leche", "quantity": 1, "notes": "sin azúcar"},
        {"product_id": str(uuid.uuid4()), "product": "Espreso", "quantity": "1"},
    ]
    value, named = said(written, "items", dishes)
    assert value[2] == {"product_id": "Table 5", "quantity": "1"}
    assert named is True


def test_special_days_are_named_by_their_date_and_name_and_a_closed_days_hours_do_not_count(written):
    """«1 Jan 2027 · New Year's Day»: a closed day carries no hours, an empty list shows nothing, as no empty datum
    does; nor do empty notes."""
    days = [
        {"date": "2027-01-01", "name": "New Year's Day", "intervals": []},
        {"date": "2027-01-06", "name": "Epiphany", "notes": ""},
    ]
    assert said(written, "special_days", days)[1] is True


@pytest.mark.parametrize(
    "day",
    [
        {"date": "2027-01-01", "name": "New Year's Day", "is_closed": True},  # a yes or no says nothing without its name
        {"date": "2027-08-15", "name": "Assumption", "intervals": [{"open_time": "09:00", "close_time": "14:00"}]},
    ],
)
def test_a_special_day_with_a_yes_or_no_or_its_hours_is_not_named(written, day):
    """A yes or no, or a list inside the line, cannot be said beside its words without the name of its datum: the
    screen says how many the list carries, unless the project sums the line up (``ai={"summary": …}``)."""
    assert said(written, "special_days", [day])[1] is False
