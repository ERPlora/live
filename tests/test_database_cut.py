"""A cut of the database: a read waits and tries again, a write that may have been applied never repeats (saas#284).

Against the real Postgres, without mocking what can be provoked: ``pg_terminate_backend`` is the server cutting a
connection, ``default_transaction_read_only`` the writer refusing writes, and ``DatabaseDoor`` (a TCP door in front of
Postgres) the network going down and the answer to a COMMIT that never comes back.

This module is also the URLconf of its own tests (``ROOT_URLCONF = __name__``) and the project's side of the piece: its
``handler500`` and a middleware that reads the database before any view runs, as a session does.
"""

import asyncio
import socket
import threading
import time
from collections import Counter
from collections.abc import Callable
from contextlib import nullcontext

import psycopg
import pytest
from asgiref.sync import sync_to_async
from django.db import OperationalError, connections, transaction
from django.http import HttpResponse, HttpResponseServerError
from django.test import AsyncClient, Client
from django.urls import path
from django.utils import translation
from live.context import OperationContext, Scope
from live.database_cut import DatabaseCut, current_cut, marked
from live.errors import Conflict, LiveMisuse
from live.executor import Executor, Stream, Subscription
from live.live_view import live_stream
from live.ninja import install_error_handlers, run_operation, run_operation_sync
from live.operations import INTERNAL, operation, registry
from ninja import NinjaAPI, Router, Schema
from psycopg import sql

from tests.live_helpers import drain
from tests.testapp.models import Thing

pytestmark = pytest.mark.django_db(databases=["default", "other"], transaction=True)

MIDDLEWARE = ["live.database_cut.DatabaseCutMiddleware", "tests.test_database_cut.ReadsBeforeTheView"]
UNAVAILABLE = "database_unavailable"
UNKNOWN = "database_outcome_unknown"
APPLIED = "database_answer_lost"
WAIT_SECONDS = 2

#: How many times each named piece ran in this test.
runs: Counter = Counter()
#: What each named piece does in this test: ``(its run number) -> the answer``.
script: dict[str, Callable[[int], object]] = {}
#: The DSN of the test database, for the connection that cuts the others (never the one being cut).
admin_dsn: list[str] = []


def scripted(name: str) -> object:
    runs[name] += 1
    return script[name](runs[name])


class Empty(Schema):
    pass


class Answer(Schema):
    rows: int = 0


def _declare(name: str, kind: str, **options):
    def body(ctx, data):
        return {"rows": scripted(name) or 0}

    body.__module__ = "tests.fakeapp." + ("services" if kind == "command" else "queries")
    return operation(
        f"cuttest.probe.{name}", kind=kind, permission=None, input=Empty, output=Answer, ai=INTERNAL, **options
    )(body)


READ = _declare("read", "query")
WRITE = _declare("write", "command")
REPEATABLE = _declare("repeatable", "command", repeatable=True)
THIRD_PARTY = _declare("thirdparty", "command", database=False)


def _outer_body(ctx, data):
    """A command that runs another one inside it, as one that records its event through another operation."""
    WRITE(ctx, Empty())
    return {"rows": scripted("outer") or 0}


_outer_body.__module__ = "tests.fakeapp.services"
OUTER = operation("cuttest.probe.outer", kind="command", permission=None, input=Empty, output=Answer, ai=INTERNAL)(_outer_body)
OPERATIONS = (READ, WRITE, REPEATABLE, THIRD_PARTY, OUTER)


# --- The project's side -----------------------------------------------------------------------------------------------


class ProbeBuilder:
    """Builds a context with no permission check to pass; ``builder`` and ``refresh`` scripted when a test names them."""

    def from_request(self, request) -> OperationContext:
        if "builder" in script:
            scripted("builder")
        return self._context(request)

    def refresh(self, ctx: OperationContext) -> OperationContext:
        if "refresh" in script:
            scripted("refresh")
        return ctx

    @staticmethod
    def _context(request=None) -> OperationContext:
        return OperationContext(scope=Scope("host", "a"), actor="ana", permissions=frozenset({"*"}), request=request)


class ReadsBeforeTheView:
    """Reads the database before any view runs, as the session and the signed-in person do."""

    def __init__(self, get_response) -> None:
        self.get_response = get_response

    def __call__(self, request):
        if "before" in script:
            scripted("before")
        return self.get_response(request)


def server_error(request):
    cut = current_cut(request)
    if cut is not None:
        return marked(HttpResponse(cut.code, status=503), cut)
    return HttpResponseServerError("server error")


def page(request):
    return HttpResponse(str(scripted("page")))


def page_after_a_command(request):
    WRITE(ProbeBuilder._context(request), Empty())
    return HttpResponse(str(scripted("page")))


router = Router()


@router.get("/read", response=Answer)
def read(request):
    return run_operation_sync(request, READ.name)


@router.get("/aread", response=Answer)
async def aread(request):
    return await run_operation(request, READ.name)


@router.get("/raw", response=Answer)
def raw_read(request):
    return {"rows": scripted("raw")}


@router.post("/raw", response=Answer)
def raw_write(request):
    return {"rows": scripted("raw")}


def reads_who_asks(request):
    """A route's authentication, as the session or an API key: inside the route, before its operation."""
    scripted("auth")
    return True


@router.post("/after-auth", response=Answer, auth=reads_who_asks)
def after_auth(request):
    return run_operation_sync(request, WRITE.name)


@router.post("/after-third-party", response=Answer)
def after_third_party(request):
    run_operation_sync(request, THIRD_PARTY.name)
    return {"rows": scripted("raw")}


@router.post("/after-write", response=Answer)
def after_write(request):
    run_operation_sync(request, WRITE.name)
    return {"rows": scripted("raw")}


@router.post("/after-repeatable", response=Answer)
def after_repeatable(request):
    run_operation_sync(request, REPEATABLE.name)
    return {"rows": scripted("raw")}


@router.post("/after-nested", response=Answer)
def after_nested(request):
    run_operation_sync(request, OUTER.name)
    return {"rows": scripted("raw")}


@router.post("/after-two-writes", response=Answer)
def after_two_writes(request):
    """The second write may fail: the route goes on, as one that tells apart what it can do without it."""
    run_operation_sync(request, WRITE.name)
    try:
        run_operation_sync(request, WRITE.name)
    except Conflict:
        pass
    return {"rows": scripted("raw")}


@router.post("/after-write-in-its-transaction", response=Answer)
def after_write_in_its_transaction(request):
    with transaction.atomic():
        run_operation_sync(request, WRITE.name)
        return {"rows": scripted("raw")}


@router.post("/write", response=Answer)
def write(request):
    return run_operation_sync(request, WRITE.name)


@router.post("/repeatable", response=Answer)
def repeatable(request):
    return run_operation_sync(request, REPEATABLE.name)


@router.post("/arepeatable", response=Answer)
async def arepeatable(request):
    return await run_operation(request, REPEATABLE.name)


api = NinjaAPI(urls_namespace="live-test-database-cut")
install_error_handlers(api)
api.add_router("", router)

urlpatterns = [
    path("api/live", live_stream),
    path("api/", api.urls),
    path("page", page),
    path("internal/page", page),
    path("page-after-a-command", page_after_a_command),
]
handler500 = "tests.test_database_cut.server_error"


def on_other(op, ctx):
    """``LIVE["operation_database"]``: the operation's transaction opens on the alias behind the door."""
    return nullcontext("other")


def read_on_other(op, ctx):
    """``LIVE["operation_database"]``: the commands on ``default``, the reads on ``other``, as a hub's and control."""
    return nullcontext("other" if op.kind == "query" else "default")


# --- Cutting the database for real ------------------------------------------------------------------------------------


def _admin() -> psycopg.Connection:
    """The connection that cuts the others: never read only itself, or it could not undo ``set_read_only``."""
    return psycopg.connect(admin_dsn[0], autocommit=True, options="-c default_transaction_read_only=off")


def terminate(alias: str = "default") -> None:
    """The server cuts this thread's connection, as a restart or a switchover does (57P01)."""
    connections[alias].ensure_connection()
    pid = connections[alias].connection.info.backend_pid
    with _admin() as admin:
        admin.execute("SELECT pg_terminate_backend(%s)", (pid,))
        deadline = time.monotonic() + 5
        while admin.execute("SELECT 1 FROM pg_stat_activity WHERE pid = %s", (pid,)).fetchone():
            assert time.monotonic() < deadline, "the backend outlived pg_terminate_backend"
            time.sleep(0.01)


def set_read_only(on: bool) -> None:
    """New sessions of the test database are read only, as the old writer is during a switchover."""
    name = sql.Identifier(connections["default"].settings_dict["NAME"])
    statement = "ALTER DATABASE {} SET default_transaction_read_only = on" if on else "ALTER DATABASE {} RESET default_transaction_read_only"
    with _admin() as admin:
        admin.execute(sql.SQL(statement).format(name))


def things_in_the_database() -> int:
    with _admin() as admin:
        return admin.execute("SELECT count(*) FROM testapp_thing").fetchone()[0]


class DatabaseDoor:
    """A TCP door in front of Postgres: closing it is the network going down; ``lose_commit_answer`` lets a COMMIT reach
    the server, which applies it, and closes everything before its answer comes back."""

    def __init__(self, host: str, port: int) -> None:
        self.target = (host, port)
        self.lose_commit_answer = False
        self.port = 0
        self._listener: socket.socket | None = None
        self._sockets: list[socket.socket] = []
        self._answers_lost = threading.Event()
        self.open()

    def open(self) -> None:
        self._listener = socket.create_server(("127.0.0.1", self.port))
        self.port = self._listener.getsockname()[1]
        threading.Thread(target=self._accept, args=(self._listener,), daemon=True).start()

    def close(self) -> None:
        listener, self._listener = self._listener, None
        if listener is not None:
            # On Linux a close alone leaves the blocked accept, and with it the port, alive: the shutdown wakes it
            # (EINVAL). macOS wakes it on close and refuses the shutdown of a listening socket (ENOTCONN).
            try:
                listener.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            listener.close()
        for each in self._sockets:
            try:
                each.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            each.close()
        self._sockets.clear()

    def _accept(self, listener: socket.socket) -> None:
        while True:
            try:
                client, _ = listener.accept()
            except OSError:
                return
            if self._listener is not listener:
                # Slipped in while the door was closing: the door is closed.
                client.close()
                return
            server = socket.create_connection(self.target)
            self._sockets += [client, server]
            threading.Thread(target=self._to_server, args=(client, server), daemon=True).start()
            threading.Thread(target=self._to_client, args=(server, client), daemon=True).start()

    def _to_server(self, client: socket.socket, server: socket.socket) -> None:
        try:
            while chunk := client.recv(65536):
                if self.lose_commit_answer and b"COMMIT" in chunk:
                    self._answers_lost.set()
                    server.sendall(chunk)
                    # The server reads it and applies it; the client only ever sees the connection go.
                    time.sleep(0.2)
                    self.close()
                    return
                server.sendall(chunk)
        except OSError:
            pass

    def _to_client(self, server: socket.socket, client: socket.socket) -> None:
        try:
            while chunk := server.recv(65536):
                if not self._answers_lost.is_set():
                    client.sendall(chunk)
        except OSError:
            pass


@pytest.fixture
def door(settings):
    """The alias ``other``, where the operations now run, reaches Postgres through a door."""
    connection = connections["other"]
    connection.close()
    original = connection.settings_dict["HOST"], connection.settings_dict["PORT"]
    opened = DatabaseDoor(original[0], int(original[1]))
    connection.settings_dict["HOST"], connection.settings_dict["PORT"] = "127.0.0.1", opened.port
    settings.LIVE = {**settings.LIVE, "operation_database": "tests.test_database_cut.on_other"}
    yield opened
    connection.close()
    connection.settings_dict["HOST"], connection.settings_dict["PORT"] = original
    opened.close()


def insert_on_other() -> int:
    with connections["other"].cursor() as cursor:
        cursor.execute("INSERT INTO testapp_thing (name) VALUES ('once')")
    return 1


@pytest.fixture(autouse=True)
def project(settings, transactional_db, db_dsn):
    settings.ROOT_URLCONF = __name__
    settings.MIDDLEWARE = MIDDLEWARE
    settings.LIVE = {
        **settings.LIVE,
        "context_builder": "tests.test_database_cut.ProbeBuilder",
        "database_cut": {"wait_seconds": WAIT_SECONDS, "no_wait_prefixes": ("/internal/",)},
    }
    admin_dsn[:] = [db_dsn]
    runs.clear()
    script.clear()
    for op in OPERATIONS:
        registry[op.name] = op
    yield
    for op in OPERATIONS:
        registry.pop(op.name, None)
    set_read_only(False)
    # A connection this test cut must not reach the flush between tests.
    connections.close_all()


@pytest.fixture
def client():
    return Client(raise_request_exception=False)


def code_of(response) -> str:
    return response.json()["error"]["code"]


def cut_once(attempt: int) -> int:
    """Cut on the first run, a good answer after it."""
    if attempt == 1:
        terminate()
    return Thing.objects.count() + 7


def always_cut(attempt: int) -> int:
    terminate()
    return Thing.objects.count()


async def async_request(method: str, url: str):
    """Through the async chain; the connection left in the request's thread goes with the test."""
    response = await getattr(AsyncClient(raise_request_exception=False), method)(url)
    await sync_to_async(connections.close_all)()
    return response


# --- Reads ------------------------------------------------------------------------------------------------------------


def test_a_read_cut_halfway_waits_and_answers(client):
    script["read"] = cut_once

    response = client.get("/api/read")

    assert response.status_code == 200, response.content
    assert response.json() == {"rows": 7}
    assert runs["read"] == 2


def test_a_read_that_stays_cut_answers_503_with_retry_after_within_the_limit(client):
    script["read"] = always_cut

    started = time.monotonic()
    response = client.get("/api/read")
    took = time.monotonic() - started

    assert response.status_code == 503, response.content
    assert code_of(response) == UNAVAILABLE
    assert int(response["Retry-After"]) > 0
    assert runs["read"] > 1
    assert WAIT_SECONDS * 0.5 <= took < WAIT_SECONDS + 2


def test_the_limit_is_shared_by_every_try_of_the_request(client):
    """The route's own tries spend the limit: the middleware that receives its 503 does not wait it all over again."""
    script["read"] = always_cut

    started = time.monotonic()
    client.get("/api/read")

    assert time.monotonic() - started < WAIT_SECONDS + 2


def test_without_the_setting_nothing_changes(client, settings, caplog):
    """A project that has not asked for it (the Hub until hub#831) keeps today's answer, and the driver's error."""
    settings.LIVE = {key: value for key, value in settings.LIVE.items() if key != "database_cut"}
    script["read"] = cut_once

    response = client.get("/api/read")

    assert response.status_code == 500
    assert code_of(response) == "internal_error"
    assert "Retry-After" not in response
    assert runs["read"] == 1
    assert [record.exc_info[0] for record in caplog.records if record.exc_info] == [OperationalError]


@pytest.mark.parametrize(
    "statements",
    [
        pytest.param(["SET LOCAL statement_timeout = '10ms'", "SELECT pg_sleep(1)"], id="a statement timeout (57014)"),
        pytest.param(["SELECT 1 / 0"], id="a division by zero (22012)"),
        pytest.param(["SELECT * FROM no_such_table"], id="a missing table (42P01)"),
    ],
)
def test_a_failure_that_is_no_cut_stays_the_error_it_was(client, statements):
    def fails(attempt):
        with connections["default"].cursor() as cursor:
            for statement in statements:
                cursor.execute(statement)

    script["read"] = fails

    response = client.get("/api/read")

    assert response.status_code == 500
    assert code_of(response) == "internal_error"
    assert runs["read"] == 1


def test_the_context_of_the_operation_is_read_again_after_a_cut(client):
    """Who is asking is the first read of a request: a cut there is a cut of the read."""
    script["builder"] = lambda attempt: cut_once(attempt)
    script["read"] = lambda attempt: 1

    response = client.get("/api/read")

    assert response.status_code == 200, response.content
    assert (runs["builder"], runs["read"]) == (2, 1)


@pytest.mark.parametrize(
    ("url", "piece"),
    [pytest.param("/api/aread", "read", id="an async route"), pytest.param("/page", "page", id="the async middleware")],
)
async def test_waiting_does_not_hold_the_event_loop(settings, url, piece):
    settings.MIDDLEWARE = MIDDLEWARE[:1]  # Only async-capable: the chain runs on the loop, no thread of its own to sleep in.
    script[piece] = always_cut
    gaps = []

    async def ticker():
        last = time.monotonic()
        while True:
            await asyncio.sleep(0.02)
            now = time.monotonic()
            gaps.append(now - last)
            last = now

    ticking = asyncio.ensure_future(ticker())
    response = await async_request("get", url)
    ticking.cancel()

    assert response.status_code == 503, response.content
    assert runs[piece] > 1
    # Waits reach 0.5 s and more: a loop asleep for one of them would show here.
    assert max(gaps) < 0.4


async def test_an_async_route_answers_after_the_cut():
    script["read"] = cut_once

    response = await async_request("get", "/api/aread")

    assert response.status_code == 200, response.content
    assert runs["read"] == 2


# --- Pages, outside any operation -------------------------------------------------------------------------------------


def test_a_page_cut_halfway_waits_and_answers(client):
    script["page"] = cut_once

    response = client.get("/page")

    assert response.status_code == 200, response.content
    assert response.content == b"7"
    assert runs["page"] == 2


def test_a_page_that_stays_cut_answers_503_with_retry_after(client):
    script["page"] = always_cut

    response = client.get("/page")

    assert response.status_code == 503, response.content
    assert response.content == UNAVAILABLE.encode()
    assert int(response["Retry-After"]) > 0
    assert runs["page"] > 1


@pytest.mark.parametrize("chain", [MIDDLEWARE[:1], MIDDLEWARE], ids=["all of it async", "with a sync middleware inside"])
async def test_a_page_waits_on_the_async_chain_too(settings, chain):
    settings.MIDDLEWARE = chain
    script["page"] = cut_once

    response = await async_request("get", "/page")

    assert response.status_code == 200, response.content
    assert runs["page"] == 2


def test_a_route_read_outside_its_operation_waits_too(client):
    """Whatever a route reads before its operation, an API key for instance."""
    script["raw"] = cut_once

    response = client.get("/api/raw")

    assert response.status_code == 200, response.content
    assert runs["raw"] == 2


def test_a_post_cut_while_reading_who_asks_is_applied_once(client):
    """The first read of a route on the panel. It writes only through its operation, and that one has not started."""
    script["auth"] = cut_once
    script["write"] = inserts

    response = client.post("/api/after-auth")

    assert response.status_code == 200, response.content
    assert (runs["auth"], runs["write"]) == (2, 1)
    assert things_in_the_database() == 1


def test_a_route_with_no_command_started_repeats_while_it_can(client):
    script["raw"] = always_cut

    response = client.post("/api/raw")

    assert response.status_code == 503, response.content
    assert code_of(response) == UNAVAILABLE
    assert int(response["Retry-After"]) > 0
    assert runs["raw"] > 1


def inserts(attempt: int) -> int:
    return Thing.objects.create(name="once") and 1


def test_a_route_cut_after_its_command_committed_says_it_was_saved(client):
    """A route writes only through its operation: once its one command committed, what the cut stopped is the answer."""
    script["write"] = inserts
    script["raw"] = always_cut

    response = client.post("/api/after-write")

    assert response.status_code == 503, response.content
    assert code_of(response) == APPLIED
    assert response.json()["error"]["message"] == DatabaseCut(repeatable=False, applied=True).message
    assert int(response["Retry-After"]) > 0
    assert (runs["write"], runs["raw"]) == (1, 1)
    assert things_in_the_database() == 1


def test_a_route_cut_after_a_call_to_a_third_party_says_it_was_done(client):
    """A command with no database has no transaction to undo what it did on the network: it answered, so it was done."""
    script["thirdparty"] = lambda attempt: 1
    script["raw"] = always_cut

    response = client.post("/api/after-third-party")

    assert response.status_code == 503, response.content
    assert code_of(response) == APPLIED
    assert (runs["thirdparty"], runs["raw"]) == (1, 1)


def test_a_route_cut_after_its_command_was_tried_again_says_it_was_saved(client):
    """The try a cut rolled back left nothing: the command was applied once, by the try after it."""
    script["repeatable"] = insert_then_cut_once
    script["raw"] = always_cut

    response = client.post("/api/after-repeatable")

    assert response.status_code == 503, response.content
    assert code_of(response) == APPLIED
    assert (runs["repeatable"], runs["raw"]) == (2, 1)
    assert things_in_the_database() == 1


def test_a_route_cut_after_a_command_that_ran_another_one_says_it_was_saved(client):
    """The one inside commits with the outer one: the route still ran one command."""
    script["write"] = inserts
    script["outer"] = lambda attempt: 1
    script["raw"] = always_cut

    response = client.post("/api/after-nested")

    assert response.status_code == 503, response.content
    assert code_of(response) == APPLIED
    assert (runs["write"], runs["outer"], runs["raw"]) == (1, 1, 1)
    assert things_in_the_database() == 1


def test_a_route_cut_after_two_commands_does_not_say_what_was_saved(client):
    """With a second command that failed, the first one alone was applied: the person checks."""

    def inserts_then_refuses(attempt):
        if attempt == 2:
            raise Conflict("refused", code="cuttest.refused")
        return inserts(attempt)

    script["write"] = inserts_then_refuses
    script["raw"] = always_cut

    response = client.post("/api/after-two-writes")

    assert response.status_code == 503, response.content
    assert code_of(response) == UNKNOWN
    assert (runs["write"], runs["raw"]) == (2, 1)
    assert things_in_the_database() == 1


def test_a_route_cut_after_two_commands_applied_does_not_say_it_was_saved_either(client):
    """One route, one operation: more than one, and the answer cannot tell what the person asked for."""
    script["write"] = inserts
    script["raw"] = always_cut

    response = client.post("/api/after-two-writes")

    assert response.status_code == 503, response.content
    assert code_of(response) == UNKNOWN
    assert things_in_the_database() == 2


def test_a_route_cut_inside_the_transaction_its_command_ran_in_does_not_say_it_was_saved(client):
    """A command inside someone else's transaction commits with it: the cut rolled it back, and only a cut at the
    right moment could tell."""
    script["write"] = inserts
    script["raw"] = always_cut

    response = client.post("/api/after-write-in-its-transaction")

    assert response.status_code == 503, response.content
    assert code_of(response) == UNKNOWN
    assert things_in_the_database() == 0


def test_a_cut_of_what_answers_at_once_does_not_wait(client):
    """Who calls ``no_wait_prefixes`` tries again on its own (the Hub's /internal calls, Stripe's webhooks)."""
    script["page"] = always_cut

    response = client.get("/internal/page")

    assert response.status_code == 503
    assert int(response["Retry-After"]) > 0
    assert runs["page"] == 1


@pytest.mark.parametrize("method", ["get", "post"])
def test_a_cut_before_the_view_repeats_the_request_whatever_its_method(client, method):
    """No view ran: nothing can have been applied."""
    script["before"] = cut_once
    script["page"] = lambda attempt: 1

    response = getattr(client, method)("/page")

    assert response.status_code == 200, response.content
    assert (runs["before"], runs["page"]) == (2, 1)


def test_a_post_cut_inside_its_view_is_never_repeated(client):
    """A view that is no operation may have written anything before the cut."""
    script["page"] = always_cut

    response = client.post("/page")

    assert response.status_code == 503
    assert response.content == UNKNOWN.encode()
    assert int(response["Retry-After"]) > 0
    assert runs["page"] == 1


def test_a_get_that_ran_a_command_is_never_repeated(client):
    """A GET is safe to repeat only while it writes nothing: the command already committed stays once. A page may write
    outside its operations, so it never says it was saved."""
    script["write"] = inserts
    script["page"] = always_cut

    response = client.get("/page-after-a-command")

    assert response.status_code == 503
    assert response.content == UNKNOWN.encode()
    assert (runs["write"], runs["page"]) == (1, 1)
    assert things_in_the_database() == 1


# --- Writes -----------------------------------------------------------------------------------------------------------


def insert_then_cut_once(attempt: int) -> int:
    Thing.objects.create(name="once")
    if attempt == 1:
        terminate()
    return Thing.objects.count()


def test_a_command_cut_in_its_body_is_not_repeated_unless_it_says_so(client):
    """Its database rolled back, but what it did outside (a charge, a mail) is not the database's to undo."""
    script["write"] = insert_then_cut_once

    response = client.post("/api/write")

    assert response.status_code == 503, response.content
    assert code_of(response) == UNKNOWN
    assert int(response["Retry-After"]) > 0
    assert runs["write"] == 1
    assert things_in_the_database() == 0


def test_a_repeatable_command_cut_in_its_body_is_applied_once(client):
    script["repeatable"] = insert_then_cut_once

    response = client.post("/api/repeatable")

    assert response.status_code == 200, response.content
    assert runs["repeatable"] == 2
    assert things_in_the_database() == 1


async def test_a_repeatable_command_is_applied_once_on_an_async_route():
    script["repeatable"] = insert_then_cut_once

    response = await async_request("post", "/api/arepeatable")

    assert response.status_code == 200, response.content
    assert runs["repeatable"] == 2
    assert await asyncio.to_thread(things_in_the_database) == 1


def read_only_for_the_first_session(attempt: int) -> int:
    if attempt == 1:
        # New sessions write again; this one stays read only, as a connection to the old writer does.
        set_read_only(False)
    Thing.objects.create(name="once")
    return Thing.objects.count()


def test_a_write_refused_as_read_only_on_a_repeatable_command_is_applied_once(client):
    set_read_only(True)
    connections["default"].close()
    script["repeatable"] = read_only_for_the_first_session

    response = client.post("/api/repeatable")

    assert response.status_code == 200, response.content
    assert runs["repeatable"] == 2
    assert things_in_the_database() == 1


def test_a_write_refused_as_read_only_on_any_other_command_is_not_repeated(client):
    set_read_only(True)
    connections["default"].close()
    script["write"] = read_only_for_the_first_session

    response = client.post("/api/write")

    assert response.status_code == 503, response.content
    assert code_of(response) == UNKNOWN
    assert runs["write"] == 1
    assert things_in_the_database() == 0


def test_a_command_that_could_not_connect_repeats_because_its_body_never_ran(client, door):
    """Any command, declared or not: nothing of it has run."""
    door.close()
    threading.Timer(0.3, door.open).start()
    script["write"] = lambda attempt: insert_on_other()

    response = client.post("/api/write")

    assert response.status_code == 200, response.content
    assert runs["write"] == 1
    assert things_in_the_database() == 1


def test_a_command_that_never_connects_answers_503_with_nothing_applied(client, door):
    door.close()
    script["write"] = lambda attempt: insert_on_other()

    response = client.post("/api/write")

    assert response.status_code == 503, response.content
    assert code_of(response) == UNAVAILABLE
    assert runs["write"] == 0


def test_the_answer_to_a_commit_lost_never_repeats_a_write_already_applied(client, door):
    """The worst cut there is: applied, and nobody can know. Not even a command declared repeatable runs again."""
    door.lose_commit_answer = True
    script["repeatable"] = lambda attempt: insert_on_other()

    response = client.post("/api/repeatable")

    assert response.status_code == 503, response.content
    assert code_of(response) == UNKNOWN
    assert int(response["Retry-After"]) > 0
    assert runs["repeatable"] == 1
    assert things_in_the_database() == 1


def test_a_query_inside_a_command_answers_for_the_command(client):
    """The query alone could repeat; what repeats is the outermost operation, and that one does not say it can."""

    def calls_a_query(attempt):
        script["read"] = always_cut
        READ(ProbeBuilder._context(), Empty())

    script["write"] = calls_a_query

    response = client.post("/api/write")

    assert response.status_code == 503, response.content
    assert code_of(response) == UNKNOWN
    assert (runs["write"], runs["read"]) == (1, 1)


def test_a_query_on_another_database_inside_a_command_answers_for_the_command(client, settings):
    """Not in a transaction of its own alias, and still not the one that decides: the command runs once."""
    settings.LIVE = {**settings.LIVE, "operation_database": "tests.test_database_cut.read_on_other"}

    def inserts_then_reads_elsewhere(attempt):
        Thing.objects.create(name="once")
        READ(ProbeBuilder._context(), Empty())

    def reads(attempt):
        terminate("other")
        with connections["other"].cursor() as cursor:
            cursor.execute("SELECT 1")

    script["write"] = inserts_then_reads_elsewhere
    script["read"] = reads

    response = client.post("/api/write")

    assert response.status_code == 503, response.content
    assert code_of(response) == UNKNOWN
    assert (runs["write"], runs["read"]) == (1, 1)
    assert things_in_the_database() == 0


def test_repeatable_is_only_for_a_command_that_uses_its_database():
    def body(ctx, data):
        return {}

    body.__module__ = "tests.fakeapp.queries"
    with pytest.raises(LiveMisuse):
        operation("cuttest.probe.badquery", kind="query", permission=None, input=Empty, output=Answer, ai=INTERNAL, repeatable=True)(body)
    body.__module__ = "tests.fakeapp.services"
    with pytest.raises(LiveMisuse):
        operation(
            "cuttest.probe.badnodb",
            kind="command",
            permission=None,
            input=Empty,
            output=Answer,
            ai=INTERNAL,
            database=False,
            repeatable=True,
        )(body)


# --- The live stream --------------------------------------------------------------------------------------------------


def _stream() -> Stream:
    return Stream(ProbeBuilder._context())


async def _pass_of(stream: Stream, sleeps: list[float] | None = None) -> list:
    waits = [] if sleeps is None else sleeps

    async def sleep(seconds):
        waits.append(seconds)

    executor = Executor(sleep=sleep)
    try:
        await executor.run_all(stream)
    finally:
        executor.reset()
        executor.shutdown()
    return await drain(stream.queue)


async def test_a_live_query_cut_is_a_passing_error_of_its_pass():
    script["read"] = cut_once
    stream = _stream()
    stream.subs["s1"] = Subscription(id="s1", op=READ, params=Empty())
    sleeps: list[float] = []

    frames = await _pass_of(stream, sleeps)

    assert [(each.event, each.data.get("data")) for each in frames] == [("result", {"rows": 7})]
    assert len(sleeps) == 1
    assert runs["read"] == 2


async def test_a_cut_while_rereading_the_stream_context_is_a_passing_error_too():
    script["refresh"] = cut_once
    script["read"] = lambda attempt: 1
    stream = _stream()
    stream.subs["s1"] = Subscription(id="s1", op=READ, params=Empty())

    frames = await _pass_of(stream)

    assert [(each.event, each.data.get("data")) for each in frames] == [("result", {"rows": 1})]
    assert runs["refresh"] == 2


async def test_a_live_query_that_stays_cut_tells_its_stream_to_come_back():
    script["read"] = always_cut
    stream = _stream()
    stream.subs["s1"] = Subscription(id="s1", op=READ, params=Empty())

    frames = await _pass_of(stream)

    assert [(each.event, each.data["error"]["code"]) for each in frames] == [("error", UNAVAILABLE)]
    assert runs["read"] == 4


def test_a_live_stream_that_cannot_open_answers_503_with_retry_after(client):
    script["builder"] = always_cut

    response = client.get("/api/live")

    assert response.status_code == 503, response.content
    assert int(response["Retry-After"]) > 0
    assert runs["builder"] > 1


def test_a_live_stream_whose_context_runs_an_operation_answers_503_with_retry_after(client):
    def runs_a_query(attempt):
        script["read"] = always_cut
        READ(ProbeBuilder._context(), Empty())

    script["builder"] = runs_a_query

    response = client.get("/api/live")

    assert response.status_code == 503, response.content
    assert code_of(response) == UNAVAILABLE
    assert int(response["Retry-After"]) > 0
    assert runs["builder"] > 1


# --- What the person reads --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("outcome", [{"repeatable": True}, {"repeatable": False}, {"repeatable": False, "applied": True}])
def test_the_message_is_translated(outcome):
    with translation.override("en"):
        english = DatabaseCut(**outcome).message
    with translation.override("es"):
        spanish = DatabaseCut(**outcome).message

    assert english and spanish and english != spanish


def test_each_outcome_says_its_own_thing():
    """Nothing applied, applied with its answer lost, or nobody can know: three codes, three messages."""
    outcomes = [DatabaseCut(repeatable=True), DatabaseCut(repeatable=False), DatabaseCut(repeatable=False, applied=True)]

    assert [cut.code for cut in outcomes] == [UNAVAILABLE, UNKNOWN, APPLIED]
    assert len({cut.message for cut in outcomes}) == 3


def test_applied_is_never_repeatable():
    with pytest.raises(LiveMisuse):
        DatabaseCut(repeatable=True, applied=True)


def test_only_what_ran_nothing_says_when_to_try_again_to_the_live_executor():
    """``OperationError.retry_after``: always ``None`` for a failure that may have done something."""
    assert DatabaseCut(repeatable=True).retry_after is not None
    assert DatabaseCut(repeatable=False).retry_after is None
    assert DatabaseCut(repeatable=False, applied=True).retry_after is None
