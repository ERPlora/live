"""SSE frames and the `s=` subscription list of `/api/live` (plan §4.1)."""

import base64
import json

import pytest

from live import sse


def encode(value) -> str:
    """base64url without padding, as the SDK sends it."""
    raw = json.dumps(value).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def lines_of(frame: bytes) -> list[str]:
    text = frame.decode()
    assert text.endswith("\n\n"), "a frame ends with a blank line"
    return text[:-2].split("\n")


class TestConstants:
    def test_event_names_are_the_contract(self):
        assert (sse.HELLO, sse.RESULT, sse.ERROR, sse.HEARTBEAT, sse.BYE) == (
            "hello",
            "result",
            "error",
            "heartbeat",
            "bye",
        )

    def test_limits_are_the_contract(self):
        assert sse.MAX_SUBS == 50
        assert sse.MAX_RESULT_BYTES == 256 * 1024
        assert sse.HEARTBEAT_EVERY == 15.0
        assert sse.RETRY_MS == 3000


class TestFrame:
    def test_event_and_data_lines(self):
        frame = sse.frame(sse.RESULT, {"id": "s1", "data": [1, 2], "rev": 3})

        assert isinstance(frame, bytes)
        assert lines_of(frame) == ["event: result", 'data: {"id":"s1","data":[1,2],"rev":3}']

    def test_no_data_is_an_empty_object(self):
        assert lines_of(sse.frame(sse.HEARTBEAT)) == ["event: heartbeat", "data: {}"]

    def test_id_and_retry_lines_come_before_data(self):
        frame = sse.frame(sse.HELLO, {"stream": "abc"}, id="7", retry_ms=sse.RETRY_MS)

        assert lines_of(frame) == ["event: hello", "id: 7", "retry: 3000", 'data: {"stream":"abc"}']

    def test_newlines_inside_values_never_split_the_data_line(self):
        frame = sse.frame(sse.RESULT, {"id": "s1", "data": {"note": "one\ntwo\r\nthree"}})

        lines = lines_of(frame)
        assert len(lines) == 2
        assert json.loads(lines[1].removeprefix("data: ")) == {"id": "s1", "data": {"note": "one\ntwo\r\nthree"}}

    def test_non_ascii_is_kept_as_utf8(self):
        frame = sse.frame(sse.RESULT, {"id": "s1", "data": "añadir línea"})

        assert "añadir línea" in frame.decode("utf-8")

    def test_django_types_are_serialised(self):
        import datetime
        import decimal
        import uuid

        value = uuid.UUID("0192f1e0-0000-7000-8000-000000000000")
        frame = sse.frame(
            sse.RESULT,
            {"id": "s1", "data": {"pk": value, "at": datetime.date(2026, 10, 13), "total": decimal.Decimal("1.50")}},
        )

        data = json.loads(lines_of(frame)[1].removeprefix("data: "))
        assert data["data"] == {"pk": str(value), "at": "2026-10-13", "total": "1.50"}

    @pytest.mark.parametrize("field", ["event", "id"])
    def test_a_line_break_in_event_or_id_is_refused(self, field):
        kwargs = {"event": "result", "id": "1"}
        kwargs[field] = "bad\nvalue"

        with pytest.raises(ValueError):
            sse.frame(kwargs["event"], {}, id=kwargs["id"])


class TestParseSubscriptions:
    def test_happy_path(self):
        subs = [
            {"id": "s1", "op": "demo.item.list", "params": {"limit": 20}},
            {"id": "s2", "op": "demo.item.detail", "params": {"id": "x"}},
        ]

        assert sse.parse_subscriptions(encode(subs)) == subs

    def test_padding_is_tolerated(self):
        subs = [{"id": "s1", "op": "demo.item.list", "params": {}}]
        padded = base64.urlsafe_b64encode(json.dumps(subs).encode()).decode()

        assert sse.parse_subscriptions(padded) == subs

    def test_an_empty_list_is_valid(self):
        assert sse.parse_subscriptions(encode([])) == []

    def test_more_than_the_limit_is_refused(self):
        subs = [{"id": f"s{i}", "op": "demo.item.list", "params": {}} for i in range(51)]

        with pytest.raises(ValueError, match="^too_many_subscriptions$"):
            sse.parse_subscriptions(encode(subs))

    def test_exactly_the_limit_is_accepted(self):
        subs = [{"id": f"s{i}", "op": "demo.item.list", "params": {}} for i in range(50)]

        assert len(sse.parse_subscriptions(encode(subs))) == 50

    def test_the_limit_can_be_lowered(self):
        subs = [{"id": f"s{i}", "op": "demo.item.list", "params": {}} for i in range(3)]

        with pytest.raises(ValueError, match="^too_many_subscriptions$"):
            sse.parse_subscriptions(encode(subs), max_subs=2)

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "!!!not-base64!!!",
            "eyJ",  # base64 of a truncated JSON document
            base64.urlsafe_b64encode(b"\xff\xfe").decode(),  # not UTF-8
            base64.urlsafe_b64encode(b"{not json").decode(),
            "a+b/",  # standard base64 alphabet, not base64url
        ],
    )
    def test_bad_base64_or_json_is_refused(self, raw):
        with pytest.raises(ValueError, match="^invalid_subscriptions$"):
            sse.parse_subscriptions(raw)

    @pytest.mark.parametrize(
        "value",
        [
            {"id": "s1", "op": "demo.item.list", "params": {}},  # not a list
            ["demo.item.list"],  # item is not an object
            [{"op": "demo.item.list", "params": {}}],  # missing id
            [{"id": "s1", "params": {}}],  # missing op
            [{"id": "s1", "op": "demo.item.list"}],  # missing params
            [{"id": 1, "op": "demo.item.list", "params": {}}],  # id not a string
            [{"id": "", "op": "demo.item.list", "params": {}}],  # empty id
            [{"id": "s1", "op": "", "params": {}}],  # empty op
            [{"id": "s1", "op": "demo.item.list", "params": []}],  # params not an object
            [{"id": "s1", "op": "demo.item.list", "params": {}, "extra": 1}],  # unknown key
            [
                {"id": "s1", "op": "demo.item.list", "params": {}},
                {"id": "s1", "op": "demo.item.detail", "params": {}},
            ],  # duplicated id: results are routed by id
        ],
    )
    def test_a_wrong_shape_is_refused(self, value):
        with pytest.raises(ValueError, match="^invalid_subscriptions$"):
            sse.parse_subscriptions(encode(value))


@pytest.mark.parametrize("extra", ["", "a", "ab", "abc"])  # every length mod 3, so every padding size
def test_parse_accepts_base64url_without_padding(extra):
    """The SDK (V1) sends `s=` as base64url without `=`; `?`/`>` force the `-`/`_` alphabet."""
    subs = [{"id": "s1" + extra, "op": "demo.item.list", "params": {"q": "??>>~~"}}]
    raw = json.dumps(subs, separators=(",", ":")).encode()
    unpadded = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    assert "=" not in unpadded

    assert sse.parse_subscriptions(unpadded) == subs
