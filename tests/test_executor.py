"""Executor of live queries: hash dedup, rev, debounce, one run per scope, errors (plan §4.1)."""

import asyncio
import contextlib
import contextvars
import threading
import time

import psycopg
import pytest
from django.utils.translation import gettext, gettext_lazy
from live import executor as executor_module
from live.context import OperationContext, Scope
from live.errors import AppInactive, NotFound, PermissionDenied, Unauthorized
from live.executor import BYE_FRAME, QUEUE_MAX, Executor, Stream, Subscription
from live.operations import registry
from live.sse import MAX_RESULT_BYTES

from tests.live_helpers import drain, next_queued, parse_frame
from tests.testapp import queries as _testapp_queries  # noqa: F401  (registers testapp operations)
from tests.testapp.live_context import LiveTestContextBuilder
from tests.testapp.schemas import ThingListIn, ThingListOut

BUILDER = "tests.testapp.live_context.LiveTestContextBuilder"
SCOPE_A = Scope("host", "a")
SCOPE_B = Scope("host", "b")


@pytest.fixture(autouse=True)
def live_builder(settings):
    settings.LIVE = {**settings.LIVE, "context_builder": BUILDER}
    LiveTestContextBuilder.reset()
    yield
    LiveTestContextBuilder.reset()


@pytest.fixture
def make_executor():
    created = []

    def make(**options):
        options.setdefault("debounce", 0.05)
        executor = Executor(**options)
        created.append(executor)
        return executor

    yield make
    for executor in created:
        executor.reset()
        executor.shutdown()


class FakeOp:
    """An operation stand-in that never touches the database; ``rows`` is what it returns."""

    def __init__(self, name="testapp.thing.list", *, permission="testapp.view", rows=None, body=None):
        self.name = name
        self.kind = "query"
        self.permission = permission
        self.rows = rows if rows is not None else []
        self.body = body
        self.calls = 0
        self._lock = threading.Lock()

    def __call__(self, ctx, params):
        if not ctx.has(self.permission):
            raise PermissionDenied(f"Permission {self.permission!r} is required.")
        with self._lock:
            self.calls += 1
        if self.body is not None:
            return self.body(ctx, params)
        return ThingListOut(rows=list(self.rows))


def make_stream(scope=SCOPE_A, *, actor="ana", permissions=("testapp.view",), maxsize=None, language="en"):
    ctx = OperationContext(scope=scope, actor=actor, permissions=frozenset(permissions), language=language)
    return Stream(ctx) if maxsize is None else Stream(ctx, maxsize=maxsize)


def subscribe(stream, op, sub_id="s1", params=None):
    sub = Subscription(id=sub_id, op=op, params=params or ThingListIn())
    stream.subs[sub.id] = sub
    return sub


def thing(id, name="x"):
    return {"id": id, "name": name}


# Stream


def test_a_stream_has_a_uuid7_hex_id_and_its_scope_channel():
    stream = make_stream()

    assert len(stream.id) == 32 and int(stream.id, 16)
    assert stream.id[12] == "7"  # UUID version nibble
    assert stream.scope == SCOPE_A
    assert stream.channel == SCOPE_A.channel
    assert stream.queue.maxsize == QUEUE_MAX == 256


async def test_queue_overflow_sends_a_single_bye_and_closes_the_stream():
    stream = make_stream(maxsize=3)

    for i in range(5):
        stream.put(f"event: result\ndata: {{\"n\":{i}}}\n\n".encode())

    assert stream.closed
    assert [stream.queue.get_nowait()] == [BYE_FRAME]
    assert stream.queue.empty()
    stream.put(b"event: result\ndata: {}\n\n")
    assert stream.queue.empty()


async def test_close_queues_one_bye():
    stream = make_stream()
    stream.put(b"event: result\ndata: {}\n\n")

    stream.close()
    stream.close()

    assert stream.closed
    assert await drain(stream.queue) == [parse_frame(BYE_FRAME)]


# Results


async def test_run_all_sends_one_result_per_subscription(make_executor):
    executor = make_executor()
    stream = make_stream()
    subscribe(stream, FakeOp(rows=[thing(1)]), "s1")
    subscribe(stream, FakeOp(rows=[thing(1), thing(2)]), "s2")

    await executor.run_all(stream)

    frames = await drain(stream.queue)
    assert [(f.event, f.data["id"], f.data["rev"], len(f.data["data"]["rows"])) for f in frames] == [
        ("result", "s1", 1, 1),
        ("result", "s2", 1, 2),
    ]
    assert frames[0].data["data"] == {"rows": [{"id": 1, "name": "x"}]}


async def test_unchanged_result_is_not_resent(make_executor):
    executor = make_executor()
    stream = make_stream()
    op = FakeOp(rows=[thing(1)])
    subscribe(stream, op)

    await executor.run_all(stream)
    await drain(stream.queue)
    await executor.run_all(stream)

    assert op.calls == 2
    assert stream.queue.empty()


async def test_changed_result_bumps_rev(make_executor):
    executor = make_executor()
    stream = make_stream()
    op = FakeOp(rows=[thing(1)])
    subscribe(stream, op)
    await executor.run_all(stream)
    await drain(stream.queue)

    op.rows = [thing(1), thing(2)]
    await executor.run_all(stream)

    (frame,) = await drain(stream.queue)
    assert frame.event == "result"
    assert frame.data["rev"] == 2
    assert frame.data["data"]["rows"] == [thing(1), thing(2)]


async def test_result_over_256_kb_is_an_error_frame_and_the_subscription_stays(make_executor):
    executor = make_executor()
    stream = make_stream()
    big = [thing(i, "x" * 1000) for i in range(300)]
    op = FakeOp(rows=big)
    subscribe(stream, op)

    await executor.run_all(stream)

    (frame,) = await drain(stream.queue)
    assert frame.event == "error"
    assert frame.data["id"] == "s1"
    assert frame.data["error"]["code"] == "result_too_large"
    assert len(frame.raw) < MAX_RESULT_BYTES
    assert "s1" in stream.subs

    await executor.run_all(stream)  # the same oversized result is not reported twice
    assert stream.queue.empty()

    op.rows = [thing(1)]
    await executor.run_all(stream)
    (frame,) = await drain(stream.queue)
    assert (frame.event, frame.data["rev"]) == ("result", 1)


# Errors


async def test_permission_revoked_mid_stream_errors_and_unsubscribes(make_executor):
    executor = make_executor()
    stream = make_stream(actor="ana")
    op = FakeOp(rows=[thing(1)])
    subscribe(stream, op, "s1")
    await executor.run_all(stream)
    await drain(stream.queue)

    LiveTestContextBuilder.revoked.add("ana")
    op.rows = [thing(1), thing(2)]
    await executor.on_events(stream, {"testapp.thing.created"})
    frame = await next_queued(stream.queue)

    assert frame.event == "error"
    assert frame.data == {
        "id": "s1",
        "error": {"code": "permission_denied", "message": "Permission 'testapp.view' is required."},
    }
    assert "s1" not in stream.subs

    await executor.run_all(stream)
    await executor.on_events(stream, {"testapp.thing.created"})
    await asyncio.sleep(0.15)
    assert op.calls == 1
    assert stream.queue.empty()


async def test_permissions_are_reread_before_every_run(make_executor):
    executor = make_executor()
    stream = make_stream()
    subscribe(stream, FakeOp())

    await executor.run_all(stream)
    await executor.run_all(stream)

    assert LiveTestContextBuilder.refreshes == 2


async def test_app_inactive_errors_and_unsubscribes(make_executor):
    def inactive(ctx, params):
        raise AppInactive("The app testapp is not active.")

    executor = make_executor()
    stream = make_stream()
    subscribe(stream, FakeOp(body=inactive))

    await executor.run_all(stream)

    (frame,) = await drain(stream.queue)
    assert frame.event == "error"
    assert frame.data["error"]["code"] == "app_inactive"
    assert stream.subs == {}


async def test_another_operation_error_keeps_the_subscription(make_executor):
    state = {"missing": True}

    def body(ctx, params):
        if state["missing"]:
            raise NotFound("Thing not found.")
        return ThingListOut(rows=[thing(1)])

    executor = make_executor()
    stream = make_stream()
    subscribe(stream, FakeOp(body=body))

    await executor.run_all(stream)
    (frame,) = await drain(stream.queue)
    assert frame.event == "error"
    assert frame.data["error"] == {"code": "not_found", "message": "Thing not found."}
    assert "s1" in stream.subs

    state["missing"] = False
    await executor.run_all(stream)
    (frame,) = await drain(stream.queue)
    assert (frame.event, frame.data["rev"]) == ("result", 1)


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


async def test_unexpected_exception_is_an_internal_error_and_keeps_the_subscription(make_executor, caplog):
    def boom(ctx, params):
        raise RuntimeError("database exploded")

    executor = make_executor()
    stream = make_stream()
    subscribe(stream, FakeOp(body=boom))

    await executor.run_all(stream)

    (frame,) = await drain(stream.queue)
    assert frame.event == "error"
    assert frame.data["error"]["code"] == "internal_error"
    assert "database exploded" not in frame.raw.decode()
    assert "s1" in stream.subs
    assert any("testapp.thing.list" in r.getMessage() and r.exc_info for r in caplog.records)


async def test_unauthorized_on_refresh_closes_the_stream_with_bye(make_executor):
    executor = make_executor()
    stream = make_stream(actor="ana")
    subscribe(stream, FakeOp(rows=[thing(1)]), "s1")
    subscribe(stream, FakeOp(rows=[thing(2)]), "s2")

    LiveTestContextBuilder.signed_out.add("ana")
    await executor.run_all(stream)

    assert stream.closed
    assert await drain(stream.queue) == [parse_frame(BYE_FRAME)]


async def test_close_old_connections_is_called_after_every_run(make_executor, monkeypatch):
    calls = []
    monkeypatch.setattr(executor_module, "close_old_connections", lambda: calls.append(threading.current_thread().name))

    def boom(ctx, params):
        raise RuntimeError("boom")

    executor = make_executor()
    stream = make_stream()
    subscribe(stream, FakeOp(rows=[thing(1)]), "ok")
    subscribe(stream, FakeOp(body=boom), "boom")

    await executor.run_all(stream)

    assert len(calls) == 2
    assert all(name != threading.main_thread().name for name in calls)


# Language: the worker thread speaks the stream's language (tests/testapp/locale/es/django.po)


async def test_run_one_activates_the_context_language(make_executor):
    def named(ctx, params):
        return ThingListOut(rows=[thing(1, gettext("Thing"))])

    executor = make_executor()
    spanish = make_stream(SCOPE_A, language="es")
    english = make_stream(SCOPE_B, language="en")
    subscribe(spanish, FakeOp(body=named))
    subscribe(english, FakeOp(body=named))

    await executor.run_all(spanish)
    await executor.run_all(english)

    (es_frame,) = await drain(spanish.queue)
    (en_frame,) = await drain(english.queue)
    assert es_frame.data["data"]["rows"] == [thing(1, "Cosa")]
    assert en_frame.data["data"]["rows"] == [thing(1, "Thing")]


async def test_error_frames_are_built_in_the_context_language(make_executor):
    def missing(ctx, params):
        # Lazy: it is only translated when the frame is serialised.
        raise NotFound(gettext_lazy("Thing not found."))

    executor = make_executor()
    spanish = make_stream(SCOPE_A, language="es")
    english = make_stream(SCOPE_B, language="en")
    subscribe(spanish, FakeOp(body=missing))
    subscribe(english, FakeOp(body=missing))

    await executor.run_all(spanish)
    await executor.run_all(english)

    (es_frame,) = await drain(spanish.queue)
    (en_frame,) = await drain(english.queue)
    assert es_frame.data["error"] == {"code": "not_found", "message": "Cosa no encontrada."}
    assert en_frame.data["error"] == {"code": "not_found", "message": "Thing not found."}


async def test_a_closed_stream_runs_nothing(make_executor):
    executor = make_executor()
    stream = make_stream()
    op = FakeOp()
    subscribe(stream, op)
    stream.closed = True

    await executor.run_all(stream)
    await executor.on_events(stream, {"testapp.thing.created"})
    await asyncio.sleep(0.1)

    assert op.calls == 0


# Events and debounce


async def test_events_rerun_only_the_affected_subscriptions(make_executor):
    executor = make_executor()
    stream = make_stream()
    affected = FakeOp(rows=[thing(1)])
    other = FakeOp("testapp.thing.other", rows=[thing(1)])
    subscribe(stream, affected, "s1")
    subscribe(stream, other, "s2")

    await executor.on_events(stream, {"testapp.thing.created"})
    frame = await next_queued(stream.queue)

    assert frame.data["id"] == "s1"
    assert (affected.calls, other.calls) == (1, 0)


async def test_star_reruns_every_live_subscription(make_executor, monkeypatch):
    from live.live_registry import live_registry

    monkeypatch.setitem(live_registry.subscribable, "testapp.thing.other", ["testapp.thing.renamed"])
    monkeypatch.setattr(live_registry, "_by_event", None)
    executor = make_executor()
    stream = make_stream()
    first, second = FakeOp(), FakeOp("testapp.thing.other")
    subscribe(stream, first, "s1")
    subscribe(stream, second, "s2")

    await executor.on_events(stream, {"*"})
    await next_queued(stream.queue)
    await next_queued(stream.queue)

    assert (first.calls, second.calls) == (1, 1)


async def test_an_unrelated_event_runs_nothing(make_executor):
    executor = make_executor()
    stream = make_stream()
    op = FakeOp()
    subscribe(stream, op)

    await executor.on_events(stream, {"other.thing.created"})
    await asyncio.sleep(0.15)

    assert op.calls == 0


async def test_a_burst_within_the_debounce_runs_once(make_executor):
    executor = make_executor(debounce=0.15)
    stream = make_stream()
    op = FakeOp(rows=[thing(1)])
    subscribe(stream, op)

    for _ in range(5):
        await executor.on_events(stream, {"testapp.thing.created"})
        await asyncio.sleep(0.02)
    assert op.calls == 0
    await next_queued(stream.queue)
    await asyncio.sleep(0.25)

    assert op.calls == 1
    assert stream.queue.empty()


async def test_max_debounce_caps_a_never_ending_burst(make_executor):
    executor = make_executor(debounce=0.1, max_debounce=0.25)
    stream = make_stream()
    op = FakeOp()
    subscribe(stream, op)

    started = time.monotonic()
    while time.monotonic() - started < 0.7:
        await executor.on_events(stream, {"testapp.thing.created"})
        await asyncio.sleep(0.03)

    assert op.calls >= 2


async def test_forget_cancels_a_pending_rerun(make_executor):
    executor = make_executor(debounce=0.1)
    stream = make_stream()
    op = FakeOp()
    subscribe(stream, op)

    await executor.on_events(stream, {"testapp.thing.created"})
    executor.forget(stream)
    await asyncio.sleep(0.2)

    assert op.calls == 0


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
    # accounts.session.list of saas-next is live on the session event itself: its run already re-reads the context.
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
    # hub-next's cash_register.session.closed and table.session.closed are a till's and a table's, not a sign-in's.
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


def _holding_the_scope(executor, scope=SCOPE_A, seconds=0.3):
    """A stream of ``scope`` whose run keeps the scope's gate for ``seconds``; its task, to await at the end."""
    holder = make_stream(scope, actor="bo")
    subscribe(holder, FakeOp(body=lambda ctx, params: time.sleep(seconds) or ThingListOut(rows=[])))
    return asyncio.ensure_future(executor.run_all(holder))


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


# Concurrency


async def test_one_run_at_a_time_per_scope_and_scopes_in_parallel(make_executor):
    lock = threading.Lock()
    active: dict[str, int] = {}
    peak: dict[str, int] = {}
    peak_total = [0]

    def slow(ctx, params):
        key = ctx.scope.key
        with lock:
            active[key] = active.get(key, 0) + 1
            peak[key] = max(peak.get(key, 0), active[key])
            peak_total[0] = max(peak_total[0], sum(active.values()))
        time.sleep(0.1)
        with lock:
            active[key] -= 1
        return ThingListOut(rows=[])

    executor = make_executor(max_workers=3)
    streams = [make_stream(SCOPE_A), make_stream(SCOPE_A), make_stream(SCOPE_B), make_stream(SCOPE_B)]
    for stream in streams:
        subscribe(stream, FakeOp(body=slow), "s1")
        subscribe(stream, FakeOp(body=slow), "s2")

    started = time.monotonic()
    await asyncio.gather(*(executor.run_all(stream) for stream in streams))
    elapsed = time.monotonic() - started

    assert peak == {"a": 1, "b": 1}
    assert peak_total[0] == 2
    assert elapsed < 0.7  # 4 runs of 0.1 s per scope in sequence, both scopes side by side (~0.4 s)


async def test_a_subscription_dropped_while_waiting_for_the_scope_does_not_run(make_executor):
    executor = make_executor()
    holding = _holding_the_scope(executor)
    await asyncio.sleep(0.05)
    stream = make_stream(actor="ana")
    op = FakeOp()
    subscribe(stream, op)

    running = asyncio.ensure_future(executor.run_all(stream))
    await asyncio.sleep(0.05)  # waiting for the scope
    del stream.subs["s1"]  # the tab unsubscribed it meanwhile
    await asyncio.gather(holding, running)

    assert op.calls == 0


async def test_a_stream_closed_while_waiting_for_the_scope_runs_nothing(make_executor):
    executor = make_executor()
    holding = _holding_the_scope(executor)
    await asyncio.sleep(0.05)
    stream = make_stream(actor="ana")
    op = FakeOp()
    subscribe(stream, op)

    running = asyncio.ensure_future(executor.run_all(stream))
    await asyncio.sleep(0.05)  # waiting for the scope
    stream.close()  # the client went away
    await asyncio.gather(holding, running)

    assert op.calls == 0


async def test_a_cancelled_waiter_keeps_the_scope_serialized(make_executor):
    lock = threading.Lock()
    active = [0, 0]

    def slow(ctx, params):
        with lock:
            active[0] += 1
            active[1] = max(active[1], active[0])
        time.sleep(0.15)
        with lock:
            active[0] -= 1
        return ThingListOut(rows=[])

    executor = make_executor()
    first, second = make_stream(), make_stream()
    subscribe(first, FakeOp(body=slow))
    subscribe(second, FakeOp(body=slow))

    task = asyncio.ensure_future(executor.run_all(first))
    await asyncio.sleep(0.05)
    task.cancel()  # the client went away while its query runs in a thread
    await executor.run_all(second)

    assert active[1] == 1


# Real operation, real threads


@pytest.mark.django_db(transaction=True)
async def test_threads_do_not_leak_database_connections(make_executor, db_dsn):
    executor = make_executor()
    stream = make_stream()
    subscribe(stream, registry["testapp.thing.list"])

    async with await psycopg.AsyncConnection.connect(db_dsn, autocommit=True) as probe:
        query = "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
        before = (await (await probe.execute(query)).fetchone())[0]
        for _ in range(50):
            await executor.run_all(stream)
        after = (await (await probe.execute(query)).fetchone())[0]

    frames = await drain(stream.queue)
    assert [(f.event, f.data["data"]) for f in frames] == [("result", {"rows": []})]
    assert after <= before


# A builder that enters a context around each run (hub-next phase 2: use_hub of the stream's hub)

ENTERING_BUILDER = "tests.test_executor.EnteringBuilder"
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
