"""One error envelope for the 404 and 405 that never reach a route of the API.

``install_error_handlers`` covers failures inside a route. A path that resolves to nothing falls
to Django's HTML 404 and a known path called with the wrong method gets ninja's plain-text 405:
``ApiErrorEnvelopeMiddleware`` turns both into ``{"error": {"code", "message"}}`` under the API
prefix, and leaves everything else (JSON, streams, the live stream, the docs) untouched.
"""

import json

import pytest
from asgiref.sync import iscoroutinefunction
from django.http import (
    HttpResponse,
    HttpResponseNotFound,
    JsonResponse,
    StreamingHttpResponse,
)
from django.test import RequestFactory
from django.urls import path
from django.utils import translation
from live.api_errors import ApiErrorEnvelopeMiddleware
from live.errors import NotFound
from live.ninja import install_error_handlers
from ninja import NinjaAPI, Router

from tests.testapp import api as testapp_api

CONTEXT_BUILDER = "tests.testapp.context.TestContextBuilder"
MIDDLEWARE = "live.api_errors.ApiErrorEnvelopeMiddleware"
NOT_FOUND = {"error": {"code": "not_found", "message": "Not found"}}
METHOD_NOT_ALLOWED = {
    "error": {"code": "method_not_allowed", "message": "Method not allowed"}
}

probe = Router()


@probe.get("/gone")
def gone(request):
    raise NotFound("Gone for good.")


api = NinjaAPI(urls_namespace="live-test-api-errors")
install_error_handlers(api)
api.add_router("", testapp_api.router)
api.add_router("/probe", probe)

urlpatterns = [path("api/", api.urls)]


@pytest.fixture(autouse=True)
def api_settings(settings):
    settings.ROOT_URLCONF = __name__
    settings.MIDDLEWARE = [*settings.MIDDLEWARE, MIDDLEWARE]
    settings.LIVE = {**settings.LIVE, "context_builder": CONTEXT_BUILDER}


def through_middleware(path, response, *, method="get"):
    """Run ``ApiErrorEnvelopeMiddleware`` (sync) on a request to ``path`` whose view answers ``response``."""
    request = getattr(RequestFactory(), method)(path)
    return ApiErrorEnvelopeMiddleware(lambda request: response)(request)


def allowed(response) -> set[str]:
    return {method.strip() for method in response["Allow"].split(",")}


# --- Converted: the 404 and 405 that never reach a route ----------------------------------------


def test_unknown_api_path_is_a_json_not_found_envelope(client):
    response = client.get("/api/nope")

    assert response.status_code == 404
    assert response["Content-Type"] == "application/json"
    assert response.json() == NOT_FOUND


def test_wrong_method_on_a_bound_route_is_a_json_405_envelope_that_keeps_allow(client):
    response = client.delete("/api/things")

    assert response.status_code == 405
    assert response["Content-Type"] == "application/json"
    assert response.json() == METHOD_NOT_ALLOWED
    assert allowed(response) == {"GET", "POST"}


def test_the_converted_response_keeps_its_other_headers():
    original = HttpResponseNotFound("<h1>Not Found</h1>")
    original["X-Frame-Options"] = "DENY"
    original["Content-Length"] = str(len(original.content))

    response = through_middleware("/api/nope", original)

    assert response["X-Frame-Options"] == "DENY"
    assert json.loads(response.content) == NOT_FOUND
    assert response["Content-Length"] == str(len(response.content))


async def test_async_middleware_converts_too():
    async def get_response(request):
        return HttpResponseNotFound("<h1>Not Found</h1>")

    middleware = ApiErrorEnvelopeMiddleware(get_response)

    assert iscoroutinefunction(middleware)
    response = await middleware(RequestFactory().get("/api/nope"))
    assert (response.status_code, json.loads(response.content)) == (404, NOT_FOUND)


async def test_the_asgi_stack_answers_the_envelope(async_client):
    not_found = await async_client.get("/api/nope")
    not_allowed = await async_client.delete("/api/things")

    assert (not_found.status_code, not_found.json()) == (404, NOT_FOUND)
    assert (not_allowed.status_code, not_allowed.json()) == (405, METHOD_NOT_ALLOWED)
    assert allowed(not_allowed) == {"GET", "POST"}


def test_the_api_prefix_comes_from_settings(client, settings):
    settings.LIVE = {**settings.LIVE, "api_prefix": "/v1"}

    assert client.get("/v1/nope").json() == NOT_FOUND
    assert not client.get("/api/nope")["Content-Type"].startswith("application/json")
    assert not client.get("/v1nope")["Content-Type"].startswith("application/json")


def test_the_envelope_speaks_the_request_language(client, settings):
    # As in the projects: the locale middleware runs before (outside) the envelope.
    settings.MIDDLEWARE = [
        *settings.MIDDLEWARE[:-1],
        "django.middleware.locale.LocaleMiddleware",
        MIDDLEWARE,
    ]

    with translation.override("en"):
        not_found = client.get("/api/nope", headers={"Accept-Language": "es"})
        not_allowed = client.delete("/api/things", headers={"Accept-Language": "es"})

    assert not_found.json() == {
        "error": {"code": "not_found", "message": "No encontrado."}
    }
    assert not_allowed.json() == {
        "error": {"code": "method_not_allowed", "message": "Método no permitido."}
    }


# --- Untouched ----------------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_json_success_is_untouched(client):
    response = client.get("/api/things", headers={"X-Test-Permissions": "testapp.view"})

    assert response.status_code == 200
    assert response.json() == {"rows": []}


def test_a_json_not_found_from_an_operation_keeps_its_message(client):
    response = client.get("/api/probe/gone")

    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "not_found", "message": "Gone for good."}
    }


@pytest.mark.parametrize(
    "content_type",
    ["application/json", "application/json; charset=utf-8", "application/problem+json"],
)
def test_json_error_responses_pass_through(content_type):
    original = HttpResponse(b'{"detail":"mine"}', status=404, content_type=content_type)

    response = through_middleware("/api/nope", original)

    assert response is original
    assert response.content == b'{"detail":"mine"}'


def test_streaming_responses_are_returned_as_is_without_reading_them():
    consumed = []

    def body():
        consumed.append(True)
        yield b"event: bye\n\n"

    original = StreamingHttpResponse(
        body(), status=404, content_type="text/event-stream"
    )

    response = through_middleware("/api/things/stream", original)

    assert response is original
    assert consumed == []


@pytest.mark.parametrize("path", ["/api/live", "/api/docs", "/api/docs/swagger.js"])
def test_the_live_stream_and_the_docs_are_untouched(path):
    original = HttpResponseNotFound("nope", content_type="text/plain")

    response = through_middleware(path, original)

    assert response is original
    assert response.content == b"nope"


def test_other_statuses_are_untouched():
    original = HttpResponse("teapot", status=418, content_type="text/plain")

    assert through_middleware("/api/brew", original) is original
    assert (
        through_middleware("/api/things", JsonResponse({"rows": []})).content
        == b'{"rows": []}'
    )


def test_a_404_outside_the_api_is_untouched(client):
    response = client.get("/nope")

    assert response.status_code == 404
    assert response["Content-Type"].startswith("text/html")
