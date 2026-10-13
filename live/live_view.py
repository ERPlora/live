"""``GET /api/live?s=…``: one Server-Sent Events stream per browser tab (plan §4.1).

The subscriptions are declared when the stream opens (``s`` = base64url JSON
``[{id, op, params}]``); if they change, the SDK closes the stream and opens another. Frames:
``hello {stream}`` (with ``retry: 3000``), then ``result {id, data, rev}`` or ``error {id, error}``
per subscription, ``heartbeat`` after :data:`HEARTBEAT_EVERY` idle seconds and ``bye`` when the
server ends the stream. A request that cannot become a stream (a Host that is no scope, no actor, a
malformed ``s``) gets the JSON error envelope instead.

Every subscription runs once when the stream opens, again after an event of its ``live.py``, and
every :data:`SAFETY_RERUN_EVERY` seconds in case a notification was lost.
"""

import asyncio
import logging
import time

import pydantic
from asgiref.sync import sync_to_async
from django.core.exceptions import NON_FIELD_ERRORS
from django.http import Http404, JsonResponse, StreamingHttpResponse

from live import sse
from live.broker import broker
from live.context import get_builder
from live.errors import OperationError
from live.executor import BYE_FRAME, Stream, Subscription, executor
from live.live_registry import live_registry
from live.operations import registry
from live.sse import ERROR, HEARTBEAT, HELLO, RETRY_MS, frame, parse_subscriptions

logger = logging.getLogger(__name__)

HEARTBEAT_EVERY = sse.HEARTBEAT_EVERY
SAFETY_RERUN_EVERY = 300.0
#: Monotonic clock of the safety re-run (tests inject their own).
clock = time.monotonic

_INVALID_S_MESSAGES = {
    "invalid_subscriptions": "The s parameter must be base64url JSON [{id, op, params}] with unique ids.",
    "too_many_subscriptions": f"A stream accepts at most {sse.MAX_SUBS} subscriptions.",
}


async def live_stream(request) -> StreamingHttpResponse | JsonResponse:
    if request.method != "GET":
        response = _envelope(405, "method_not_allowed", "Open a live stream with GET.")
        response["Allow"] = "GET"
        return response
    try:
        ctx = await sync_to_async(get_builder().from_request)(request)
    except OperationError as exc:
        return JsonResponse(exc.envelope(), status=exc.status)
    except Http404:
        # The builder rejects the Host (hub-next: not a hub's slug), as the ninja routes answer it.
        return _envelope(404, "not_found", "Not found.")
    if ctx is None or ctx.actor is None:
        return _envelope(401, "unauthorized", "Sign in to open a live stream.")
    try:
        items = parse_subscriptions(request.GET.get("s", ""))
    except ValueError as exc:
        code = str(exc)
        return _envelope(400, code, _INVALID_S_MESSAGES.get(code, "Invalid subscriptions."))

    stream = Stream(ctx)
    rejected = []
    for item in items:
        sub, error = _subscription(item)
        if sub is None:
            rejected.append(error)
        else:
            stream.subs[sub.id] = sub
    response = StreamingHttpResponse(_LiveBody(stream, rejected), content_type="text/event-stream")
    response["Cache-Control"] = "no-store"
    response["X-Accel-Buffering"] = "no"  # nginx and friends must not buffer the stream
    return response


class _LiveBody:
    """The body of one stream. Django calls ``close()`` once the response is over (client gone)."""

    def __init__(self, stream: Stream, rejected: list[bytes]) -> None:
        self.stream = stream
        self._rejected = rejected
        self._loop: asyncio.AbstractEventLoop | None = None
        self._released = False

    def __aiter__(self):
        return self._frames()

    async def _frames(self):
        self._loop = asyncio.get_running_loop()
        stream = self.stream
        try:
            yield frame(HELLO, {"stream": stream.id}, retry_ms=RETRY_MS)
            for rejected in self._rejected:
                yield rejected
            if self._released:
                return
            await broker.register(stream)
            await executor.run_all(stream)
            last_full_run = clock()
            while True:
                try:
                    item = await asyncio.wait_for(stream.queue.get(), HEARTBEAT_EVERY)
                except TimeoutError:
                    item = frame(HEARTBEAT)
                yield item
                if item == BYE_FRAME:
                    return
                if clock() - last_full_run >= SAFETY_RERUN_EVERY:
                    last_full_run = clock()
                    await executor.run_all(stream)
        finally:
            # A disconnect cancels the response task, so the CancelledError lands here: nothing
            # may be yielded any more, only released.
            self._release()

    def close(self) -> None:
        """Release the stream; Django may call this from a worker thread."""
        loop = self._loop
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if loop is None or running is loop:
            self._release()
        elif not loop.is_closed():
            loop.call_soon_threadsafe(self._release)

    def _release(self) -> None:
        if self._released:
            return
        self._released = True
        self.stream.closed = True
        broker.unregister(self.stream)
        executor.forget(self.stream)


def _subscription(item: dict) -> tuple[Subscription | None, bytes | None]:
    sub_id, op_name = item["id"], item["op"]
    op = registry.get(op_name)
    if op is None:
        return None, _error_frame(sub_id, "unknown_operation", f"Unknown operation {op_name!r}.")
    if op.kind != "query" or not live_registry.is_subscribable(op_name):
        return None, _error_frame(sub_id, "not_subscribable", f"{op_name} is not a live query.")
    try:
        params = op.input.model_validate(item["params"])
    except pydantic.ValidationError as exc:
        fields = {}
        for error in exc.errors():
            fields.setdefault(".".join(str(part) for part in error["loc"]) or NON_FIELD_ERRORS, error["msg"])
        return None, _error_frame(sub_id, "invalid_payload", "Invalid parameters.", fields=fields)
    return Subscription(id=sub_id, op=op, params=params), None


def _error_frame(sub_id: str, code: str, message: str, *, fields: dict[str, str] | None = None) -> bytes:
    error = {"code": code, "message": message}
    if fields:
        error["fields"] = fields
    return frame(ERROR, {"id": sub_id, "error": error})


def _envelope(status: int, code: str, message: str) -> JsonResponse:
    return JsonResponse({"error": {"code": code, "message": message}}, status=status)
