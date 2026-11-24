"""The schema a tool is offered to the model with (``live.assistant.tool_spec``): pydantic's input schema without its
titles, which repeat each datum's name («Product Id») and weigh on every call; what the person sees on a write's card
still names each datum by the title its app wrote (``input_schema``)."""

from enum import Enum
from typing import Annotated

from live import assistant
from live.operations import AI, Operation
from ninja import Field, Schema
from pydantic import StringConstraints


class Color(str, Enum):
    red = "red"


class Section(Schema):
    title: str = Field(description="The section's heading.")
    color: Color = Color.red


class PageIn(Schema):
    title: str
    counted: int | None = Field(None, title="Counted cash", json_schema_extra={"money": True})
    either: Annotated[int, Field(title="Small")] | Annotated[str, Field(title="Word")] = 1
    sections: list[Section] = []
    main: Section | None = None
    extra: dict = {"title": "Hola"}
    sample: dict = Field({}, examples=[{"title": "Hola"}])
    counts: dict[Annotated[str, StringConstraints(pattern="title")], int] = {}


#: ``PageIn``'s schema as the model receives it: every keyword pydantic writes but its titles; a datum called «title»,
#: a default or an example that holds one and the data whose names match «title» are the app's, not titles.
TOLD = {
    "$defs": {
        "Color": {"enum": ["red"], "type": "string"},
        "Section": {
            "properties": {
                "title": {"description": "The section's heading.", "type": "string"},
                "color": {"$ref": "#/$defs/Color", "default": "red"},
            },
            "required": ["title"],
            "type": "object",
        },
    },
    "properties": {
        "title": {"type": "string"},
        "counted": {"anyOf": [{"type": "integer"}, {"type": "null"}], "default": None, "money": True},
        "either": {"anyOf": [{"type": "integer"}, {"type": "string"}], "default": 1},
        "sections": {"default": [], "items": {"$ref": "#/$defs/Section"}, "type": "array"},
        "main": {"anyOf": [{"$ref": "#/$defs/Section"}, {"type": "null"}], "default": None},
        "extra": {"additionalProperties": True, "default": {"title": "Hola"}, "type": "object"},
        "sample": {"additionalProperties": True, "default": {}, "examples": [{"title": "Hola"}], "type": "object"},
        "counts": {"default": {}, "patternProperties": {"title": {"type": "integer"}}, "type": "object"},
    },
    "required": ["title"],
    "type": "object",
}


def page_op() -> Operation:
    return Operation(
        name="testapp.page.save",
        kind="command",
        permission="testapp.manage",
        input=PageIn,
        output=PageIn,
        expose_api=False,
        ai=AI(description="Saves the page."),
        fn=lambda ctx, data: data,
        database=False,
    )


def refs(node) -> list[str]:
    if isinstance(node, dict):
        own = [node["$ref"]] if "$ref" in node else []
        return own + [ref for value in node.values() for ref in refs(value)]
    return [ref for value in node for ref in refs(value)] if isinstance(node, list) else []


def test_a_tool_is_told_to_the_model_without_the_titles_of_its_schema():
    assert assistant.tool_spec(page_op())["parameters"] == TOLD


def test_each_reference_of_the_schema_told_still_names_one_of_its_definitions():
    told = assistant.tool_spec(page_op())["parameters"]
    assert sorted(set(refs(told))) == ["#/$defs/Color", "#/$defs/Section"]
    assert all(ref.removeprefix("#/$defs/") in told["$defs"] for ref in refs(told))


def test_the_card_of_the_write_still_names_a_datum_by_the_title_its_app_wrote():
    page = page_op()
    assert assistant.input_schema(page)["properties"]["counted"]["title"] == "Counted cash"
    [counted] = assistant.card(page, {"counted": 1200}, "en")["fields"]
    assert (counted["label"], counted.get("titled")) == ("Counted cash", True)
