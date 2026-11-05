"""``live.middleware.SyncAndAsyncMiddleware``: the one place a middleware of ``live`` says it serves both chains.

Django runs a middleware in the chain's own mode: a sync one in an async chain costs a thread switch per request, so
each middleware of ``live`` serves both. The base keeps the detection and the mark; a subclass writes ``sync`` and
``asynchronous`` only (saas#284: the second copy of that boilerplate, in ``live.database_cut``).
"""

import pytest
from asgiref.sync import iscoroutinefunction
from django.http import HttpResponse
from django.test import RequestFactory

from live.middleware import SyncAndAsyncMiddleware


class Tagging(SyncAndAsyncMiddleware):
    def sync(self, request):
        response = self.get_response(request)
        response["X-Chain"] = "sync"
        return response

    async def asynchronous(self, request):
        response = await self.get_response(request)
        response["X-Chain"] = "async"
        return response


def test_a_sync_chain_runs_the_sync_side():
    middleware = Tagging(lambda request: HttpResponse("ok"))

    assert not iscoroutinefunction(middleware)
    assert middleware(RequestFactory().get("/"))["X-Chain"] == "sync"


async def test_an_async_chain_runs_the_async_side_without_a_thread_switch():
    async def get_response(request):
        return HttpResponse("ok")

    middleware = Tagging(get_response)

    assert iscoroutinefunction(middleware)
    assert (await middleware(RequestFactory().get("/")))["X-Chain"] == "async"


def test_the_base_declares_both_capabilities():
    assert (SyncAndAsyncMiddleware.sync_capable, SyncAndAsyncMiddleware.async_capable) == (True, True)


def test_a_subclass_has_to_write_both_sides():
    middleware = SyncAndAsyncMiddleware(lambda request: HttpResponse("ok"))

    with pytest.raises(NotImplementedError):
        middleware(RequestFactory().get("/"))
