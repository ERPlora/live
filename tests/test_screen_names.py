"""The values of a closed list in a tool's result, told with the names the project's screens give them (``run_tool``).

The model never sees the result's schema and repeats a code as it reads it: the Hub's assistant wrote «lead» and
«walk_in» for what a customer's card calls «Contacto» and «En el local». The result carries, once, the name of each
value its screens name, in the person's language, under the path of its datum (``SCREEN_NAMES``); the name is the one
a write's card says (``choice_label``), of the field a ``choices_of`` mark names.
"""

import json
import re
from typing import Literal

import pytest
from django.utils import translation
from live import assistant
from live.assistant import screen_names
from ninja import Field, Schema

from tests.test_assistant import ctx, op

#: The values the app's models name, by the app and the field that name them.
NAMED = {("testapp", "status"): {"open", "done", "vip"}, ("sale", "method"): {"card"}}


@pytest.fixture(autouse=True)
def labels(monkeypatch):
    """Each value named by its field and the active language, so a test sees which field and language named it; «vip»
    as the screens write it, «VIP»."""

    def label(app, entity, name, value):
        if value not in NAMED.get((app, name), ()):
            return None
        return "VIP" if value == "vip" else f"{name}:{value}@{translation.get_language()}"

    monkeypatch.setattr(screen_names, "choice_label", label)


Status = Literal["open", "done", "vip"]


class ItemOut(Schema):
    status: Status
    note: str


class FiguresOut(Schema):
    status: Status
    note: str
    total: int
    rows: list[ItemOut]
    best: ItemOut | None
    states: list[Status] = Field(json_schema_extra={"choices_of": "status"})
    method: str = Field(json_schema_extra={"choices_of": "sale.method"})
    methods: list[str] = Field(json_schema_extra={"choices_of": "sale.method"})


FIGURES = {
    "status": "open",
    "note": "open",
    "total": 3,
    "rows": [{"status": "open", "note": ""}, {"status": "done", "note": "done"}, {"status": "open", "note": "x"}],
    "best": {"status": "done", "note": ""},
    "states": ["done", "vip"],
    "method": "card",
    "methods": ["card", "cash"],
}


def read(figures: dict = FIGURES, **kwargs) -> dict:
    figures_op = op("testapp.probe.figures", kind="query", output=FiguresOut, fn=lambda ctx, data: figures)
    outcome = assistant.run_tool(ctx("testapp.manage", language="es"), figures_op, "{}", **kwargs)
    assert outcome.outcome == "ok"
    return json.loads(outcome.content)


def test_each_value_its_screens_name_comes_once_with_its_name_in_the_persons_language_under_its_datum():
    told = read()
    assert told[assistant.SCREEN_NAMES] == {
        "status": {"open": "status:open@es"},
        "rows.status": {"open": "status:open@es", "done": "status:done@es"},
        "best.status": {"done": "status:done@es"},
        "states": {"done": "status:done@es"},
        "method": {"card": "method:card@es"},
        "methods": {"card": "method:card@es"},
    }


def test_the_codes_stay_as_they_were():
    told = read()
    assert {key: value for key, value in told.items() if key != assistant.SCREEN_NAMES} == written(FIGURES)


def test_with_nothing_its_screens_name_a_result_reads_as_its_operation_wrote_it():
    unnamed = {**FIGURES, "status": "vip", "rows": [], "best": None, "states": [], "method": "cash", "methods": []}
    assert read(unnamed) == written(unnamed)


def written(figures: dict) -> dict:
    return json.loads(FiguresOut.model_validate(figures).model_dump_json())


def test_a_long_result_keeps_its_names_and_says_how_many_rows_it_had():
    rows = [{"status": "open", "note": "a note"}, {"status": "done", "note": "another"}] * 2000
    told = read({**FIGURES, "rows": rows})
    assert len(json.dumps(told, ensure_ascii=False, separators=(",", ":"))) <= assistant.MAX_RESULT_CHARS
    assert told[assistant.SCREEN_NAMES]["rows.status"] == {"open": "status:open@es", "done": "status:done@es"}
    assert re.findall(r"\d+", told["cut"])[1] == "4000"


def test_the_name_of_a_value_is_the_one_its_field_gives_it_or_none():
    figures_op = op("testapp.probe.figures", kind="query", output=FiguresOut)
    with translation.override("es"):
        assert screen_names.screen_name(figures_op, "status", None, "done") == "status:done@es"
        assert screen_names.screen_name(figures_op, "methods", "sale.method", "card") == "method:card@es"
        assert screen_names.screen_name(figures_op, "note", None, "open") is None
