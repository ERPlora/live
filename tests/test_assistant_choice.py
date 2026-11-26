"""A value of a closed list on a write's card (``live.assistant.CHOICE``): «Light» or «50 m» says which option was
chosen, never which datum it is, so the screen names it even when it goes first («Appearance: Light»)."""

from typing import Literal

import pytest
from live import assistant
from ninja import Field, Schema

from tests.test_assistant import CREATE, SpokenWords, fields, op


class SettingsIn(Schema):
    name: str | None = None
    theme: Literal["", "light", "dark"] | None = None
    scale: Literal[90, 110] | None = None
    method: Literal["cash", "card"] | None = Field(None, json_schema_extra={"choices_of": "sale.method"})
    sizes: list[Literal["s", "m"]] = []
    count: int | None = None
    online: bool | None = None


#: The labels the app gives its closed lists; «dark» and 90 have none.
LABELS = {"light": "Light", 110: "110%", "card": "Card", "s": "Small", "m": "Medium"}


@pytest.fixture
def settings_write(monkeypatch):
    monkeypatch.setattr(assistant.cards, "choice_label", lambda app, entity, name, value: LABELS.get(value))
    return op("testapp.probe.settings", ai=CREATE, input=SettingsIn)


def choices(card: dict) -> dict:
    return {name: shown.get(assistant.CHOICE, False) for name, shown in fields(card).items()}


@pytest.mark.parametrize("words", [None, SpokenWords])
def test_a_value_of_a_closed_list_is_marked_a_choice_and_no_other_datum_is(settings_write, words):
    arguments = {
        "name": "Ana",
        "theme": "light",
        "scale": 110,
        "method": "card",
        "sizes": ["s", "m"],
        "count": 3,
        "online": True,
    }
    card = assistant.card(settings_write, arguments, "en", words and words(settings_write, "en"))
    assert choices(card) == {
        "name": False,
        "theme": True,
        "scale": True,
        "method": True,
        "sizes": False,
        "count": False,
        "online": False,
    }
    shown = fields(card)
    assert (shown["theme"]["kind"], shown["theme"]["value"]) == ("text", "Light")
    assert (shown["scale"]["kind"], shown["scale"]["value"]) == ("text", "110%")


def test_a_value_its_app_gives_no_label_is_still_a_choice(settings_write):
    """Said as sent («dark», 90), it is still one option of the list, not what the write is about."""
    shown = fields(assistant.card(settings_write, {"theme": "dark", "scale": 90}, "en"))
    assert [(shown[name]["value"], shown[name].get(assistant.CHOICE)) for name in ("theme", "scale")] == [
        ("dark", True),
        (90, True),
    ]


def test_an_empty_value_of_a_closed_list_shows_a_dash_and_is_no_choice(settings_write):
    shown = fields(assistant.card(settings_write, {"theme": ""}, "en"))["theme"]
    assert (shown["kind"], assistant.CHOICE in shown) == ("empty", False)
