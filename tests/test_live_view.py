"""``/api/live``: one SSE stream per tab, its frames, its errors and its scope isolation (plan §4.1)."""

import json
import re

import psycopg
import pytest
from asgiref.sync import sync_to_async
from django.db import connection
from django.http import Http404
from django.test import AsyncRequestFactory
from live import live_view
from live.broker import broker
from live.context import OperationContext, Scope
from live.executor import executor
from live.operations import registry

from tests.live_helpers import StreamReader, create_thing, encode_subs, eventually, host_client
from tests.testapp import queries as _testapp_queries  # noqa: F401  (registers testapp operations)
from tests.testapp import services as _testapp_services  # noqa: F401
from tests.testapp.live_context import LiveTestContextBuilder
from tests.testapp.schemas import ThingIn

pytestmark = pytest.mark.django_db(transaction=True)

BUILDER = "tests.testapp.live_context.LiveTestContextBuilder"
LIST = {"id": "list", "op": "testapp.thing.list", "params": {}}


@pytest.fixture(autouse=True)
def live_settings(settings):
    settings.LIVE = {**settings.LIVE, "context_builder": BUILDER}
    settings.ALLOWED_HOSTS = [".localhost", "testserver"]
    LiveTestContextBuilder.reset()
    yield
    LiveTestContextBuilder.reset()


@pytest.fixture(autouse=True)
async def clean_live():
    yield
    await broker.reset()
    executor.reset()


@pytest.fixture
def client():
    return host_client()


@pytest.fixture
async def readers():
    opened: list[StreamReader] = []
    yield opened
    for reader in opened:
        await reader.disconnect()


@pytest.fixture
async def pg(db_dsn):
    conn = await psycopg.AsyncConnection.connect(db_dsn, autocommit=True)
    yield conn
    await conn.close()


def headers_for(host="a.localhost", user="ana", permissions="testapp.view"):
    headers = {"host": host}
    if user:
        headers["X-Test-User"] = user
    if permissions:
        headers["X-Test-Permissions"] = permissions
    return headers


async def open_stream(client, readers, subs, **who):
    response = await client.get("/api/live", {"s": encode_subs(subs)}, headers=headers_for(**who))
    assert response.status_code == 200, response.content
    reader = StreamReader(response).start()
    readers.append(reader)
    return response, reader


async def open_and_settle(client, readers, subs, **who):
    """Open a stream and read its hello and one initial frame per subscription."""
    response, reader = await open_stream(client, readers, subs, **who)
    hello = await reader.next()
    assert hello.event == "hello"
    initial = [await reader.next_data_frame() for _ in subs]
    return response, reader, initial


def names(frame):
    return [row["name"] for row in frame.data["data"]["rows"]]


@sync_to_async
def run_create(scope_key: str, name: str, actor="bob"):
    """Run the testapp command as a real write: its own transaction, NOTIFY after the COMMIT."""
    ctx = OperationContext(scope=Scope("host", scope_key), actor=actor, permissions=frozenset({"testapp.manage"}))
    try:
        return registry["testapp.thing.create"](ctx, ThingIn(name=name))
    finally:
        connection.close()


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


# Opening the stream


async def test_hello_then_initial_results_for_every_subscription(client, readers):
    await create_thing("one")
    await create_thing("two")
    first = {"id": "first", "op": "testapp.thing.list", "params": {"limit": 1}}

    response, reader = await open_stream(client, readers, [LIST, first])

    assert response.streaming
    assert response["Content-Type"] == "text/event-stream"
    assert response["Cache-Control"] == "no-store"
    assert response["X-Accel-Buffering"] == "no"
    hello = await reader.next()
    assert hello.event == "hello"
    assert re.fullmatch(r"[0-9a-f]{32}", hello.data["stream"])
    results = [await reader.next(), await reader.next()]
    assert [(f.event, f.data["id"], f.data["rev"], names(f)) for f in results] == [
        ("result", "list", 1, ["one", "two"]),
        ("result", "first", 1, ["one"]),
    ]
    assert [stream.id for stream in broker.streams_for("live_host_a")] == [hello.data["stream"]]


async def test_retry_3000_is_sent_once(client, readers, monkeypatch):
    monkeypatch.setattr(live_view, "HEARTBEAT_EVERY", 0.05)

    _, reader = await open_stream(client, readers, [LIST])
    frames = [await reader.next() for _ in range(4)]

    assert [f.event for f in frames] == ["hello", "result", "heartbeat", "heartbeat"]
    assert frames[0].retry == 3000
    assert [f.retry for f in frames[1:]] == [None, None, None]
    assert sum(f.raw.count(b"retry:") for f in frames) == 1


async def test_heartbeat_after_idle_with_an_injected_clock(client, readers, monkeypatch):
    monkeypatch.setattr(live_view, "HEARTBEAT_EVERY", 0.05)

    _, reader, _ = await open_and_settle(client, readers, [LIST])
    heartbeat = await reader.next(timeout=1.0)

    assert heartbeat.event == "heartbeat"
    assert heartbeat.data == {}


async def test_heartbeat_is_15_seconds_by_default():
    assert live_view.HEARTBEAT_EVERY == 15.0
    assert live_view.SAFETY_RERUN_EVERY == 300.0


async def test_safety_rerun_every_300s_with_an_injected_clock(client, readers, monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(live_view, "clock", clock)
    monkeypatch.setattr(live_view, "HEARTBEAT_EVERY", 0.02)
    _, reader, (initial,) = await open_and_settle(client, readers, [LIST])
    assert names(initial) == []

    await create_thing("missed")  # written without any notification (as if the NOTIFY was lost)
    clock.now += 299
    assert await reader.nothing_within(0.2) == []

    clock.now += 2
    frame = await reader.next_data_frame()

    assert (frame.event, frame.data["rev"], names(frame)) == ("result", 2, ["missed"])


# Errors of one subscription keep the stream


async def test_unknown_operation_errors_its_id_but_keeps_the_stream(client, readers):
    ghost = {"id": "ghost", "op": "nope.thing.list", "params": {}}

    _, reader = await open_stream(client, readers, [ghost, LIST])
    frames = [await reader.next() for _ in range(3)]

    assert [f.event for f in frames] == ["hello", "error", "result"]
    assert frames[1].data["id"] == "ghost"
    assert frames[1].data["error"]["code"] == "unknown_operation"
    assert frames[2].data["id"] == "list"


@pytest.mark.parametrize("op", ["testapp.thing.create", "testapp.thing.sneaky_write"])
async def test_a_command_or_a_query_that_is_not_live_is_not_subscribable(client, readers, op):
    _, reader = await open_stream(client, readers, [{"id": "x", "op": op, "params": {"name": "n"}}, LIST])
    frames = [await reader.next() for _ in range(3)]

    assert [f.event for f in frames] == ["hello", "error", "result"]
    assert frames[1].data["id"] == "x"
    assert frames[1].data["error"]["code"] == "not_subscribable"


async def test_invalid_params_error_that_id(client, readers):
    too_many = {"id": "big", "op": "testapp.thing.list", "params": {"limit": 500}}

    _, reader = await open_stream(client, readers, [too_many, LIST])
    frames = [await reader.next() for _ in range(3)]

    assert [f.event for f in frames] == ["hello", "error", "result"]
    error = frames[1].data
    assert error["id"] == "big"
    assert error["error"]["code"] == "invalid_payload"
    assert set(error["error"]["fields"]) == {"limit"}
    assert frames[2].data["id"] == "list"


# Requests that never become a stream


async def test_no_actor_is_401_envelope_not_a_stream(client):
    response = await client.get("/api/live", {"s": encode_subs([LIST])}, headers=headers_for(user=None))

    assert response.status_code == 401
    assert not response.streaming
    assert response["Content-Type"] == "application/json"
    assert json.loads(response.content)["error"]["code"] == "unauthorized"
    assert broker.channel_count() == 0


@pytest.mark.parametrize(
    ("s", "code"),
    [
        (None, "invalid_subscriptions"),
        ("!!!", "invalid_subscriptions"),
        (encode_subs({"id": "x"}), "invalid_subscriptions"),
        (encode_subs([{"id": f"s{i}", "op": "testapp.thing.list", "params": {}} for i in range(51)]), "too_many_subscriptions"),
    ],
)
async def test_bad_s_param_is_400(client, s, code):
    data = {} if s is None else {"s": s}

    response = await client.get("/api/live", data, headers=headers_for())

    assert response.status_code == 400
    assert not response.streaming
    assert json.loads(response.content)["error"]["code"] == code
    assert broker.channel_count() == 0


async def test_a_host_that_is_no_scope_is_a_404_envelope(client, monkeypatch):
    # A builder that rejects the Host (hub-next: a reserved or invalid hub slug) raises Http404.
    def no_such_scope(self, request):
        raise Http404("www is not a hub")

    monkeypatch.setattr(LiveTestContextBuilder, "from_request", no_such_scope)
    response = await client.get("/api/live", {"s": encode_subs([LIST])}, headers=headers_for())

    assert response.status_code == 404
    assert not response.streaming
    assert response["Content-Type"] == "application/json"
    assert json.loads(response.content)["error"]["code"] == "not_found"
    assert broker.channel_count() == 0


async def test_only_get_opens_a_stream(client):
    response = await client.post("/api/live", {}, headers=headers_for())

    assert response.status_code == 405
    assert response["Allow"] == "GET"
    assert json.loads(response.content)["error"]["code"] == "method_not_allowed"


# Scope isolation and delivery after the COMMIT


async def test_a_write_in_scope_a_is_not_seen_by_a_stream_of_scope_b(client, readers, pg):
    _, reader_a, _ = await open_and_settle(client, readers, [LIST], host="a.localhost")
    _, reader_b, _ = await open_and_settle(client, readers, [LIST], host="b.localhost")

    await run_create("a", "from a")  # a command of scope A: outbox, COMMIT, pg_notify on live_host_a

    frame = await reader_a.next_data_frame()
    assert (frame.event, frame.data["rev"], names(frame)) == ("result", 2, ["from a"])
    assert await reader_b.nothing_within(1.0) == []

    await create_thing("raw")
    await pg.execute("SELECT pg_notify('live_host_a', '{\"events\":[\"testapp.thing.created\"]}')")

    frame = await reader_a.next_data_frame()
    assert (frame.data["rev"], names(frame)) == (3, ["from a", "raw"])
    assert await reader_b.nothing_within(1.0) == []


async def test_a_commit_in_scope_a_reaches_two_streams_of_a(client, readers):
    _, first, _ = await open_and_settle(client, readers, [LIST])
    _, second, _ = await open_and_settle(client, readers, [LIST])

    await run_create("a", "shared")

    for reader in (first, second):
        frame = await reader.next_data_frame()
        assert (frame.event, frame.data["id"], frame.data["rev"], names(frame)) == ("result", "list", 2, ["shared"])


async def test_permission_revoked_mid_stream_errors_that_subscription(client, readers):
    _, reader, _ = await open_and_settle(client, readers, [LIST], user="ana")

    LiveTestContextBuilder.revoked.add("ana")
    await run_create("a", "secret")

    frame = await reader.next_data_frame()
    assert frame.event == "error"
    assert frame.data["id"] == "list"
    assert frame.data["error"]["code"] == "permission_denied"
    (stream,) = broker.streams_for("live_host_a")
    assert stream.subs == {}


async def test_a_signed_out_user_gets_bye_and_the_stream_ends(client, readers):
    _, reader, _ = await open_and_settle(client, readers, [LIST], user="ana")

    LiveTestContextBuilder.signed_out.add("ana")
    await run_create("a", "after logout")

    frame = await reader.next_data_frame()
    assert frame.event == "bye"
    await eventually(reader.ended.is_set)
    assert broker.channel_count() == 0


# Closing the stream


async def test_disconnect_unregisters_the_stream(client, readers):
    _, reader, _ = await open_and_settle(client, readers, [LIST])
    assert broker.channel_count() == 1
    assert broker.listener.channels == {"live_host_a": 1}

    await reader.disconnect()  # what Django's ASGI handler does when the client goes away

    assert broker.channel_count() == 0
    await broker.listener.wait_synced()
    assert broker.listener.channels == {}
    assert broker.listener.listened == set()


async def test_a_cancelled_response_releases_the_stream_even_without_close(readers):
    """Without the test client's wrapper nobody calls response.close(): the cancellation alone releases."""
    request = AsyncRequestFactory().get(
        "/api/live", {"s": encode_subs([LIST])}, headers={"X-Test-User": "ana", "X-Test-Permissions": "testapp.view"}
    )
    response = await live_view.live_stream(request)
    reader = StreamReader(response).start()
    readers.append(reader)
    assert (await reader.next()).event == "hello"
    await reader.next_data_frame()
    assert broker.channel_count() == 1

    await reader.disconnect()

    assert broker.channel_count() == 0


async def test_response_close_releases_the_stream(client, readers):
    response, _, _ = await open_and_settle(client, readers, [LIST])

    await sync_to_async(response.close)()  # Django closes the response after a disconnect, in a thread

    await eventually(lambda: broker.channel_count() == 0)
    assert broker.listener.channels == {}


async def test_a_server_side_close_sends_bye_and_unregisters(client, readers):
    _, reader, _ = await open_and_settle(client, readers, [LIST])
    (stream,) = broker.streams_for("live_host_a")

    stream.close()  # e.g. the client is too slow and its queue overflowed

    frame = await reader.next_data_frame()
    assert frame.event == "bye"
    await eventually(reader.ended.is_set)
    assert broker.channel_count() == 0
