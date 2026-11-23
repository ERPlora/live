"""How many tools a turn offers (``live.assistant.relevant``): only those the words name, at most ``MAX_TOOLS``.

Every tool offered travels whole with each call to the model. A turn that filled its share with tools the words never
named sent a «hola» or a «sí» with forty full specifications; what was asked and no tool offered is found with the
search of the rest of the catalogue.
"""

from live import assistant
from live.operations import AI, Operation
from ninja import Schema


class NoIn(Schema):
    pass


class Done(Schema):
    done: bool = True


def op(name: str, description: str, kind: str = "command") -> Operation:
    return Operation(
        name=name,
        kind=kind,
        permission="testapp.manage",
        input=NoIn,
        output=Done,
        expose_api=False,
        ai=AI(description=description),
        fn=lambda ctx, data: Done(),
    )


THINGS = {
    "testapp.probe.list": op("testapp.probe.list", "Lists the things by name.", kind="query"),
    "testapp.probe.create": op("testapp.probe.create", "Creates a thing with its name."),
}
UNNAMED = op("demo.invoice.archive", "Archives the invoices of a closed year.")


def names(offered: list[Operation]) -> list[str]:
    return [tool.name for tool in offered]


def test_a_greeting_or_a_yes_is_offered_no_tool():
    tools = {**THINGS, UNNAMED.name: UNNAMED}
    for said in ("hola", "sí", "hello", "yes"):
        assert assistant.relevant(tools, [said], "es") == [], said


def test_what_is_always_at_hand_is_still_offered_when_the_words_name_nothing():
    tools = {**THINGS, UNNAMED.name: UNNAMED}
    assert names(assistant.relevant(tools, ["hola"], "es", always=(UNNAMED.name,))) == [UNNAMED.name]


def test_a_tool_the_words_do_not_name_is_left_out_of_what_they_ask():
    tools = {**THINGS, UNNAMED.name: UNNAMED}
    assert names(assistant.relevant(tools, ["Show me my things"], "en")) == ["testapp.probe.list", "testapp.probe.create"]


def test_a_turn_offers_twenty_tools_at_most():
    many = {f"testapp.many.n{i:02}": op(f"testapp.many.n{i:02}", "Lists the things.", "query") for i in range(25)}
    offered = assistant.relevant(many, ["Show me my things"], "en")
    assert assistant.MAX_TOOLS == 20
    assert names(offered) == sorted(many)[: assistant.MAX_TOOLS]
