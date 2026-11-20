"""A cut of the database on the live stream: a passing error of its pass, or a 503 that tells it to come back."""

import pytest
from live.executor import Executor, Stream, Subscription

from tests.database_cut.cutting import always_cut, cut_once
from tests.database_cut.project import READ, UNAVAILABLE, Empty, ProbeBuilder, code_of, runs, script
from tests.live_helpers import drain

pytestmark = pytest.mark.django_db(databases=["default", "other"], transaction=True)


def _stream() -> Stream:
    return Stream(ProbeBuilder._context())


async def _pass_of(stream: Stream, sleeps: list[float] | None = None) -> list:
    waits = [] if sleeps is None else sleeps

    async def sleep(seconds):
        waits.append(seconds)

    executor = Executor(sleep=sleep)
    try:
        await executor.run_all(stream)
    finally:
        executor.reset()
        executor.shutdown()
    return await drain(stream.queue)


async def test_a_live_query_cut_is_a_passing_error_of_its_pass():
    script["read"] = cut_once
    stream = _stream()
    stream.subs["s1"] = Subscription(id="s1", op=READ, params=Empty())
    sleeps: list[float] = []

    frames = await _pass_of(stream, sleeps)

    assert [(each.event, each.data.get("data")) for each in frames] == [("result", {"rows": 7})]
    assert len(sleeps) == 1
    assert runs["read"] == 2


async def test_a_cut_while_rereading_the_stream_context_is_a_passing_error_too():
    script["refresh"] = cut_once
    script["read"] = lambda attempt: 1
    stream = _stream()
    stream.subs["s1"] = Subscription(id="s1", op=READ, params=Empty())

    frames = await _pass_of(stream)

    assert [(each.event, each.data.get("data")) for each in frames] == [("result", {"rows": 1})]
    assert runs["refresh"] == 2


async def test_a_live_query_that_stays_cut_tells_its_stream_to_come_back():
    script["read"] = always_cut
    stream = _stream()
    stream.subs["s1"] = Subscription(id="s1", op=READ, params=Empty())

    frames = await _pass_of(stream)

    assert [(each.event, each.data["error"]["code"]) for each in frames] == [("error", UNAVAILABLE)]
    assert runs["read"] == 4


def test_a_live_stream_that_cannot_open_answers_503_with_retry_after(client):
    script["builder"] = always_cut

    response = client.get("/api/live")

    assert response.status_code == 503, response.content
    assert int(response["Retry-After"]) > 0
    assert runs["builder"] > 1


def test_a_live_stream_whose_context_runs_an_operation_answers_503_with_retry_after(client):
    def runs_a_query(attempt):
        script["read"] = always_cut
        READ(ProbeBuilder._context(), Empty())

    script["builder"] = runs_a_query

    response = client.get("/api/live")

    assert response.status_code == 503, response.content
    assert code_of(response) == UNAVAILABLE
    assert int(response["Retry-After"]) > 0
    assert runs["builder"] > 1
