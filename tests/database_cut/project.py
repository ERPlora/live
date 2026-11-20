"""The project these tests run in: its operations, its side of the piece and the URLconf of the tests.

Each operation, the context builder and the pages run what a test scripts for them (``script``) and count their runs
(``runs``). The project's side is its ``handler500`` and a middleware that reads the database before any view runs, as a
session does.
"""

from collections import Counter
from collections.abc import Callable
from contextlib import nullcontext

from asgiref.sync import sync_to_async
from django.db import connections, transaction
from django.http import HttpResponse, HttpResponseServerError
from django.test import AsyncClient
from django.urls import path
from live.context import OperationContext, Scope
from live.database_cut import current_cut, marked
from live.errors import Conflict
from live.live_view import live_stream
from live.ninja import install_error_handlers, run_operation, run_operation_sync
from live.operations import INTERNAL, operation
from ninja import NinjaAPI, Router, Schema

MIDDLEWARE = ["live.database_cut.DatabaseCutMiddleware", "tests.database_cut.project.ReadsBeforeTheView"]
UNAVAILABLE = "database_unavailable"
UNKNOWN = "database_outcome_unknown"
APPLIED = "database_answer_lost"
WAIT_SECONDS = 2

#: How many times each named piece ran in this test.
runs: Counter = Counter()
#: What each named piece does in this test: ``(its run number) -> the answer``.
script: dict[str, Callable[[int], object]] = {}


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


@router.post("/after-write-then-one-in-a-transaction", response=Answer)
def after_write_then_one_in_a_transaction(request):
    """The first command owns its transaction; the second runs inside the route's, which a cut may roll back."""
    run_operation_sync(request, WRITE.name)
    with transaction.atomic():
        run_operation_sync(request, REPEATABLE.name)
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
handler500 = "tests.database_cut.project.server_error"


def on_other(op, ctx):
    """``LIVE["operation_database"]``: the operation's transaction opens on the alias behind the door."""
    return nullcontext("other")


def read_on_other(op, ctx):
    """``LIVE["operation_database"]``: the commands on ``default``, the reads on ``other``, as a hub's and control."""
    return nullcontext("other" if op.kind == "query" else "default")


def code_of(response) -> str:
    return response.json()["error"]["code"]


async def async_request(method: str, url: str):
    """Through the async chain; the connection left in the request's thread goes with the test."""
    response = await getattr(AsyncClient(raise_request_exception=False), method)(url)
    await sync_to_async(connections.close_all)()
    return response
