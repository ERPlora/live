"""Helpers shared by the live-stream tests: parse SSE frames and read them with a timeout."""

import asyncio
import base64
import contextlib
import json
from dataclasses import dataclass, field


@dataclass
class Frame:
    event: str
    data: dict
    retry: int | None = None
    raw: bytes = b""


def parse_frame(raw: bytes) -> Frame:
    assert raw.endswith(b"\n\n"), f"not a complete SSE frame: {raw!r}"
    event, data, retry = "message", None, None
    for line in raw.decode().strip("\n").split("\n"):
        name, _, value = line.partition(": ")
        if name == "event":
            event = value
        elif name == "data":
            data = json.loads(value)
        elif name == "retry":
            retry = int(value)
    return Frame(event=event, data=data or {}, retry=retry, raw=raw)


async def drain(queue: asyncio.Queue) -> list[Frame]:
    """Every frame already queued on a stream (executor tests)."""
    frames = []
    while not queue.empty():
        frames.append(parse_frame(queue.get_nowait()))
    return frames


async def next_queued(queue: asyncio.Queue, timeout: float = 2.0) -> Frame:
    return parse_frame(await asyncio.wait_for(queue.get(), timeout))


def encode_subs(subs: list[dict]) -> str:
    """The ``s=`` parameter as the SDK sends it: base64url JSON without padding."""
    return base64.urlsafe_b64encode(json.dumps(subs).encode()).decode().rstrip("=")


@dataclass
class StreamReader:
    """Consumes a streaming response in a background task, as the ASGI server would.

    Cancelling the task is what Django's ASGI handler does when the client disconnects.
    """

    response: object
    frames: asyncio.Queue = field(default_factory=asyncio.Queue)
    ended: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None

    def start(self) -> "StreamReader":
        self.task = asyncio.get_running_loop().create_task(self._pump())
        return self

    async def _pump(self) -> None:
        try:
            async for chunk in self.response.streaming_content:
                await self.frames.put(parse_frame(chunk))
        finally:
            self.ended.set()

    async def next(self, timeout: float = 3.0) -> Frame:
        return await asyncio.wait_for(self.frames.get(), timeout)

    async def next_data_frame(self, timeout: float = 3.0) -> Frame:
        """The next frame that is not a heartbeat, within ``timeout`` overall."""
        async with asyncio.timeout(timeout):
            while True:
                frame = await self.frames.get()
                if frame.event != "heartbeat":
                    return frame

    async def nothing_within(self, seconds: float, *, ignore=("heartbeat",)) -> list[Frame]:
        """Frames other than ``ignore`` received within ``seconds`` (expected to be empty)."""
        await asyncio.sleep(seconds)
        seen = []
        while not self.frames.empty():
            frame = self.frames.get_nowait()
            if frame.event not in ignore:
                seen.append(frame)
        return seen

    async def disconnect(self) -> None:
        if self.task is not None and not self.task.done():
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task


async def eventually(check, *, timeout: float = 3.0, interval: float = 0.01):
    """Poll ``check`` (sync or async) until it returns something truthy; fail after ``timeout``."""
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        value = check()
        if asyncio.iscoroutine(value):
            value = await value
        if value:
            return value
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"condition not met within {timeout} s: {check}")
        await asyncio.sleep(interval)


def create_thing_sync(name: str):
    """Create a testapp Thing and close this thread's connection (asgiref's thread keeps it otherwise)."""
    from django.db import connection

    from tests.testapp.models import Thing

    try:
        return Thing.objects.create(name=name)
    finally:
        connection.close()


async def create_thing(name: str):
    from asgiref.sync import sync_to_async

    return await sync_to_async(create_thing_sync)(name)


def host_client():
    """An AsyncClient whose ``headers={"host": ...}`` replaces its built-in ``host: testserver``."""
    from django.test import AsyncClient

    class HostAsyncClient(AsyncClient):
        def request(self, **request):
            headers = request.get("headers", [])
            if sum(1 for name, _ in headers if name == b"host") > 1:
                default = next(i for i, (name, _) in enumerate(headers) if name == b"host")
                request["headers"] = headers[:default] + headers[default + 1 :]
            return super().request(**request)

    return HostAsyncClient()
