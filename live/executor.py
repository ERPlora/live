"""Runs live queries for the streams of ``/api/live`` and queues their frames (plan §4.1).

When a stream opens, every subscription runs once. After an event, the subscriptions it affects
(``live.py``) run again, bursts grouped by a debounce, **as the stream's user**: the context is
refreshed (permissions re-read) before every run. A ``result`` frame is queued only when the
serialised result changed (``blake2b`` hash), with a ``rev`` that grows per subscription.

Operations run in a small thread pool (``max_workers`` per process) because the ORM is
synchronous; at most one run per scope at a time, different scopes in parallel. Each thread run
ends with ``close_old_connections()``, so threads never keep a database connection past its age.
A worker thread inherits no active language, so each run activates the stream's
(``ctx.language``): the operation's texts and the messages of its error frames reach the client
in it.
"""

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from hashlib import blake2b
from typing import Any

from django.db import close_old_connections
from django.utils.translation import override
from ninja import Schema

from live.context import OperationContext, Scope, get_builder
from live.errors import AppInactive, OperationError, PermissionDenied, Unauthorized
from live.live_registry import live_registry
from live.sse import BYE, ERROR, MAX_RESULT_BYTES, RESULT, frame

logger = logging.getLogger(__name__)

#: Frames a stream may hold for a slow client; past it the stream is closed with ``bye``.
QUEUE_MAX = 256
#: The frame that ends a stream from the server side (the client reconnects).
BYE_FRAME = frame(BYE)


@dataclass(eq=False)
class Subscription:
    id: str
    op: Any  # live.operations.Operation (or anything callable as op(ctx, params) with a .name)
    params: Schema
    last_hash: str | None = None
    rev: int = 0
    #: Set by a run that lost the right to it (permission revoked, app inactive).
    dropped: bool = False


class Stream:
    """One open ``/api/live`` connection: its context, its subscriptions and its frame queue."""

    def __init__(self, ctx: OperationContext, *, maxsize: int | None = None) -> None:
        self.id = uuid.uuid7().hex
        self.ctx = ctx
        self.scope: Scope = ctx.scope
        self.subs: dict[str, Subscription] = {}
        self.queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=QUEUE_MAX if maxsize is None else maxsize)
        self.closed = False

    @property
    def channel(self) -> str:
        return self.scope.channel

    def put(self, item: bytes) -> None:
        """Queue a frame; a ``bye`` or an overflow closes the stream."""
        if self.closed:
            return
        if item == BYE_FRAME:
            self.close()
            return
        try:
            self.queue.put_nowait(item)
        except asyncio.QueueFull:
            logger.warning("Live stream %s overflowed (%d frames queued); closing it.", self.id, self.queue.maxsize)
            self.close()

    def close(self) -> None:
        """End the stream from the server side: drop what is queued and queue a single ``bye``."""
        if self.closed:
            return
        self.closed = True
        while not self.queue.empty():
            self.queue.get_nowait()
        self.queue.put_nowait(BYE_FRAME)


@dataclass(eq=False)
class _Pending:
    sub_ids: set[str]
    first_at: float
    due_at: float
    task: asyncio.Task | None = None


@dataclass(eq=False)
class _Gate:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    users: int = 0


class Executor:
    def __init__(
        self,
        *,
        max_workers: int = 3,
        debounce: float = 0.15,
        max_debounce: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self.max_workers = max_workers
        self.debounce = debounce
        self.max_debounce = max_debounce
        self.clock = clock
        self._loop = loop
        self._pool: ThreadPoolExecutor | None = None
        self._gates: dict[Scope, _Gate] = {}
        self._pending: dict[Stream, _Pending] = {}
        self._tasks: set[asyncio.Task] = set()

    async def run_all(self, stream: Stream) -> None:
        """Run every subscription of the stream once (initial results, safety re-run, resync)."""
        await self._run_subs(stream, list(stream.subs.values()))

    async def on_events(self, stream: Stream, names: Iterable[str]) -> None:
        """Schedule the subscriptions affected by ``names``; a burst within the debounce runs once."""
        if stream.closed:
            return
        affected = live_registry.affected(names)
        ids = {sub.id for sub in stream.subs.values() if sub.op.name in affected}
        if not ids:
            return
        now = self.clock()
        pending = self._pending.get(stream)
        if pending is None:
            pending = _Pending(sub_ids=ids, first_at=now, due_at=now + self.debounce)
            self._pending[stream] = pending
            pending.task = self._spawn(self._flush(stream, pending))
        else:
            pending.sub_ids |= ids
            pending.due_at = min(now + self.debounce, pending.first_at + self.max_debounce)

    def forget(self, stream: Stream) -> None:
        """Cancel the pending re-runs of a stream that is going away."""
        pending = self._pending.pop(stream, None)
        if pending is not None and pending.task is not None:
            pending.task.cancel()

    def reset(self) -> None:
        """Forget every pending re-run and scope gate (tests: each test has its own event loop)."""
        for task in list(self._tasks):
            task.cancel()
        self._tasks.clear()
        self._pending.clear()
        self._gates.clear()

    def shutdown(self) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)
            self._pool = None

    async def _flush(self, stream: Stream, pending: _Pending) -> None:
        try:
            while (delay := pending.due_at - self.clock()) > 0:
                await asyncio.sleep(delay)
        finally:
            if self._pending.get(stream) is pending:
                del self._pending[stream]
        await self._run_subs(stream, [sub for sub in stream.subs.values() if sub.id in pending.sub_ids])

    async def _run_subs(self, stream: Stream, subs: list[Subscription]) -> None:
        for sub in subs:
            if stream.closed:
                return
            if stream.subs.get(sub.id) is sub:
                await self._run(stream, sub)

    async def _run(self, stream: Stream, sub: Subscription) -> None:
        gate = self._gates.get(stream.scope)
        if gate is None:
            gate = self._gates[stream.scope] = _Gate()
        gate.users += 1
        try:
            await gate.lock.acquire()
        except BaseException:
            self._leave(stream.scope, gate)
            raise
        if stream.closed or stream.subs.get(sub.id) is not sub:
            self._release(stream.scope, gate)
            return
        try:
            future = self._get_loop().run_in_executor(self._get_pool(), self._run_one, stream, sub)
        except BaseException:
            self._release(stream.scope, gate)
            raise
        # The scope stays taken until the thread is done, even if the awaiting stream goes away.
        future.add_done_callback(lambda _future: self._release(stream.scope, gate))
        data = await asyncio.shield(future)
        if sub.dropped and stream.subs.get(sub.id) is sub:
            del stream.subs[sub.id]
        if data is not None:
            stream.put(data)

    def _run_one(self, stream: Stream, sub: Subscription) -> bytes | None:
        """Run one subscription in a worker thread; the frame to queue, or ``None`` if unchanged.

        Everything runs in the stream's language: the operation and the frame (a lazy message is
        only translated when the frame is serialised).
        """
        try:
            with override(stream.ctx.language):
                return self._run_in_language(stream, sub)
        finally:
            close_old_connections()

    def _run_in_language(self, stream: Stream, sub: Subscription) -> bytes | None:
        try:
            ctx = get_builder().refresh(stream.ctx)
            data = sub.op(ctx, sub.params).model_dump(mode="json")
        except Unauthorized:
            return BYE_FRAME
        except (PermissionDenied, AppInactive) as exc:
            sub.dropped = True
            return self._error(sub, exc.envelope()["error"])
        except OperationError as exc:
            return self._error(sub, exc.envelope()["error"])
        except Exception:
            logger.exception("Live query %s failed (stream %s, subscription %s).", sub.op.name, stream.id, sub.id)
            return self._error(sub, {"code": "internal_error", "message": "The live query failed."})
        body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
        digest = blake2b(body, digest_size=16).hexdigest()
        if digest == sub.last_hash:
            return None
        sub.last_hash = digest
        if len(body) > MAX_RESULT_BYTES:
            return frame(ERROR, {"id": sub.id, "error": {
                "code": "result_too_large",
                "message": f"The result exceeds {MAX_RESULT_BYTES} bytes; ask for fewer rows.",
            }})
        sub.rev += 1
        return frame(RESULT, {"id": sub.id, "data": data, "rev": sub.rev})

    @staticmethod
    def _error(sub: Subscription, error: dict) -> bytes:
        # After an error the client shows it; the next result must be sent even if it is the old one.
        sub.last_hash = None
        return frame(ERROR, {"id": sub.id, "error": error})

    def _release(self, scope: Scope, gate: _Gate) -> None:
        gate.lock.release()
        self._leave(scope, gate)

    def _leave(self, scope: Scope, gate: _Gate) -> None:
        gate.users -= 1
        if gate.users == 0 and self._gates.get(scope) is gate:
            del self._gates[scope]

    def _spawn(self, coro) -> asyncio.Task:
        task = self._get_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def _get_loop(self) -> asyncio.AbstractEventLoop:
        return self._loop or asyncio.get_running_loop()

    def _get_pool(self) -> ThreadPoolExecutor:
        if self._pool is None:
            self._pool = ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="live-query")
        return self._pool


executor = Executor()
