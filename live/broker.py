"""One ``LISTEN`` connection per process and the streams waiting on each channel (plan §4.1).

Commands notify their scope's channel after the COMMIT, on the control database
(``live.outbox.notify``). Every process keeps a single ``psycopg.AsyncConnection`` there (the
``Listener``, ``application_name = 'live-listener'``): it LISTENs on a channel while at least one
stream of that scope is open and UNLISTENs when the last one goes. It is not a Django connection:
it lives in the event loop for the life of the process, outside the ORM and any pool.

The Listener starts with the first stream, inside the running event loop (daphne's). If the
connection is lost it reconnects with a growing backoff and asks the broker to re-run every
stream (``resync_all``): notifications sent while it was away are lost, results are not.
"""

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable, Coroutine
from contextlib import aclosing
from functools import cache
from typing import Any

import psycopg
from django.conf import settings
from django.db import DEFAULT_DB_ALIAS
from psycopg import pq, sql
from psycopg.conninfo import make_conninfo

from live import executor as executor_module
from live.errors import LiveMisuse
from live.executor import Stream
from live.live_registry import ALL_EVENTS

logger = logging.getLogger(__name__)

APPLICATION_NAME = "live-listener"
#: Seconds a new stream waits for its channel to be LISTENed before running its first results.
#: Past it the stream goes on, and the Listener re-runs every stream once it is connected.
LISTEN_WAIT = 2.0
#: TCP keepalives, so a silently dropped connection (failover, NAT) is noticed within a minute.
_KEEPALIVES = {"keepalives": 1, "keepalives_idle": 30, "keepalives_interval": 10, "keepalives_count": 3}

Connect = Callable[[], Awaitable[psycopg.AsyncConnection]]


def control_conninfo(db: dict[str, Any] | None = None) -> str:
    """libpq connection string of the control database (``settings.LIVE["control_alias"]``)."""
    if db is None:
        alias = getattr(settings, "LIVE", {}).get("control_alias", DEFAULT_DB_ALIAS)
        try:
            db = settings.DATABASES[alias]
        except KeyError:
            raise LiveMisuse(f'settings.LIVE["control_alias"] = {alias!r} is not in settings.DATABASES.') from None
    params = {
        "dbname": db.get("NAME"),
        "user": db.get("USER"),
        "password": db.get("PASSWORD"),
        "host": db.get("HOST"),
        "port": db.get("PORT"),
    }
    # Django-only options (pool, isolation_level, server_side_binding…) are not libpq parameters.
    params |= {key: value for key, value in (db.get("OPTIONS") or {}).items() if key in _libpq_keywords()}
    return make_conninfo(**{key: str(value) for key, value in params.items() if value not in (None, "")})


@cache
def _libpq_keywords() -> frozenset[str]:
    return frozenset(option.keyword.decode() for option in pq.Conninfo.get_defaults())


async def default_connect() -> psycopg.AsyncConnection:
    return await psycopg.AsyncConnection.connect(
        control_conninfo(), autocommit=True, application_name=APPLICATION_NAME, **_KEEPALIVES
    )


class Listener:
    """The process's single LISTEN connection, with a reference count per channel."""

    def __init__(self, broker: "Broker", *, connect: Connect | None = None, backoff: tuple[float, float] = (0.5, 10.0)) -> None:
        self.broker = broker
        #: Channels wanted, with how many streams want each.
        self.channels: dict[str, int] = {}
        #: Channels LISTENed on the current connection.
        self.listened: set[str] = set()
        #: Successful connections so far (1 while it never dropped).
        self.connections = 0
        self._connect = connect or default_connect
        self._backoff_min, self._backoff_max = backoff
        self._task: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake: asyncio.Event | None = None
        self._synced: asyncio.Condition | None = None
        self._connected = False
        self._resync_needed = False
        self._background: set[asyncio.Task] = set()

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def listen(self, channel: str) -> None:
        self.channels[channel] = self.channels.get(channel, 0) + 1
        self._ensure_started()
        if self.channels[channel] == 1:
            self._wake.set()

    def unlisten(self, channel: str) -> None:
        count = self.channels.get(channel, 0)
        if count > 1:
            self.channels[channel] = count - 1
            return
        self.channels.pop(channel, None)
        if self._wake is not None:
            self._wake.set()

    async def wait_listening(self, channel: str, timeout: float | None = None) -> bool:
        """Wait until ``channel`` is LISTENed; on timeout, re-run every stream once connected."""
        if channel in self.listened or self._synced is None:
            return channel in self.listened
        try:
            async with asyncio.timeout(LISTEN_WAIT if timeout is None else timeout):
                async with self._synced:
                    await self._synced.wait_for(lambda: channel in self.listened or channel not in self.channels)
        except TimeoutError:
            logger.warning("Live listener is not listening on %s yet; the stream starts without it.", channel)
            self._resync_needed = True
        return channel in self.listened

    async def wait_synced(self, timeout: float = 5.0) -> None:
        """Wait until the LISTENed channels are exactly the wanted ones (tests, shutdown)."""
        if self._synced is None:
            return
        async with asyncio.timeout(timeout):
            async with self._synced:
                await self._synced.wait_for(lambda: self._connected and self.listened == set(self.channels))

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            if task.get_loop() is asyncio.get_running_loop():
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        for background in list(self._background):
            background.cancel()
        self._background.clear()
        self.listened = set()
        self._connected = False

    def _ensure_started(self) -> None:
        loop = asyncio.get_running_loop()
        if self.running and self._loop is loop:
            return
        self._loop = loop
        self._wake = asyncio.Event()
        self._synced = asyncio.Condition()
        self.listened = set()
        self._connected = False
        self._task = loop.create_task(self._run(), name="live-listener")

    async def _run(self) -> None:
        delay = self._backoff_min
        lost = False
        while True:
            try:
                conn = await self._connect()
            except Exception as exc:
                logger.log(_level(exc), "Live listener cannot connect (%s); retrying in %.1f s.", exc, delay,
                           exc_info=_level(exc) == logging.ERROR)
                lost = True
                await asyncio.sleep(delay)
                delay = min(delay * 2, self._backoff_max)
                continue
            self.connections += 1
            self._connected = True
            try:
                self.listened = set()
                await self._sync(conn)
                if lost or self._resync_needed:
                    self._resync_needed = False
                    self._spawn(self.broker.resync_all())
                delay = self._backoff_min
                await self._serve(conn)
            except Exception as exc:
                logger.log(_level(exc), "Live listener lost its connection (%s); reconnecting in %.1f s.", exc, delay,
                           exc_info=_level(exc) == logging.ERROR)
                lost = True
            finally:
                self._connected = False
                self.listened = set()
                with contextlib.suppress(Exception):
                    await conn.close()
            await asyncio.sleep(delay)
            delay = min(delay * 2, self._backoff_max)

    async def _serve(self, conn: psycopg.AsyncConnection) -> None:
        """Deliver notifications; stop waiting for them whenever the wanted channels change."""
        while True:
            self._wake.clear()
            await self._sync(conn)
            if self._wake.is_set():
                continue
            consume = asyncio.ensure_future(self._consume(conn))
            woken = asyncio.ensure_future(self._wake.wait())
            try:
                await asyncio.wait({consume, woken}, return_when=asyncio.FIRST_COMPLETED)
            finally:
                consume.cancel()
                woken.cancel()
                await asyncio.wait({consume, woken})
            if not consume.cancelled() and consume.exception() is not None:
                raise consume.exception()

    async def _consume(self, conn: psycopg.AsyncConnection) -> None:
        # aclosing: however this ends, the generator is closed and releases the connection lock.
        async with aclosing(conn.notifies()) as notifies:
            async for notification in notifies:
                self._spawn(self.broker.dispatch(notification.channel, notification.payload))
        raise psycopg.OperationalError("The notification stream ended.")

    async def _sync(self, conn: psycopg.AsyncConnection) -> None:
        wanted = set(self.channels)
        for channel in sorted(wanted - self.listened):
            await conn.execute(sql.SQL("LISTEN {}").format(sql.Identifier(channel)))
            self.listened.add(channel)
        for channel in sorted(self.listened - wanted):
            await conn.execute(sql.SQL("UNLISTEN {}").format(sql.Identifier(channel)))
            self.listened.discard(channel)
        async with self._synced:
            self._synced.notify_all()

    def _spawn(self, coro: Coroutine) -> None:
        task = asyncio.get_running_loop().create_task(coro)
        self._background.add(task)
        task.add_done_callback(self._finished)

    def _finished(self, task: asyncio.Task) -> None:
        self._background.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.error("Live listener task failed.", exc_info=task.exception())


def _level(exc: Exception) -> int:
    """Connection trouble is expected now and then; anything else is a bug worth a traceback."""
    return logging.WARNING if isinstance(exc, (psycopg.OperationalError, OSError)) else logging.ERROR


class Broker:
    """The open streams of this process, by channel, and the Listener that wakes them."""

    def __init__(self, *, executor=None, connect: Connect | None = None, backoff: tuple[float, float] = (0.5, 10.0)) -> None:
        self._executor = executor
        self._streams: dict[str, dict[str, Stream]] = {}
        self.listener = Listener(self, connect=connect, backoff=backoff)

    @property
    def executor(self):
        return self._executor or executor_module.executor

    async def register(self, stream: Stream) -> None:
        """Add a stream and wait until its channel is LISTENed (so no COMMIT after it is missed)."""
        self._streams.setdefault(stream.channel, {})[stream.id] = stream
        self.listener.listen(stream.channel)
        await self.listener.wait_listening(stream.channel)

    def unregister(self, stream: Stream) -> None:
        streams = self._streams.get(stream.channel)
        if not streams or streams.pop(stream.id, None) is None:
            return
        if not streams:
            del self._streams[stream.channel]
        self.listener.unlisten(stream.channel)

    async def dispatch(self, channel: str, payload: str) -> None:
        """A notification arrived: hand its event names to every stream of the channel."""
        streams = self.streams_for(channel)
        if not streams:
            return
        names = event_names(payload)
        for stream in streams:
            await self.executor.on_events(stream, names)

    async def resync_all(self) -> None:
        """Re-run every stream of the process (after the LISTEN connection came back)."""
        streams = [stream for streams in self._streams.values() for stream in streams.values()]
        results = await asyncio.gather(*(self.executor.run_all(stream) for stream in streams), return_exceptions=True)
        for stream, result in zip(streams, results, strict=True):
            if isinstance(result, Exception):
                logger.error("Live resync of stream %s failed.", stream.id, exc_info=result)

    def streams_for(self, channel: str) -> list[Stream]:
        return list(self._streams.get(channel, {}).values())

    def channel_count(self) -> int:
        return len(self._streams)

    async def stop(self) -> None:
        await self.listener.stop()

    async def reset(self) -> None:
        """Stop listening and forget every stream (tests: each test has its own event loop)."""
        await self.stop()
        self._streams.clear()
        self.listener.channels.clear()


def event_names(payload: str) -> set[str]:
    """Event names of a notification; anything unexpected means "everything may have changed"."""
    try:
        data = json.loads(payload)
    except ValueError:
        data = None
    events = data.get("events") if isinstance(data, dict) else None
    if isinstance(events, list) and events and all(isinstance(name, str) for name in events):
        return set(events)
    if events != ALL_EVENTS and payload != ALL_EVENTS:
        logger.warning("Live notification with an unexpected payload %.200r; re-running everything.", payload)
    return {ALL_EVENTS}


broker = Broker()
