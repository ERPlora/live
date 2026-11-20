"""Executor of live queries: the context of a stream, re-read when its session may have ended and entered around every
run."""

import asyncio
import contextlib
import contextvars
import threading

import pytest
from live import executor as executor_module
from live.context import Scope
from live.errors import OperationError, Unauthorized
from live.executor import BYE_FRAME

from tests.live_helpers import drain, next_queued, parse_frame
from tests.test_executor import (  # noqa: F401 - live_builder, its autouse fixture, sets these tests up too
    SCOPE_A,
    SCOPE_B,
    FakeOp,
    _holding_the_scope,
    live_builder,
    make_stream,
    subscribe,
    thing,
)
from tests.testapp.live_context import LiveTestContextBuilder
from tests.testapp.schemas import ThingListOut


# Session events (LIVE["session_events"]): the stream re-reads its context, no query has to declare them

SESSION_CLOSED = "testapp.session.closed"


@pytest.fixture
def session_events(settings):
    settings.LIVE = {**settings.LIVE, "session_events": [SESSION_CLOSED]}


@pytest.mark.usefixtures("session_events")
async def test_a_session_event_ends_a_stream_whose_session_ended_though_no_query_declares_it(make_executor):
    executor = make_executor()
    stream = make_stream(actor="ana")
    op = FakeOp(rows=[thing(1)])  # testapp.thing.list: live on testapp.thing.created only
    subscribe(stream, op)
    LiveTestContextBuilder.signed_out.add("ana")

    await executor.on_events(stream, {SESSION_CLOSED})

    assert await next_queued(stream.queue) == parse_frame(BYE_FRAME)
    assert stream.closed
    assert op.calls == 0


@pytest.mark.usefixtures("session_events")
async def test_a_session_event_rereads_the_context_once_and_reruns_nothing_while_the_session_lives(make_executor):
    executor = make_executor()
    stream = make_stream(actor="ana")
    first, second = FakeOp(rows=[thing(1)]), FakeOp("testapp.thing.other", rows=[thing(2)])
    subscribe(stream, first, "s1")
    subscribe(stream, second, "s2")

    await executor.on_events(stream, {SESSION_CLOSED})
    await asyncio.sleep(0.2)

    assert LiveTestContextBuilder.refreshes == 1
    assert (first.calls, second.calls) == (0, 0)
    assert not stream.closed
    assert stream.queue.empty()


@pytest.mark.usefixtures("session_events")
async def test_a_stream_without_subscriptions_also_ends_with_its_session(make_executor):
    executor = make_executor()
    stream = make_stream(actor="ana")
    LiveTestContextBuilder.signed_out.add("ana")

    await executor.on_events(stream, {SESSION_CLOSED})

    assert await next_queued(stream.queue) == parse_frame(BYE_FRAME)


@pytest.mark.usefixtures("session_events")
async def test_a_burst_of_session_events_rereads_the_context_once(make_executor):
    executor = make_executor(debounce=0.15)
    stream = make_stream(actor="ana")
    subscribe(stream, FakeOp())

    for _ in range(5):
        await executor.on_events(stream, {SESSION_CLOSED})
        await asyncio.sleep(0.02)
    assert LiveTestContextBuilder.refreshes == 0
    await asyncio.sleep(0.3)

    assert LiveTestContextBuilder.refreshes == 1


@pytest.mark.usefixtures("session_events")
async def test_a_session_event_joining_a_pending_burst_still_rereads_the_context(make_executor):
    executor = make_executor(debounce=0.1)
    stream = make_stream(actor="ana")
    subscribe(stream, FakeOp())
    LiveTestContextBuilder.signed_out.add("ana")

    await executor.on_events(stream, {"testapp.thing.created"})
    del stream.subs["s1"]  # dropped before the burst runs (its permission was revoked by another run)
    await executor.on_events(stream, {SESSION_CLOSED})

    assert await next_queued(stream.queue) == parse_frame(BYE_FRAME)


async def test_a_session_event_that_reruns_a_query_rereads_the_context_through_that_run(make_executor, settings):
    # The SaaS's accounts.session.list is live on the session event itself: its run already re-reads the context.
    settings.LIVE = {**settings.LIVE, "session_events": ["testapp.thing.created"]}
    executor = make_executor()
    stream = make_stream(actor="ana")
    op = FakeOp(rows=[thing(1)])
    subscribe(stream, op)

    await executor.on_events(stream, {"testapp.thing.created"})
    await next_queued(stream.queue)
    await asyncio.sleep(0.1)

    assert (op.calls, LiveTestContextBuilder.refreshes) == (1, 1)


@pytest.mark.usefixtures("session_events")
async def test_an_event_is_never_taken_for_a_session_end_by_its_name(make_executor):
    # The Hub's cash_register.session.closed and table.session.closed are a till's and a table's, not a sign-in's.
    executor = make_executor()
    stream = make_stream(actor="ana")
    subscribe(stream, FakeOp())
    LiveTestContextBuilder.signed_out.add("ana")

    await executor.on_events(stream, {"cash_register.session.closed", "table.session.closed"})
    await asyncio.sleep(0.15)

    assert LiveTestContextBuilder.refreshes == 0
    assert not stream.closed


async def test_without_session_events_no_event_rereads_the_context(make_executor):
    executor = make_executor()
    stream = make_stream(actor="ana")
    subscribe(stream, FakeOp())
    LiveTestContextBuilder.signed_out.add("ana")

    await executor.on_events(stream, {SESSION_CLOSED})
    await asyncio.sleep(0.15)

    assert LiveTestContextBuilder.refreshes == 0
    assert not stream.closed


@pytest.mark.usefixtures("session_events")
async def test_a_session_reread_that_fails_is_logged_and_keeps_the_stream(make_executor, monkeypatch, caplog):
    def broken(self, ctx):
        raise RuntimeError("the session store is down")

    monkeypatch.setattr(LiveTestContextBuilder, "refresh", broken)
    executor = make_executor()
    stream = make_stream(actor="ana")
    subscribe(stream, FakeOp())

    await executor.on_events(stream, {SESSION_CLOSED})
    await asyncio.sleep(0.15)

    assert not stream.closed
    assert stream.queue.empty()
    assert f"Re-reading the context of live stream {stream.id} failed." in caplog.text


@pytest.mark.usefixtures("session_events")
async def test_a_session_reread_that_finds_the_scope_busy_is_a_warning_without_a_trace(make_executor, monkeypatch, caplog):
    def busy(self, ctx):
        raise OperationError("Busy for a moment.", code="busy", status=503, retry_after=1)

    monkeypatch.setattr(LiveTestContextBuilder, "refresh", busy)
    executor = make_executor()
    stream = make_stream(actor="ana")
    subscribe(stream, FakeOp())

    await executor.on_events(stream, {SESSION_CLOSED})
    await asyncio.sleep(0.15)

    (record,) = [record for record in caplog.records if str(stream.id) in record.getMessage()]
    assert record.levelname == "WARNING"
    assert record.exc_info is None
    assert "Busy for a moment." in record.getMessage()
    assert not stream.closed


@pytest.mark.usefixtures("session_events")
async def test_close_old_connections_is_called_after_a_session_reread(make_executor, monkeypatch):
    calls = []
    monkeypatch.setattr(executor_module, "close_old_connections", lambda: calls.append(threading.current_thread().name))
    executor = make_executor()
    stream = make_stream(actor="ana")
    subscribe(stream, FakeOp())

    await executor.on_events(stream, {SESSION_CLOSED})
    await asyncio.sleep(0.15)

    assert len(calls) == 1
    assert calls[0] != threading.main_thread().name


@pytest.mark.usefixtures("session_events")
async def test_a_data_event_joining_a_pending_session_event_keeps_the_reread(make_executor):
    executor = make_executor(debounce=0.1)
    stream = make_stream(actor="ana")
    subscribe(stream, FakeOp())
    LiveTestContextBuilder.signed_out.add("ana")

    await executor.on_events(stream, {SESSION_CLOSED})
    await executor.on_events(stream, {"testapp.thing.created"})  # joins the burst: its run would re-read the context
    del stream.subs["s1"]  # but it goes away before the burst runs

    assert await next_queued(stream.queue) == parse_frame(BYE_FRAME)


@pytest.mark.usefixtures("session_events")
async def test_a_session_event_whose_query_goes_away_while_waiting_for_the_scope_still_rereads(make_executor):
    # The session event and a data event of the subscribed query arrive together: that query's run would be the
    # re-read, but the tab unsubscribes it while the run waits for the scope (another stream's query holds it).
    executor = make_executor(debounce=0.05)
    holding = _holding_the_scope(executor)
    await asyncio.sleep(0.05)
    stream = make_stream(actor="ana")
    subscribe(stream, FakeOp())
    LiveTestContextBuilder.signed_out.add("ana")

    await executor.on_events(stream, {SESSION_CLOSED, "testapp.thing.created"})
    await asyncio.sleep(0.1)  # the burst ran out; its only run is waiting for the scope
    del stream.subs["s1"]

    assert await next_queued(stream.queue) == parse_frame(BYE_FRAME)
    await holding


@pytest.mark.usefixtures("session_events")
async def test_a_session_reread_of_a_stream_closed_while_waiting_for_the_scope_is_skipped(make_executor):
    executor = make_executor(debounce=0.05)
    holding = _holding_the_scope(executor)
    await asyncio.sleep(0.05)
    stream = make_stream(actor="ana")
    subscribe(stream, FakeOp())

    await executor.on_events(stream, {SESSION_CLOSED})
    await asyncio.sleep(0.1)  # the re-read is waiting for the scope
    stream.close()  # the client went away
    await holding
    await asyncio.sleep(0.05)

    assert LiveTestContextBuilder.refreshes == 1  # the holder's run only


@pytest.mark.usefixtures("session_events")
async def test_forget_cancels_a_pending_session_reread(make_executor):
    executor = make_executor(debounce=0.1)
    stream = make_stream(actor="ana")
    subscribe(stream, FakeOp())

    await executor.on_events(stream, {SESSION_CLOSED})
    executor.forget(stream)
    await asyncio.sleep(0.2)

    assert LiveTestContextBuilder.refreshes == 0


# A builder that enters a context around each run (the Hub: use_hub of the stream's hub)

ENTERING_BUILDER = "tests.test_executor_context.EnteringBuilder"
_entered_scope: "contextvars.ContextVar[Scope | None]" = contextvars.ContextVar("entered_scope", default=None)


class EnteringBuilder(LiveTestContextBuilder):
    """``enter(ctx)``: the context each run of a stream goes into, in the executor's thread (a thread of its own
    starts without the request's context vars)."""

    __test__ = False
    closed: set[str] = set()
    order: list[str] = []

    def enter(self, ctx):
        if ctx.scope.key in self.closed:
            raise Unauthorized("This host stopped serving the app.")
        return self._entered(ctx.scope)

    @contextlib.contextmanager
    def _entered(self, scope):
        token = _entered_scope.set(scope)
        type(self).order.append("enter")
        try:
            yield
        finally:
            _entered_scope.reset(token)

    def refresh(self, ctx):
        type(self).order.append("refresh")
        return super().refresh(ctx)


@pytest.fixture
def entering_builder(settings):
    settings.LIVE = {**settings.LIVE, "context_builder": ENTERING_BUILDER}
    EnteringBuilder.closed = set()
    EnteringBuilder.order = []


@pytest.mark.usefixtures("entering_builder")
async def test_every_run_goes_into_the_context_the_builder_enters(make_executor):
    executor = make_executor()
    seen = []
    op = FakeOp(body=lambda ctx, params: seen.append(_entered_scope.get()) or ThingListOut(rows=[]))
    stream = make_stream(SCOPE_B)
    subscribe(stream, op)

    await executor.run_all(stream)

    assert seen == [SCOPE_B]
    assert _entered_scope.get() is None
    # Entered first: the refresh (which re-reads the registry, the user) runs inside it too.
    assert EnteringBuilder.order == ["enter", "refresh"]


@pytest.mark.usefixtures("entering_builder")
async def test_a_context_that_cannot_be_entered_ends_the_stream(make_executor):
    executor = make_executor()
    EnteringBuilder.closed = {"a"}
    op = FakeOp(rows=[thing(1)])
    stream = make_stream(SCOPE_A)
    subscribe(stream, op)

    await executor.run_all(stream)

    assert op.calls == 0
    assert stream.closed
    assert await drain(stream.queue) == [parse_frame(BYE_FRAME)]


@pytest.mark.usefixtures("entering_builder", "session_events")
async def test_a_session_reread_goes_into_the_context_the_builder_enters(make_executor):
    executor = make_executor()
    stream = make_stream(SCOPE_B, actor="ana")
    subscribe(stream, FakeOp())

    await executor.on_events(stream, {SESSION_CLOSED})
    await asyncio.sleep(0.15)

    assert EnteringBuilder.order == ["enter", "refresh"]
    assert not stream.closed


@pytest.mark.usefixtures("entering_builder", "session_events")
async def test_a_session_reread_whose_context_cannot_be_entered_ends_the_stream(make_executor):
    executor = make_executor()
    EnteringBuilder.closed = {"a"}
    stream = make_stream(SCOPE_A, actor="ana")
    subscribe(stream, FakeOp())

    await executor.on_events(stream, {SESSION_CLOSED})

    assert await next_queued(stream.queue) == parse_frame(BYE_FRAME)
