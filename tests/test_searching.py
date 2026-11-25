"""The search of the tools a turn did not offer (``live.assistant.found``, ``offered`` and ``searched``): a turn offers
only the tools its words name best, so the project gives its model a search of the rest, last in every turn; the model
searches for the task it lacks a tool for, and the next round of the same request offers what it found.

The Hub's assistant and the panel of erplora.com use the same search, each with its own search tool and its own words.
"""

import json

from ninja import Schema
from pydantic import Field

from live import assistant
from live.operations import AI, Operation
from tests.assistant_catalogue import CATALOGUE


class FindIn(Schema):
    query: str = Field(min_length=1)


class FoundOut(Schema):
    tools: list[dict]


SEARCH = Operation(
    name="testapp.assistant.find_tools",
    kind="query",
    permission="testapp.view",
    input=FindIn,
    output=FoundOut,
    expose_api=False,
    ai=AI(description="Finds the tools for a task."),
    fn=lambda ctx, data: {"tools": []},
    database=False,
)
ALWAYS = ("customer.customer.list",)


def names(tools: list[Operation]) -> list[str]:
    return [op.name for op in tools]


def found(query: str, language: str = "en", **ranking) -> list[str]:
    return names(assistant.found(CATALOGUE, query, language, **ranking))


def offered(*said: str, searched=(), places: int = 5, language: str = "en") -> list[str]:
    search = assistant.ToolSearch(SEARCH, places)
    tools = assistant.offered(CATALOGUE, list(said), language, search=search, searched=searched, always=ALWAYS)
    return names(tools)


def model_asked(*calls: tuple[str, str]) -> dict:
    """The model's message asking for ``calls`` (tool name → its arguments), as the browser keeps it."""
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {"id": f"c{at}", "type": "function", "function": {"name": name, "arguments": arguments}}
            for at, (name, arguments) in enumerate(calls)
        ],
    }


def search_for(task: str) -> tuple[str, str]:
    return assistant.tool_name(SEARCH.name), json.dumps({"query": task})


class TestFound:
    def test_a_search_finds_the_tools_of_the_task_best_first(self):
        assert found("create a reservation")[0] == "reservation.reservation.create"

    def test_it_finds_ten_tools_at_most(self):
        assert assistant.FOUND == 10
        assert len(found("create a thing")) == assistant.FOUND

    def test_it_never_finds_what_every_turn_already_offers(self):
        assert "customer.customer.list" in found("list the customers")
        assert "customer.customer.list" not in found("list the customers", always=ALWAYS)

    def test_what_names_no_tool_finds_nothing(self):
        assert found("hello") == []


class TestOffered:
    def test_the_search_is_offered_last_and_takes_no_place_from_the_tools(self):
        ranked = names(assistant.relevant(CATALOGUE, ["list the tables"], "en", always=ALWAYS))
        assert len(ranked) > 5  # positive control: the words name more tools than fit
        assert offered("list the tables") == [*ranked[:5], SEARCH.name]

    def test_a_turn_whose_words_name_nothing_still_offers_the_search(self):
        assert offered("hello") == [*ALWAYS, SEARCH.name]

    def test_what_the_model_searched_for_goes_right_after_what_is_always_at_hand(self):
        task = "create a reservation"
        got = offered("list the tables", searched=[task])
        searched = found(task, always=ALWAYS)
        assert 0 < len(ALWAYS) + len(searched) < 5  # what was found fits, with room left for the words
        assert got[: len(ALWAYS) + len(searched)] == [*ALWAYS, *searched]
        assert "table.table.list" in got
        assert len(got) == 5 + 1
        assert got[-1] == SEARCH.name

    def test_the_latest_search_is_offered_first(self):
        got = offered("hello", searched=["list the customers", "create a product"], places=2)
        assert got == [*ALWAYS, "inventory.product.create", SEARCH.name]

    def test_a_tool_both_named_and_found_is_offered_once(self):
        got = offered("create a reservation", searched=["create a reservation"])
        assert got.count("reservation.reservation.create") == 1


class TestSearched:
    def test_it_reads_the_tasks_the_model_searched_for_in_order(self):
        messages = [
            {"role": "user", "content": "The tonic water is new"},
            model_asked(search_for("create a product")),
            {"role": "tool", "tool_call_id": "c0", "content": "{}"},
            model_asked(("base__docs__search", json.dumps({"query": "how do I add a category?"})),
                        search_for("list the categories")),
        ]
        assert assistant.searched(messages, SEARCH) == ["create a product", "list the categories"]

    def test_a_search_its_input_refuses_searched_nothing(self):
        name = assistant.tool_name(SEARCH.name)
        messages = [
            model_asked((name, "list the products")),
            model_asked((name, json.dumps({"query": ""}))),
            model_asked((name, json.dumps({"task": "list the products"}))),
            model_asked((name, "")),
        ]
        assert assistant.searched(messages, SEARCH) == []
        # The search the model writes well after them still counts.
        assert assistant.searched([*messages, model_asked(search_for("list the products"))], SEARCH) == ["list the products"]

    def test_only_the_models_calls_count(self):
        name = assistant.tool_name(SEARCH.name)
        call = {"id": "c0", "type": "function", "function": {"name": name, "arguments": json.dumps({"query": "x"})}}
        messages = [
            {"role": "user", "content": "x", "tool_calls": [call]},
            {"role": "assistant", "content": "", "tool_calls": "not a list"},
            {"role": "assistant", "content": "", "tool_calls": ["not a call", {"function": "not a dict"}]},
            {"role": "assistant", "content": "Hello."},
        ]
        assert assistant.searched(messages, SEARCH) == []

