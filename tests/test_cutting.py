"""A tool's result longer than the model is told at once: it keeps whole rows and says how to read on, and it is
always JSON the model can read."""

import json

import pytest
from live import assistant
from live.assistant import cutting
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


class Record(Schema):
    number: str
    total: int
    qr: str


class Loose(Schema):
    data: dict


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


def cut_off(kept: int, of: int) -> str:
    return f" …(cut: only the first {kept} of {of} characters fit)"


def kept_of(text: str) -> int:
    return text.index(" …(cut: ")


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


def test_a_long_text_keeps_its_first_characters_and_the_rest_of_the_answer_comes_whole():
    answer = {"number": "T-1", "total": 121, "qr": "q" * (3 * LIMIT)}
    content = told(Record, answer, input=FilterIn)
    record = json.loads(content)
    kept = kept_of(record["qr"])
    assert len(content) <= LIMIT
    assert record == {**answer, "qr": "q" * kept + cut_off(kept, 3 * LIMIT)}
    assert len(written({**record, "qr": "q" * (kept + 1) + cut_off(kept + 1, 3 * LIMIT)})) > LIMIT


def test_every_long_text_is_cut_to_the_same_length_wherever_it_is_and_the_short_ones_stay_whole():
    answer = {"data": {"qr": "q" * (2 * LIMIT), "lines": [{"xml": "<x/>" * LIMIT, "number": "T-1"}]}}
    data = json.loads(told(Loose, answer, input=FilterIn))["data"]
    kept = kept_of(data["qr"])
    assert data == {
        "qr": "q" * kept + cut_off(kept, 2 * LIMIT),
        "lines": [{"xml": ("<x/>" * LIMIT)[:kept] + cut_off(kept, 4 * LIMIT), "number": "T-1"}],
    }


def test_a_text_its_cut_would_not_shorten_stays_whole():
    shell = len(written({"data": {"a": "", "b": ""}}))
    near = (LIMIT - shell - len(cut_off(8_000, 3 * LIMIT))) // 2 + 10
    answer = {"data": {"a": "a" * (3 * LIMIT), "b": "b" * near}}
    data = json.loads(told(Loose, answer, input=FilterIn))["data"]
    assert near - len(cut_off(near, near)) < kept_of(data["a"]) < near
    assert data["b"] == "b" * near


@pytest.mark.parametrize("key", ["b", "bb"])
def test_a_text_is_never_traded_for_a_cut_as_long_as_itself(key):
    shell = len(written({"data": {"a": "", key: ""}}))
    middle = (LIMIT - shell - len(cut_off(8_000, 3 * LIMIT))) // 2
    for near in range(middle - 30, middle + 60):
        answer = {"data": {"a": "a" * (3 * LIMIT), key: "b" * near}}
        data = json.loads(told(Loose, answer, input=FilterIn))["data"]
        assert data[key] == "b" * near or len(data[key]) < near, near


def test_a_row_longer_than_the_whole_cut_keeps_every_row_with_its_text_cut():
    answer = {"rows": rows(2, size=2 * LIMIT), "total": 2, "limit": 50, "offset": 0}
    content = told(Page, answer)
    page = json.loads(content)
    kept = kept_of(page["rows"][0]["note"])
    assert len(content) <= LIMIT
    assert page == {**answer, "rows": [{**row, "note": "x" * kept + cut_off(kept, 2 * LIMIT)} for row in answer["rows"]]}


def test_an_answer_too_long_even_without_its_texts_comes_as_its_first_characters_and_says_so():
    answer = {"data": {f"amount_{i:05d}": i for i in range(3_000)}}
    whole_answer = Loose.model_validate(answer).model_dump_json()
    content = told(Loose, answer, input=FilterIn)
    cut = json.loads(content)
    seen = len(cut["answer"])
    assert len(content) <= LIMIT < len(whole_answer)
    assert cut == {
        "cut": f"Only the first {seen} of the {len(whole_answer)} characters of the answer fit here: narrow the request.",
        "answer": whole_answer[:seen],
    }
    assert seen > LIMIT // 2


def test_an_answer_with_no_room_for_a_single_character_is_still_json():
    read = op("testapp.probe.long", output=LongOut, fn=lambda ctx, data: {})
    content = '{"text":"' + "x" * 100 + '"}'
    assert json.loads(cutting.within(read, {}, content, 10)) == {
        "cut": f"Only the first 0 of the {len(content)} characters of the answer fit here: narrow the request.",
        "answer": "",
    }
