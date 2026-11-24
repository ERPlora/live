"""A tool's result longer than the model is told at once: it keeps whole rows and says how to read on."""

import json

import pytest
from live import assistant
from ninja import Field, Schema

from tests.test_assistant import ctx, op

LIMIT = assistant.MAX_RESULT_CHARS


class PageIn(Schema):
    limit: int = Field(50, ge=1, le=100)
    offset: int = Field(0, ge=0)


class FilterIn(Schema):
    names: list[str] | None = None


class Row(Schema):
    name: str
    note: str


class Page(Schema):
    rows: list[Row]
    total: int
    limit: int
    offset: int


class Unechoed(Schema):
    items: list[Row]
    total: int


class LongOut(Schema):
    text: str


class Catalogue(Schema):
    apps: list[str]
    actions: list[Row]


def rows(count: int, size: int = 1_000) -> list[dict]:
    return [{"name": f"café {i}", "note": "x" * size} for i in range(count)]


def written(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def told(output, answer, arguments: str = "", input=PageIn) -> str:
    read = op("testapp.probe.rows", kind="query", input=input, output=output, fn=lambda ctx, data: answer)
    outcome = assistant.run_tool(ctx("testapp.manage"), read, arguments)
    assert outcome.outcome == "ok"
    return outcome.content


def whole(output, answer) -> int:
    return len(output.model_validate(answer).model_dump_json())


def next_page(kept: int, of: int, offset: int) -> str:
    return f"Only the first {kept} of the {of} rows fit here: call again with offset {offset} to read the next ones."


def test_a_result_that_fits_is_told_as_the_operation_answers_it():
    answer = {"rows": rows(3), "total": 3, "limit": 50, "offset": 0}
    assert told(Page, answer) == Page.model_validate(answer).model_dump_json()


def test_a_result_exactly_as_long_as_the_limit_is_told_whole():
    exact = op("testapp.probe.long", output=LongOut, fn=lambda ctx, data: {"text": "x" * (LIMIT - 11)})
    assert assistant.run_tool(ctx("testapp.manage"), exact, "").content == '{"text":"' + "x" * (LIMIT - 11) + '"}'


def test_a_result_of_twenty_thousand_characters_is_more_than_the_model_is_told_at_once():
    answer = {"rows": rows(20), "total": 20, "limit": 50, "offset": 0}
    assert whole(Page, answer) > 20_000
    assert len(told(Page, answer)) <= LIMIT < 20_000


@pytest.mark.parametrize("size", [291, 700, 1_000, 1_700, 4_000])
def test_a_long_page_keeps_as_many_whole_rows_as_fit_and_says_which_offset_reads_on(size):
    answer = {"rows": rows(50, size), "total": 340, "limit": 50, "offset": 100}
    content = told(Page, answer, '{"offset": 100}')
    page = json.loads(content)
    kept = len(page["rows"])
    assert len(content) <= LIMIT
    assert content == written(page)
    assert page == {**answer, "rows": answer["rows"][:kept], "cut": next_page(kept, 50, 100 + kept)}
    assert len(written({**page, "rows": answer["rows"][: kept + 1]})) > LIMIT


def test_a_page_just_over_the_limit_leaves_out_only_its_last_row():
    answer = {"rows": rows(50, 291), "total": 50, "limit": 50, "offset": 0}
    assert len(json.loads(told(Page, answer))["rows"]) == 49


@pytest.mark.parametrize("kept", range(1, 15))
def test_rows_that_reach_the_limit_exactly_are_all_kept(kept):
    answer = {"rows": rows(50), "total": 340, "limit": 50, "offset": 0}
    room = LIMIT - len(written({**answer, "rows": answer["rows"][:kept], "cut": next_page(kept, 50, kept)}))
    answer["rows"][kept - 1]["note"] += "x" * room
    assert len(json.loads(told(Page, answer))["rows"]) == kept


def test_a_default_page_of_fifty_short_rows_is_told_whole():
    answer = {"rows": rows(50, size=250), "total": 50, "limit": 50, "offset": 0}
    assert json.loads(told(Page, answer)) == answer


def test_the_offset_a_page_says_it_skipped_is_the_one_read_on_from():
    answer = {"rows": rows(50), "total": 340, "limit": 50, "offset": 90}
    page = json.loads(told(Page, answer, '{"offset": 100}'))
    assert page["cut"] == next_page(len(page["rows"]), 50, 90 + len(page["rows"]))


def test_a_page_that_says_no_offset_and_was_asked_none_reads_on_from_its_first_rows():
    page = json.loads(told(Unechoed, {"items": rows(50), "total": 90}))
    kept = len(page["items"])
    assert page["cut"].endswith(f"call again with offset {kept} to read the next ones.")


def test_a_page_that_does_not_say_its_offset_reads_on_from_the_one_asked_for():
    answer = {"items": rows(50), "total": 90}
    page = json.loads(told(Unechoed, answer, '{"offset": 40}'))
    kept = len(page["items"])
    assert page["cut"].endswith(f"call again with offset {40 + kept} to read the next ones.")


def test_a_list_the_tool_cannot_page_says_to_narrow_the_request():
    answer = {"apps": ["sale", "task"], "actions": rows(50)}
    page = json.loads(told(Catalogue, answer, input=FilterIn))
    kept = len(page["actions"])
    assert 1 <= kept < 50
    assert page["apps"] == ["sale", "task"]
    assert page["cut"] == f"Only the first {kept} of the 50 actions fit here: narrow the request to read the others."


def test_the_list_that_takes_the_most_room_is_the_one_shortened_though_another_has_more_items():
    answer = {"apps": [f"app {i}" for i in range(60)], "actions": rows(20)}
    page = json.loads(told(Catalogue, answer, input=FilterIn))
    assert page["apps"] == answer["apps"]
    assert 1 <= len(page["actions"]) < 20


def test_a_result_with_no_list_to_shorten_is_cut_and_says_how_much_was_seen():
    long = op("testapp.probe.long", output=LongOut, fn=lambda ctx, data: {"text": "x" * (3 * LIMIT)})
    content = assistant.run_tool(ctx("testapp.manage"), long, "").content
    assert len(content) <= LIMIT
    seen = LIMIT - len(f" …(cut: only the first {LIMIT} of {3 * LIMIT + 11} characters fit)")
    assert content == '{"text":"' + "x" * (seen - 9) + f" …(cut: only the first {seen} of {3 * LIMIT + 11} characters fit)"


def test_a_row_longer_than_the_whole_cut_is_told_cut_rather_than_as_no_rows():
    answer = {"rows": rows(2, size=2 * LIMIT), "total": 2, "limit": 50, "offset": 0}
    content = told(Page, answer)
    assert len(content) <= LIMIT
    assert content.startswith('{"rows":[{"name":"café 0","note":"xxx')
    assert content.endswith(" characters fit)")
