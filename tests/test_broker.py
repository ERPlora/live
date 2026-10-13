"""Broker and Listener: one LISTEN connection per process, refcounted channels, resync (plan §4.1).

Real Postgres: ``pg_listening_channels()`` is per session, so the LISTEN state is checked through
``Listener.listened`` plus what the server delivers, and the single connection through
``pg_stat_activity`` (``application_name = 'live-listener'``).
"""

import asyncio

import psycopg
import pytest
from live import broker as broker_module
from live.broker import APPLICATION_NAME, Broker, control_conninfo
from live.context import OperationContext, Scope
from live.errors import LiveMisuse
from live.executor import Executor, Stream, Subscription
from live.operations import registry
from psycopg.conninfo import conninfo_to_dict

from tests.live_helpers import create_thing, eventually, next_queued
from tests.testapp import queries as _testapp_queries  # noqa: F401  (registers testapp operations)
from tests.testapp.live_context import LiveTestContextBuilder
from tests.testapp.schemas import ThingListIn

CREATED = '{"events":["testapp.thing.created"]}'


class RecordingExecutor:
    """Records what the broker asks for instead of running queries."""

    def __init__(self):
        self.events: list[tuple[str, set[str]]] = []
        self.runs: list[str] = []

    async def on_events(self, stream, names):
        self.events.append((stream.id, set(names)))

    async def run_all(self, stream):
        self.runs.append(stream.id)


def make_stream(key="a", actor="ana"):
    return Stream(OperationContext(scope=Scope("host", key), actor=actor, permissions=frozenset({"testapp.view"})))


@pytest.fixture
async def make_broker():
    created = []

    def make(**options):
        options.setdefault("backoff", (0.01, 0.05))
        options.setdefault("executor", RecordingExecutor())
        broker = Broker(**options)
        created.append(broker)
        return broker

    yield make
    for broker in created:
        await broker.stop()


@pytest.fixture
async def pg(db_dsn):
    conn = await psycopg.AsyncConnection.connect(db_dsn, autocommit=True)
    yield conn
    await conn.close()


async def listener_pids(pg) -> list[int]:
    cursor = await pg.execute(
        "SELECT pid FROM pg_stat_activity WHERE application_name = %s AND datname = current_database()",
        [APPLICATION_NAME],
    )
    return [pid for (pid,) in await cursor.fetchall()]


async def notify(pg, channel, payload=CREATED):
    await pg.execute("SELECT pg_notify(%s, %s)", [channel, payload])


# Connection settings (no database needed)


def test_control_conninfo_is_built_from_the_database_settings():
    info = control_conninfo({
        "NAME": "control",
        "USER": "u",
        "PASSWORD": "p",
        "HOST": "db.internal",
        "PORT": 5433,
        "OPTIONS": {"sslmode": "require", "pool": True, "isolation_level": 1},
    })

    assert conninfo_to_dict(info) == {
        "dbname": "control",
        "user": "u",
        "password": "p",
        "host": "db.internal",
        "port": "5433",
        "sslmode": "require",
    }


def test_empty_host_and_port_are_left_to_libpq():
    info = control_conninfo({"NAME": "control", "USER": "u", "PASSWORD": "", "HOST": "", "PORT": ""})

    assert conninfo_to_dict(info) == {"dbname": "control", "user": "u"}


def test_control_conninfo_reads_the_control_alias(settings):
    settings.LIVE = {**settings.LIVE, "control_alias": "default"}

    assert conninfo_to_dict(control_conninfo())["dbname"] == settings.DATABASES["default"]["NAME"]


def test_an_unknown_control_alias_is_a_misuse(settings):
    settings.LIVE = {**settings.LIVE, "control_alias": "nowhere"}

    with pytest.raises(LiveMisuse, match="nowhere"):
        control_conninfo()


# One LISTEN connection per process

pytestmark_db = pytest.mark.django_db(transaction=True)


@pytestmark_db
async def test_the_listener_connects_lazily_with_the_first_stream(make_broker, pg):
    broker = make_broker()
    assert await listener_pids(pg) == []

    await broker.register(make_stream("a"))

    assert len(await listener_pids(pg)) == 1
    assert broker.listener.connections == 1


@pytestmark_db
async def test_first_stream_of_a_scope_listens_and_last_unlistens(make_broker, pg):
    broker = make_broker()
    recorder = broker.executor
    first, second = make_stream("a"), make_stream("a")

    await broker.register(first)
    assert broker.listener.channels == {"live_host_a": 1}
    assert broker.listener.listened == {"live_host_a"}

    await broker.register(second)
    assert broker.listener.channels == {"live_host_a": 2}
    assert broker.channel_count() == 1
    assert broker.streams_for("live_host_a") == [first, second]
    assert len(await listener_pids(pg)) == 1

    await notify(pg, "live_host_a")
    await eventually(lambda: len(recorder.events) == 2)
    assert sorted(recorder.events, key=lambda e: e[0]) == sorted(
        [(first.id, {"testapp.thing.created"}), (second.id, {"testapp.thing.created"})], key=lambda e: e[0]
    )

    broker.unregister(first)
    await broker.listener.wait_synced()
    assert broker.listener.listened == {"live_host_a"}

    broker.unregister(second)
    await broker.listener.wait_synced()
    assert broker.listener.channels == {}
    assert broker.listener.listened == set()
    assert broker.channel_count() == 0

    recorder.events.clear()
    await notify(pg, "live_host_a")
    await asyncio.sleep(0.3)
    assert recorder.events == []  # UNLISTENed on the server: nothing is delivered any more
    assert len(await listener_pids(pg)) == 1  # the connection stays for the next stream


@pytestmark_db
async def test_fifty_streams_share_one_listen_connection(make_broker, pg):
    broker = make_broker()
    streams = [make_stream(f"shop{i % 5}") for i in range(50)]

    await asyncio.gather(*(broker.register(stream) for stream in streams))

    assert broker.channel_count() == 5
    assert broker.listener.channels == {f"live_host_shop{i}": 10 for i in range(5)}
    assert broker.listener.listened == {f"live_host_shop{i}" for i in range(5)}
    assert len(await listener_pids(pg)) == 1
    assert broker.listener.connections == 1


@pytestmark_db
async def test_unregister_is_idempotent(make_broker):
    broker = make_broker()
    first, second = make_stream("a"), make_stream("a")
    await broker.register(first)
    await broker.register(second)

    broker.unregister(first)
    broker.unregister(first)

    assert broker.listener.channels == {"live_host_a": 1}
    assert broker.streams_for("live_host_a") == [second]


# Dispatch


@pytestmark_db
@pytest.mark.parametrize(
    ("payload", "names"),
    [
        ('{"events":["testapp.thing.created","testapp.thing.deleted"]}', {"testapp.thing.created", "testapp.thing.deleted"}),
        ('{"events":["*"]}', {"*"}),
        ('{"events":"*"}', {"*"}),
        ("*", {"*"}),
        ("not json", {"*"}),
        ('{"events":[1]}', {"*"}),
        ('{"other":1}', {"*"}),
    ],
)
async def test_dispatch_hands_the_event_names_to_every_stream_of_the_channel(make_broker, payload, names):
    broker = make_broker()
    stream = make_stream("a")
    await broker.register(stream)

    await broker.dispatch("live_host_a", payload)
    await broker.dispatch("live_host_nobody", payload)

    assert broker.executor.events == [(stream.id, names)]


@pytestmark_db
async def test_notify_on_channel_dispatches_to_its_streams_only(make_broker, pg, settings):
    settings.LIVE = {**settings.LIVE, "context_builder": "tests.testapp.live_context.LiveTestContextBuilder"}
    LiveTestContextBuilder.reset()
    executor = Executor(debounce=0.05)
    broker = make_broker(executor=executor)
    stream_a, stream_b = make_stream("a"), make_stream("b")
    try:
        for stream in (stream_a, stream_b):
            stream.subs["s1"] = Subscription(id="s1", op=registry["testapp.thing.list"], params=ThingListIn())
            await broker.register(stream)
            await executor.run_all(stream)
            assert (await next_queued(stream.queue)).data["data"] == {"rows": []}

        await create_thing("new")
        await notify(pg, "live_host_a")

        frame = await next_queued(stream_a.queue)
        assert frame.event == "result"
        assert frame.data["rev"] == 2
        assert [row["name"] for row in frame.data["data"]["rows"]] == ["new"]
        await asyncio.sleep(1.0)
        assert stream_b.queue.empty()
    finally:
        executor.reset()
        executor.shutdown()


# Resync and reconnection


@pytestmark_db
async def test_resync_all_runs_every_stream(make_broker):
    broker = make_broker()
    streams = [make_stream("a"), make_stream("a"), make_stream("b")]
    for stream in streams:
        await broker.register(stream)

    await broker.resync_all()

    assert sorted(broker.executor.runs) == sorted(stream.id for stream in streams)


@pytestmark_db
async def test_reconnect_triggers_resync_all(make_broker):
    attempts = []

    async def flaky_connect():
        attempts.append(1)
        if len(attempts) == 1:
            raise psycopg.OperationalError("the database system is starting up")
        return await broker_module.default_connect()

    broker = make_broker(connect=flaky_connect)
    stream = make_stream("a")

    await broker.register(stream)

    await eventually(lambda: broker.executor.runs)
    assert broker.executor.runs == [stream.id]
    assert len(attempts) == 2
    assert broker.listener.listened == {"live_host_a"}


@pytestmark_db
async def test_a_lost_connection_reconnects_listens_again_and_resyncs(make_broker, pg):
    broker = make_broker()
    stream = make_stream("a")
    await broker.register(stream)
    (old_pid,) = await listener_pids(pg)
    assert broker.executor.runs == []

    await pg.execute("SELECT pg_terminate_backend(%s)", [old_pid])

    await eventually(lambda: broker.executor.runs)
    assert broker.executor.runs == [stream.id]
    await broker.listener.wait_synced()
    pids = await eventually(lambda: listener_pids(pg))
    assert len(pids) == 1 and pids[0] != old_pid
    assert broker.listener.connections == 2

    await notify(pg, "live_host_a")
    await eventually(lambda: broker.executor.events)
    assert broker.executor.events == [(stream.id, {"testapp.thing.created"})]


@pytestmark_db
async def test_a_slow_first_connection_does_not_block_streams_and_resyncs_them(make_broker, monkeypatch):
    monkeypatch.setattr(broker_module, "LISTEN_WAIT", 0.05)

    async def slow_connect():
        await asyncio.sleep(0.3)
        return await broker_module.default_connect()

    broker = make_broker(connect=slow_connect)
    stream = make_stream("a")
    loop = asyncio.get_running_loop()

    started = loop.time()
    await broker.register(stream)
    assert loop.time() - started < 0.25

    await eventually(lambda: broker.executor.runs)
    assert broker.executor.runs == [stream.id]
    assert broker.listener.listened == {"live_host_a"}


@pytestmark_db
async def test_stop_closes_the_listen_connection(make_broker, pg):
    broker = make_broker()
    await broker.register(make_stream("a"))
    assert len(await listener_pids(pg)) == 1

    await broker.stop()

    await eventually(lambda: _no_listener(pg))
    assert not broker.listener.running


async def _no_listener(pg):
    return await listener_pids(pg) == []
