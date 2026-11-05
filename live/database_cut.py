"""A cut of the database: a request waits and tries again instead of failing (PLAN-DB, round 2026-11-04e, point 5).

A restart of the writer, an AWS maintenance or a Blue/Green switchover cut the connections or leave the database read
only for some seconds. A project asks for this piece by naming ``settings.LIVE["database_cut"]``:
``{"wait_seconds": <the limit of a whole request>, "no_wait_prefixes": (<paths whose callers try again on their own>)}``.
Without that setting nothing changes: a cut stays the error it was.

**What is a cut** (:func:`is_cut`): a lost or refused connection, a pool with nothing to give, ``57P01`` and its
neighbours, ``25006`` (a write on a read-only database). A statement timeout, a deadlock or a bug are not, and stay what
they were.

**What may repeat, and only this:**

- a read (``kind="query"``);
- a command whose body never ran: it could not connect;
- a command that says so (``repeatable=True``), when the cut came before its COMMIT was sent: its database rolled back,
  and it declares that it touches nothing else. Never a charge, a numbering, a call to a third party;
- a whole request cut before its view started (a route of the API counts as started when a command does: it writes only
  through its operations), or a safe method (GET, HEAD, OPTIONS) that started no command.

A cut while sending the COMMIT leaves the result unknown: nothing repeats it, not even a command that says it can.

**Who waits.** The route's operation in :func:`retrying` / :func:`aretrying` (``live.ninja.run_operation``), outside its
transaction, so the wait holds no connection and no slot of the project's ``operation_database``. Everything else, a
page or a session read, in :class:`DatabaseCutMiddleware`, which goes first in ``MIDDLEWARE``: Django turns an exception
into a response at every layer, so it can only look at the response, which the project's ``handler500`` marks with
:func:`current_cut` and :func:`marked`. A live stream waits in ``live.executor``, as any passing failure.

Past the limit, or when it may not repeat: 503 with ``Retry-After``, never a 500. The code says which: ``database_unavailable``
(come back in a moment) or ``database_outcome_unknown`` (check whether it was saved).
"""

import asyncio
import random
import sys
import time
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, TypeVar

from asgiref.sync import iscoroutinefunction, markcoroutinefunction, sync_to_async
from django.conf import settings
from django.db import Error, OperationalError, connections
from django.http import HttpRequest
from django.http.response import HttpResponseBase
from django.utils.cache import add_never_cache_headers
from django.utils.translation import gettext

from live.api_errors import is_api_path
from live.errors import OperationError

T = TypeVar("T")

#: The seconds a client is told to wait (``Retry-After``), and the live executor after a repeatable cut.
RETRY_AFTER_SECONDS = 10
#: The first wait between two tries, doubled up to the longest.
FIRST_WAIT = 0.25
LONGEST_WAIT = 2.0
#: Methods whose request repeats, while it started no command.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
#: Stages of an operation's transaction: what a cut means depends on how far it got.
CONNECTING, RUNNING, COMMITTING = "connecting", "running", "committing"
#: Read only, shut down, crashed and still starting up. And below, ``08…``, Postgres's class of connection exceptions.
CUT_STATES = frozenset({"25006", "57P01", "57P02", "57P03"})
CONNECTION_EXCEPTIONS = "08"


class DatabaseCut(OperationError):
    """The database went away for a moment: 503, always with ``Retry-After``.

    ``repeatable``: it is known that nothing was applied, so the same call may run again. Only then ``retry_after`` is
    set, as ``OperationError`` asks of a failure that ran nothing. Otherwise it may have done something, and its message
    asks the person to check before trying again.
    """

    status = 503
    code = "database_unavailable"

    def __init__(self, *, repeatable: bool) -> None:
        if repeatable:
            super().__init__(gettext("ERPlora will be back in a moment: try again in a few seconds."), retry_after=RETRY_AFTER_SECONDS)
        else:
            message = gettext("The connection was lost while this was being saved. Check whether it was saved before trying again.")
            super().__init__(message, code="database_outcome_unknown")
        self.repeatable = repeatable


def enabled() -> bool:
    return "database_cut" in getattr(settings, "LIVE", {})


def is_cut(exc: BaseException | None) -> bool:
    """Whether ``exc`` is the database going away for a moment, in a project that waits for it."""
    if not isinstance(exc, Error) or not enabled():
        return False
    state = getattr(exc.__cause__, "sqlstate", None)
    if state is None:
        # No answer of the server to read: a lost connection, a refused one, a pool with nothing to give.
        return isinstance(exc, OperationalError)
    return state in CUT_STATES or state.startswith(CONNECTION_EXCEPTIONS)


# --- The state of one request -----------------------------------------------------------------------------------------


@dataclass
class _Request:
    deadline: float | None = None
    next_wait: float = FIRST_WAIT
    view_started: bool = False
    command_started: bool = False


#: The running request's, when the middleware is on: a command may run with a context that does not name its request.
_running: ContextVar[_Request | None] = ContextVar("live_database_cut_request", default=None)


def _state(request: HttpRequest) -> _Request:
    state = getattr(request, "_database_cut", None)
    if state is None:
        state = request._database_cut = _Request()
    return state


def command_started() -> None:
    """A command's body is about to run: from here this request no longer repeats whole, whatever its method."""
    state = _running.get()
    if state is not None:
        state.command_started = True


def may_repeat(request: HttpRequest) -> bool:
    """Whether the whole request may run again: nothing it started can have been applied."""
    state = _state(request)
    if state.command_started:
        return False
    return request.method in SAFE_METHODS or not state.view_started


def next_wait(request: HttpRequest) -> float | None:
    """The seconds to wait before the next try of this request, ``None`` past its limit or if its caller retries.

    The limit is the whole request's, counted from its first cut, whoever asks. Each wait is random in its second half,
    so the requests a cut caught at once do not all come back at once.
    """
    config = settings.LIVE["database_cut"]
    if request.path.startswith(tuple(config.get("no_wait_prefixes", ()))):
        return None
    state = _state(request)
    now = time.monotonic()
    if state.deadline is None:
        state.deadline = now + config["wait_seconds"]
    left = state.deadline - now
    if left <= 0:
        return None
    wait = state.next_wait
    state.next_wait = min(wait * 2, LONGEST_WAIT)
    return min(random.uniform(wait / 2, wait), left)


def release_connections() -> None:
    """Drop this thread's connections, so the next try opens new ones. Run in the thread of the failed try.

    The socket closes first: a pool would hand out again a connection that only went back to it, and a session on the
    old writer stays read only for as long as it lives. One inside a transaction is left to whoever opened it.
    """
    for connection in connections.all(initialized_only=True):
        if connection.in_atomic_block:
            continue
        if connection.connection is not None:
            connection.connection.close()
        connection.close()


# --- The answer -------------------------------------------------------------------------------------------------------


def cut_of(exc: BaseException | None, request: HttpRequest) -> DatabaseCut | None:
    """``exc`` as the cut a request answers with, or ``None`` if it is no cut. Raised outside a route, or outside any
    operation, it only promises what the whole request can: a view may have written before it."""
    if isinstance(exc, DatabaseCut):
        return exc if not exc.repeatable or may_repeat(request) else DatabaseCut(repeatable=False)
    if is_cut(exc):
        return DatabaseCut(repeatable=may_repeat(request))
    return None


def current_cut(request: HttpRequest) -> DatabaseCut | None:
    """The cut a project's ``handler500`` is being called for, or ``None``: it answers it with :func:`marked`."""
    return cut_of(sys.exc_info()[1], request)


def marked(response: HttpResponseBase, error: BaseException) -> HttpResponseBase:
    """``response``, when ``error`` is a cut: 503 for a moment, never cached, and marked for the middleware to look at."""
    if isinstance(error, DatabaseCut):
        response["Retry-After"] = str(RETRY_AFTER_SECONDS)
        add_never_cache_headers(response)
        response.database_cut = error
    return response


# --- Who waits --------------------------------------------------------------------------------------------------------


def _wait_or_raise(request: HttpRequest, exc: Exception) -> float:
    """The wait before the next try of the operation that raised ``exc``, or the error it ends with."""
    if isinstance(exc, DatabaseCut):
        wait = next_wait(request) if exc.repeatable else None
        if wait is None:
            raise exc
        return wait
    if not is_cut(exc):
        raise exc
    # The operation turns its own cuts into DatabaseCut: this one is from reading who asks, before it ran.
    wait = next_wait(request)
    if wait is None:
        raise DatabaseCut(repeatable=True) from exc
    return wait


def retrying(request: HttpRequest, call: Callable[[], T]) -> T:
    """``call()``, again while it fails with a cut that may repeat, within the request's limit."""
    while True:
        try:
            return call()
        except (DatabaseCut, Error) as exc:
            wait = _wait_or_raise(request, exc)
        release_connections()
        time.sleep(wait)


async def aretrying(request: HttpRequest, call: Callable[[], T]) -> T:
    """:func:`retrying` from an async route: ``call`` runs in the request's thread, and the wait holds none."""
    while True:
        try:
            return await sync_to_async(call)()
        except (DatabaseCut, Error) as exc:
            wait = _wait_or_raise(request, exc)
        await sync_to_async(release_connections)()
        await asyncio.sleep(wait)


class DatabaseCutMiddleware:
    """Repeats the request that a cut stopped, when it may repeat. First in ``MIDDLEWARE``, after the health checks."""

    sync_capable = True
    async_capable = True

    def __init__(self, get_response: Any) -> None:
        self.get_response = get_response
        self.is_async = iscoroutinefunction(get_response)
        if self.is_async:
            markcoroutinefunction(self)

    def __call__(self, request: HttpRequest) -> Any:
        if self.is_async:
            return self._acall(request)
        token = _running.set(_state(request))
        try:
            while True:
                response = self.get_response(request)
                wait = self._wait(request, response)
                if wait is None:
                    return response
                release_connections()
                time.sleep(wait)
        finally:
            _running.reset(token)

    async def _acall(self, request: HttpRequest) -> HttpResponseBase:
        token = _running.set(_state(request))
        try:
            while True:
                response = await self.get_response(request)
                wait = self._wait(request, response)
                if wait is None:
                    return response
                await sync_to_async(release_connections)()
                await asyncio.sleep(wait)
        finally:
            _running.reset(token)

    def process_view(self, request: HttpRequest, view_func: Any, view_args: Any, view_kwargs: Any) -> None:
        # A route of the API writes only through its operations, and a command says when it starts. Until then a cut (who
        # is asking is read inside the route: the session, an API key) has applied nothing, whatever the method.
        if not is_api_path(request.path_info):
            _state(request).view_started = True

    @staticmethod
    def _wait(request: HttpRequest, response: HttpResponseBase) -> float | None:
        if getattr(response, "database_cut", None) is None or not may_repeat(request):
            return None
        return next_wait(request)
