"""Executor of live queries: a passing error (``OperationError.retry_after``) is tried again after its wait, and only an
error that lasts is sent."""

import asyncio
import threading
import time

import pytest
from live import executor as executor_module
from live.errors import NotFound, OperationError, PermissionDenied

from tests.live_helpers import drain
from tests.test_executor import (  # noqa: F401 - live_builder, its autouse fixture, sets these tests up too
    FakeOp,
    live_builder,
    make_stream,
    subscribe,
    thing,
)
from tests.testapp.schemas import ThingListOut


def busy_for(failures: int, *, retry_after: float = 0.05):
    """A query body that fails ``failures`` times with a passing error (``retry_after``), then answers."""
    state = {"left": failures}

    def body(ctx, params):
        if state["left"]:
            state["left"] -= 1
            raise OperationError("Busy for a moment.", code="busy", status=503, retry_after=retry_after)
        return ThingListOut(rows=[thing(1)])

    return body


async def test_a_passing_error_is_tried_again_after_its_wait_and_only_the_result_is_sent(make_executor):
    executor = make_executor()
    stream = make_stream()
    op = FakeOp(body=busy_for(2))
    subscribe(stream, op)

    started = time.monotonic()
    await executor.run_all(stream)

    frames = await drain(stream.queue)
    assert [(f.event, f.data.get("rev")) for f in frames] == [("result", 1)]
    assert op.calls == 3
    assert time.monotonic() - started >= 2 * 0.05


async def test_a_passing_error_that_lasts_is_sent_after_three_more_tries(make_executor):
    executor = make_executor()
    stream = make_stream()
    op = FakeOp(body=busy_for(10))
    subscribe(stream, op)

    await executor.run_all(stream)

    (frame,) = await drain(stream.queue)
    assert frame.event == "error"
    assert frame.data["error"] == {"code": "busy", "message": "Busy for a moment."}
    assert op.calls == 1 + executor_module.PASSING_ERROR_RETRIES == 4
    assert "s1" in stream.subs


@pytest.fixture
def reached_the_client(monkeypatch):
    """What ``OperationError.reached_client`` heard: the codes of the failures a client got."""
    told = []
    monkeypatch.setattr(OperationError, "reached_client", lambda self: told.append(self.code))
    return told


async def test_a_try_the_executor_makes_again_never_reaches_the_client(make_executor, reached_the_client):
    stream = make_stream()
    subscribe(stream, FakeOp(body=busy_for(2)))

    await make_executor().run_all(stream)

    assert reached_the_client == []


async def test_a_passing_error_that_lasts_reaches_the_client_once_a_pass(make_executor, reached_the_client):
    """Every subscription left waiting gets its frame: one failure of the pass, however many there are."""
    stream = make_stream()
    subscribe(stream, FakeOp(body=busy_for(10)), "s1")
    subscribe(stream, FakeOp(body=busy_for(10)), "s2")

    await make_executor().run_all(stream)

    assert [frame.event for frame in await drain(stream.queue)] == ["error", "error"]
    assert reached_the_client == ["busy"]


async def test_an_error_that_is_not_passing_reaches_the_client_at_once(make_executor, reached_the_client):
    def body(ctx, params):
        raise OperationError("Refused.", code="refused", status=409)

    stream = make_stream()
    subscribe(stream, FakeOp(body=body))

    await make_executor().run_all(stream)

    assert reached_the_client == ["refused"]


async def test_a_permission_lost_reaches_the_client_too(make_executor, reached_the_client):
    def body(ctx, params):
        raise PermissionDenied("Not any more.")

    stream = make_stream()
    subscribe(stream, FakeOp(body=body))

    await make_executor().run_all(stream)

    assert reached_the_client == ["permission_denied"]


async def test_a_passing_error_that_clears_sends_nothing_when_the_result_did_not_change(make_executor):
    state = {"busy": False}

    def body(ctx, params):
        if state["busy"]:
            state["busy"] = False
            raise OperationError("Busy for a moment.", code="busy", status=503, retry_after=0.05)
        return ThingListOut(rows=[thing(1)])

    executor = make_executor()
    stream = make_stream()
    subscribe(stream, FakeOp(body=body))
    await executor.run_all(stream)
    state["busy"] = True
    await executor.run_all(stream)

    # The client never saw the error: the same result is no news.
    assert [(f.event, f.data.get("rev")) for f in await drain(stream.queue)] == [("result", 1)]


async def test_a_run_whose_retry_is_skipped_still_ran(make_executor):
    """Its first try reached a thread and so re-read the stream's context (``_flush`` needs no re-read alone)."""
    executor = make_executor()
    stream = make_stream()
    sub = subscribe(stream, FakeOp(body=busy_for(10, retry_after=0.3)))
    asyncio.get_running_loop().call_later(0.1, stream.subs.clear)

    assert await executor._run_subs(stream, [sub]) is True
    assert await drain(stream.queue) == []


async def test_a_subscription_gone_while_waiting_for_its_scope_lets_the_next_one_run(make_executor):
    executor = make_executor()
    release = threading.Event()

    def blocking(ctx, params):
        release.wait(5)
        return ThingListOut(rows=[])

    holder, waiting = make_stream(), make_stream()
    subscribe(holder, FakeOp(body=blocking))
    gone, kept = FakeOp(rows=[thing(1)]), FakeOp(rows=[thing(2)])
    subscribe(waiting, gone, "s1")
    subscribe(waiting, kept, "s2")
    holding = asyncio.create_task(executor.run_all(holder))
    await asyncio.sleep(0.05)
    run = asyncio.create_task(executor._run_subs(waiting, list(waiting.subs.values())))
    await asyncio.sleep(0.05)
    del waiting.subs["s1"]
    release.set()
    await holding

    assert await run is True
    assert (gone.calls, kept.calls) == (0, 1)
    assert [(f.event, f.data["id"]) for f in await drain(waiting.queue)] == [("result", "s2")]


class FakeSleep:
    """The executor's ``sleep``: records each wait and yields to the loop without waiting."""

    def __init__(self):
        self.waits = []

    async def __call__(self, seconds):
        self.waits.append(seconds)
        await asyncio.sleep(0)


async def test_busy_subscriptions_share_one_wait_per_try_however_many_they_are(make_executor):
    sleep = FakeSleep()
    executor = make_executor(sleep=sleep)
    stream = make_stream()
    ops = [FakeOp(body=busy_for(100)) for _ in range(5)]
    for index, op in enumerate(ops):
        subscribe(stream, op, f"s{index}")

    await executor.run_all(stream)

    # The first one tells the scope is busy: the others wait with it instead of each waiting its own turn.
    assert sleep.waits == [0.05] * executor_module.PASSING_ERROR_RETRIES
    assert [op.calls for op in ops] == [1 + executor_module.PASSING_ERROR_RETRIES, 0, 0, 0, 0]
    frames = await drain(stream.queue)
    assert [(f.event, f.data["id"], f.data["error"]["code"]) for f in frames] == [
        ("error", f"s{index}", "busy") for index in range(5)
    ]


async def test_a_pass_of_many_busy_subscriptions_lasts_as_long_as_one(make_executor):
    executor = make_executor()
    stream = make_stream()
    for index in range(5):
        subscribe(stream, FakeOp(body=busy_for(100, retry_after=0.05)), f"s{index}")

    started = time.monotonic()
    await executor.run_all(stream)

    assert time.monotonic() - started < 0.05 * executor_module.PASSING_ERROR_RETRIES + 0.3


async def test_after_a_wait_the_pass_goes_on_from_the_busy_subscription(make_executor):
    sleep = FakeSleep()
    executor = make_executor(sleep=sleep)
    stream = make_stream()
    first, second, third = FakeOp(rows=[thing(1)]), FakeOp(body=busy_for(1)), FakeOp(rows=[thing(3)])
    subscribe(stream, first, "s1")
    subscribe(stream, second, "s2")
    subscribe(stream, third, "s3")

    await executor.run_all(stream)

    assert sleep.waits == [0.05]
    assert (first.calls, second.calls, third.calls) == (1, 2, 1)
    frames = await drain(stream.queue)
    assert [(f.event, f.data["id"]) for f in frames] == [("result", "s1"), ("result", "s2"), ("result", "s3")]


async def test_a_long_retry_after_is_cut_to_the_longest_wait(make_executor):
    sleep = FakeSleep()
    executor = make_executor(sleep=sleep)
    stream = make_stream()
    subscribe(stream, FakeOp(body=busy_for(100, retry_after=60)))

    await executor.run_all(stream)

    assert executor_module.MAX_RETRY_AFTER == 5
    assert sleep.waits == [5] * executor_module.PASSING_ERROR_RETRIES


async def test_another_stream_of_the_same_scope_goes_on_while_one_waits(make_executor):
    executor = make_executor()
    waiting, other = make_stream(), make_stream()
    subscribe(waiting, FakeOp(body=busy_for(1, retry_after=0.5)))
    subscribe(other, FakeOp(rows=[thing(1)]))

    started = time.monotonic()
    waits = asyncio.create_task(executor.run_all(waiting))
    await asyncio.sleep(0.05)
    await executor.run_all(other)
    other_done = time.monotonic() - started
    await waits

    assert other_done < 0.4
    assert not waits.cancelled()
    assert [f.event for f in await drain(other.queue)] == ["result"]


class SleepThen(FakeSleep):
    """A ``FakeSleep`` that, on its wait number ``at`` (1-based), runs ``then()`` (a coroutine function) first."""

    def __init__(self, at, then):
        super().__init__()
        self.at, self.then = at, then

    async def __call__(self, seconds):
        await super().__call__(seconds)
        if len(self.waits) == self.at:
            await self.then()


async def test_a_subscription_another_pass_answered_meanwhile_gets_no_busy_error(make_executor):
    stream = make_stream()
    busy, other = FakeOp(body=busy_for(100)), FakeOp(rows=[thing(2)])
    subscribe(stream, busy, "s1")
    second = subscribe(stream, other, "s2")
    executor = make_executor()
    # While this pass waits, an event's pass runs s2 and sends its newer result.
    executor.sleep = SleepThen(1, lambda: executor._run_subs(stream, [second]))

    await executor.run_all(stream)

    frames = await drain(stream.queue)
    assert [(f.event, f.data["id"]) for f in frames] == [("result", "s2"), ("error", "s1")]
    assert other.calls == 1


async def test_a_subscription_gone_before_the_last_try_gets_no_error(make_executor):
    stream = make_stream()
    subscribe(stream, FakeOp(body=busy_for(100)), "s1")
    subscribe(stream, FakeOp(rows=[thing(2)]), "s2")
    executor = make_executor()

    async def unsubscribe_s2():
        del stream.subs["s2"]

    executor.sleep = SleepThen(executor_module.PASSING_ERROR_RETRIES, unsubscribe_s2)

    await executor.run_all(stream)

    assert [(f.event, f.data["id"]) for f in await drain(stream.queue)] == [("error", "s1")]


async def test_the_error_after_the_last_try_lets_the_same_result_through_again(make_executor):
    state = {"busy": False}

    def body(ctx, params):
        if state["busy"]:
            raise OperationError("Busy for a moment.", code="busy", status=503, retry_after=0.01)
        return ThingListOut(rows=[thing(1)])

    executor = make_executor(sleep=FakeSleep())
    stream = make_stream()
    subscribe(stream, FakeOp(body=body))
    await executor.run_all(stream)
    state["busy"] = True
    await executor.run_all(stream)
    state["busy"] = False
    await executor.run_all(stream)

    frames = await drain(stream.queue)
    assert [(f.event, f.data.get("rev")) for f in frames] == [("result", 1), ("error", None), ("result", 2)]


async def test_a_final_error_is_never_tried_again(make_executor):
    def body(ctx, params):
        raise NotFound("Thing not found.")

    executor = make_executor()
    stream = make_stream()
    op = FakeOp(body=body)
    subscribe(stream, op)

    await executor.run_all(stream)

    (frame,) = await drain(stream.queue)
    assert frame.data["error"]["code"] == "not_found"
    assert op.calls == 1


async def test_a_stream_closed_while_waiting_to_try_again_runs_nothing_more(make_executor):
    executor = make_executor()
    stream = make_stream()
    op = FakeOp(body=busy_for(10, retry_after=0.3))
    subscribe(stream, op)
    asyncio.get_running_loop().call_later(0.1, stream.close)

    await executor.run_all(stream)

    assert op.calls == 1
    assert [frame.event for frame in await drain(stream.queue)] == ["bye"]


async def test_a_result_after_an_error_is_sent_even_if_it_equals_the_one_before(make_executor):
    state = {"fail": False}

    def body(ctx, params):
        if state["fail"]:
            raise NotFound("Gone for a moment.")
        return ThingListOut(rows=[thing(1)])

    executor = make_executor()
    stream = make_stream()
    subscribe(stream, FakeOp(body=body))
    await executor.run_all(stream)
    state["fail"] = True
    await executor.run_all(stream)
    state["fail"] = False
    await executor.run_all(stream)

    frames = await drain(stream.queue)
    assert [(f.event, f.data.get("rev")) for f in frames] == [("result", 1), ("error", None), ("result", 2)]
