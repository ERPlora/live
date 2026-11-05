"""A middleware of ``live`` serves the sync and the async chain alike.

Django runs a middleware in the chain's own mode: a sync-only one in an async chain costs a thread switch per request.
Every middleware of ``live`` says it serves both, and this base keeps the detection and the mark in one place: a
subclass writes :meth:`sync` and :meth:`asynchronous` only (``live.api_errors``, ``live.database_cut``).
"""

from typing import Any

from asgiref.sync import iscoroutinefunction, markcoroutinefunction
from django.http import HttpRequest
from django.http.response import HttpResponseBase


class SyncAndAsyncMiddleware:
    sync_capable = True
    async_capable = True

    def __init__(self, get_response: Any) -> None:
        self.get_response = get_response
        self.is_async = iscoroutinefunction(get_response)
        if self.is_async:
            markcoroutinefunction(self)

    def __call__(self, request: HttpRequest) -> Any:
        return self.asynchronous(request) if self.is_async else self.sync(request)

    def sync(self, request: HttpRequest) -> HttpResponseBase:
        raise NotImplementedError(f"{type(self).__name__} serves no sync chain.")

    async def asynchronous(self, request: HttpRequest) -> HttpResponseBase:
        raise NotImplementedError(f"{type(self).__name__} serves no async chain.")
