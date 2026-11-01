"""Ninja binding: a route calls the same operation, one error envelope, route-operation parity.

This module is also the URLconf of its own tests (``ROOT_URLCONF = __name__``): the API mounted
at ``/api/`` carries the testapp router plus a ``probe`` router whose routes only exist to
exercise the error handlers.
"""

import logging
from collections import defaultdict
from datetime import date, datetime, time
from decimal import Decimal
from types import SimpleNamespace
from typing import Generic, Literal, TypeVar
from uuid import UUID

import pytest
from django.http import Http404
from django.test import RequestFactory
from django.urls import path
from django.utils import translation
from live.context import OperationContext, Scope
from live.errors import Conflict, LiveMisuse, OperationError
from live.ninja import (
    bind,
    ensure_api_parity,
    install_error_handlers,
    mount_app_routers,
    operation_ids,
    run_operation,
    run_operation_sync,
)
from live.operations import Operation, UnknownOperation, operation, registry
from ninja import Field, NinjaAPI, Query, Router, Schema
from ninja.errors import HttpError
from pydantic import HttpUrl, field_validator
from pydantic_core import PydanticCustomError

from tests.testapp import api as testapp_api
from tests.testapp.models import Thing
from tests.testapp.queries import list_things
from tests.testapp.schemas import ThingIn, ThingListIn, ThingListOut, ThingOut
from tests.testapp.services import create_thing

pytestmark = pytest.mark.django_db

CONTEXT_BUILDER = "tests.testapp.context.TestContextBuilder"
VIEW = "testapp.view"
MANAGE = "testapp.manage"

probe = Router()


@probe.get("/conflict")
def raise_conflict(request):
    raise Conflict("Already done.", code="demo.x")


@probe.get("/missing")
def raise_http404(request):
    raise Http404("No Thing matches the given query.")


@probe.get("/http-error/{status}")
def raise_http_error(request, status: int):
    raise HttpError(status, "Ninja says no.")


@probe.get("/boom")
def raise_unexpected(request):
    raise RuntimeError("kaboom: secret detail")


class StrictIn(Schema):
    name: str = Field(min_length=1, max_length=3)
    qty: int = Field(1, ge=1, le=10)
    size: Literal["s", "m"] = "s"
    code: str = "ok"
    site: HttpUrl | None = None
    low: int = Field(0, gt=-1, lt=100)
    step: int = Field(0, multiple_of=5)
    ratio: float = 0
    price: Decimal = Field(Decimal("0"), max_digits=4, decimal_places=2)
    flag: bool = False
    label: str = Field("", pattern=r"^[a-z]*$")
    tags: list[str] = Field(default_factory=list, min_length=0, max_length=2)
    ref: UUID | None = None
    day: date | None = None
    when: datetime | None = None
    at: time | None = None
    cap: int = 0

    @field_validator("code")
    @classmethod
    def code_is_known(cls, value: str) -> str:
        if value != "ok":
            raise ValueError("Unknown code.")
        return value

    @field_validator("cap")
    @classmethod
    def cap_is_zero(cls, value: int) -> int:
        if value:
            # A known pydantic type without the ctx its message needs.
            raise PydanticCustomError("greater_than", "Keep it at zero.")
        return value


@probe.post("/strict")
def validate_strictly(request, data: StrictIn):
    return {"ok": True}


api = NinjaAPI(urls_namespace="live-test-ninja")
install_error_handlers(api)
api.add_router("", testapp_api.router)
api.add_router("/probe", probe)

urlpatterns = [path("api/", api.urls)]


@pytest.fixture(autouse=True)
def ninja_settings(settings):
    settings.ROOT_URLCONF = __name__
    settings.LIVE = {
        **getattr(settings, "LIVE", {}),
        "context_builder": CONTEXT_BUILDER,
    }


class NoInput(Schema):
    pass


T = TypeVar("T")


class Page(Schema, Generic[T]):
    rows: list[T]


@pytest.fixture
def isolated_registry():
    saved = dict(registry)
    yield registry
    registry.clear()
    registry.update(saved)


def declare_query(name, *, input, output):
    """Register an ad-hoc query that pretends to live in the testapp's queries.py."""

    def fn(ctx, data):
        return {"rows": []}

    fn.__module__ = "tests.testapp.queries"
    return operation(name, kind="query", permission=None, input=input, output=output)(
        fn
    )


def as_user(*permissions):
    return {"X-Test-Permissions": ",".join(permissions)}


def api_with(*routers):
    """An API that is not mounted anywhere, so its route paths start at ``/``."""
    unmounted = NinjaAPI(urls_namespace="live-test-parity")
    for prefix, router in routers:
        unmounted.add_router(prefix, router)
    return unmounted


# --- run_operation: the route and the operation share the same function --------------------


def test_route_and_operation_share_the_same_function(client, monkeypatch):
    operation = registry["testapp.thing.list"]
    assert operation is list_things
    original = operation.fn
    calls = []

    def spy(ctx, params):
        calls.append((ctx, params))
        return original(ctx, params)

    monkeypatch.setattr(operation, "fn", spy)
    thing = Thing.objects.create(name="first")

    response = client.get("/api/things", {"limit": 5}, headers=as_user(VIEW))

    assert response.status_code == 200
    assert response.json() == {"rows": [{"id": thing.id, "name": "first"}]}
    assert len(calls) == 1
    ctx, params = calls[0]
    assert isinstance(ctx, OperationContext)
    assert ctx.scope == Scope("host", "testserver")
    assert ctx.permissions == frozenset({VIEW})
    assert params == ThingListIn(limit=5)


def test_command_route_returns_201_with_the_operation_output(client):
    response = client.post(
        "/api/things",
        {"name": "new"},
        content_type="application/json",
        headers=as_user(MANAGE),
    )

    assert response.status_code == 201
    thing = Thing.objects.get()
    assert response.json() == {"id": thing.id, "name": "new"}


def test_run_operation_sync_accepts_the_operation_or_its_name_and_defaults_the_input():
    Thing.objects.create(name="a")
    request = RequestFactory().get("/", headers=as_user(VIEW))

    by_name = run_operation_sync(request, "testapp.thing.list", ThingListIn(limit=1))
    by_object = run_operation_sync(request, list_things)

    assert isinstance(by_name, ThingListOut)
    assert [row.name for row in by_name.rows] == ["a"]
    assert by_object == by_name


def test_run_operation_sync_rejects_an_unknown_operation():
    request = RequestFactory().get("/", headers=as_user(VIEW))

    with pytest.raises(UnknownOperation):
        run_operation_sync(request, "testapp.thing.nope")


def test_run_operation_sync_rejects_an_input_of_another_schema():
    request = RequestFactory().post("/", headers=as_user(MANAGE))

    with pytest.raises(LiveMisuse, match="ThingIn"):
        run_operation_sync(request, create_thing, ThingListIn())
    assert not Thing.objects.exists()


async def test_run_operation_is_awaitable_from_an_async_route(monkeypatch):
    # The call itself is stubbed: in an async test the executor's thread would open its own
    # connection, outside the test transaction. The routes above cover the database path.
    calls = []

    def call(self, ctx, data):
        calls.append((self, ctx, data))
        return ThingListOut(rows=[])

    monkeypatch.setattr(Operation, "__call__", call)
    request = RequestFactory().get("/", headers=as_user(VIEW))

    result = await run_operation(request, "testapp.thing.list")

    assert result == ThingListOut(rows=[])
    [(operation, ctx, data)] = calls
    assert operation is list_things
    assert isinstance(ctx, OperationContext)
    assert ctx.permissions == frozenset({VIEW})
    assert data == ThingListIn()


# --- The single error envelope ----------------------------------------------------------------


def test_invalid_payload_is_422_with_fields_per_field(client):
    response = client.post(
        "/api/things", {}, content_type="application/json", headers=as_user(MANAGE)
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "invalid_payload"
    assert error["message"] == "Invalid payload"
    assert set(error["fields"]) == {"name"}
    assert error["fields"]["name"]
    assert not Thing.objects.exists()


def test_invalid_query_is_422_with_the_field_name(client):
    response = client.get("/api/things", {"limit": 500}, headers=as_user(VIEW))

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "invalid_payload"
    assert set(error["fields"]) == {"limit"}


def test_missing_body_is_422_with_a_non_field_error(client):
    # The test client sends "{}" for a missing JSON body; generic() sends nothing at all.
    response = client.generic(
        "POST",
        "/api/things",
        b"",
        content_type="application/json",
        headers=as_user(MANAGE),
    )

    assert response.status_code == 422
    assert set(response.json()["error"]["fields"]) == {"__all__"}


def test_operation_error_uses_the_single_envelope(client):
    response = client.get("/api/probe/conflict")

    assert response.status_code == 409
    assert response.json() == {"error": {"code": "demo.x", "message": "Already done."}}


def test_an_operation_error_a_route_answers_has_reached_its_client(client, monkeypatch):
    told = []
    monkeypatch.setattr(OperationError, "reached_client", lambda self: told.append(self.code))

    client.get("/api/probe/conflict")

    assert told == ["demo.x"]


def test_permission_denied_is_403_envelope(client):
    response = client.get("/api/things", headers=as_user("other.view"))

    assert response.status_code == 403
    assert response.json() == {
        "error": {
            "code": "permission_denied",
            "message": "Permission “testapp.view” is required.",
        }
    }


def test_permission_denied_speaks_the_request_language(client, settings):
    settings.MIDDLEWARE = [*settings.MIDDLEWARE, LOCALE_MIDDLEWARE]

    with translation.override("en"):
        spanish = client.get(
            "/api/things", headers={**as_user("other.view"), "Accept-Language": "es"}
        )
        english = client.get(
            "/api/things", headers={**as_user("other.view"), "Accept-Language": "en"}
        )

    assert spanish.status_code == english.status_code == 403
    assert spanish.json() == {
        "error": {
            "code": "permission_denied",
            "message": "Se necesita el permiso «testapp.view».",
        }
    }
    assert english.json()["error"]["message"] == "Permission “testapp.view” is required."


def test_permission_denied_follows_the_language_cookie(client, settings):
    settings.MIDDLEWARE = [*settings.MIDDLEWARE, LOCALE_MIDDLEWARE]
    client.cookies[settings.LANGUAGE_COOKIE_NAME] = "es"

    with translation.override("en"):
        response = client.get("/api/things", headers=as_user("other.view"))

    assert response.status_code == 403
    assert response.json()["error"]["message"] == "Se necesita el permiso «testapp.view»."


def test_http404_is_not_found_envelope(client):
    response = client.get("/api/probe/missing")

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found", "message": "Not found"}}


def test_operation_errors_speak_the_request_language(client, settings):
    settings.MIDDLEWARE = [
        *settings.MIDDLEWARE,
        "django.middleware.locale.LocaleMiddleware",
    ]

    # The request activates its language in this thread; override restores it afterwards.
    with translation.override("en"):
        spanish = client.get(
            "/api/things/999999", headers={**as_user(VIEW), "Accept-Language": "es"}
        )
        english = client.get(
            "/api/things/999999", headers={**as_user(VIEW), "Accept-Language": "en"}
        )

    assert spanish.status_code == 404
    assert spanish.json() == {
        "error": {"code": "not_found", "message": "Cosa no encontrada."}
    }
    assert english.json() == {
        "error": {"code": "not_found", "message": "Thing not found."}
    }


LOCALE_MIDDLEWARE = "django.middleware.locale.LocaleMiddleware"


@pytest.mark.parametrize(
    ("payload", "field", "english", "spanish"),
    [
        ({}, "name", "This field is required.", "Este campo es obligatorio."),
        (
            {"name": ""},
            "name",
            "Ensure this value has at least 1 character.",
            "Debe tener al menos 1 carácter.",
        ),
        (
            {"name": "abcd"},
            "name",
            "Ensure this value has at most 3 characters.",
            "Debe tener como máximo 3 caracteres.",
        ),
        (
            {"name": "a", "qty": 0},
            "qty",
            "Ensure this value is greater than or equal to 1.",
            "Debe ser mayor o igual que 1.",
        ),
        (
            {"name": "a", "qty": 11},
            "qty",
            "Ensure this value is less than or equal to 10.",
            "Debe ser menor o igual que 10.",
        ),
        (
            {"name": "a", "qty": "many"},
            "qty",
            "Enter a whole number.",
            "Introduce un número entero.",
        ),
        (
            {"name": "a", "size": "xl"},
            "size",
            "Select a valid choice.",
            "Selecciona una opción válida.",
        ),
    ],
)
def test_field_errors_speak_the_request_language(
    client, settings, payload, field, english, spanish
):
    settings.MIDDLEWARE = [*settings.MIDDLEWARE, LOCALE_MIDDLEWARE]

    with translation.override("en"):
        in_english = client.post(
            "/api/probe/strict",
            payload,
            content_type="application/json",
            headers={"Accept-Language": "en"},
        )
        in_spanish = client.post(
            "/api/probe/strict",
            payload,
            content_type="application/json",
            headers={"Accept-Language": "es"},
        )

    assert in_english.status_code == in_spanish.status_code == 422
    assert in_english.json() == {
        "error": {
            "code": "invalid_payload",
            "message": "Invalid payload",
            "fields": {field: english},
        }
    }
    assert in_spanish.json() == {
        "error": {
            "code": "invalid_payload",
            "message": "Los datos enviados no son válidos.",
            "fields": {field: spanish},
        }
    }


def test_invalid_payload_follows_the_language_cookie(client, settings):
    settings.MIDDLEWARE = [*settings.MIDDLEWARE, LOCALE_MIDDLEWARE]
    client.cookies[settings.LANGUAGE_COOKIE_NAME] = "es"

    with translation.override("en"):
        response = client.post(
            "/api/probe/strict", {"name": ""}, content_type="application/json"
        )

    assert response.status_code == 422
    assert response.json()["error"]["message"] == "Los datos enviados no son válidos."
    assert response.json()["error"]["fields"] == {
        "name": "Debe tener al menos 1 carácter."
    }


def test_a_validator_message_reaches_the_client_without_pydantic_prefix(client):
    response = client.post(
        "/api/probe/strict",
        {"name": "a", "code": "nope"},
        content_type="application/json",
    )

    assert response.status_code == 422
    assert response.json()["error"]["fields"] == {"code": "Unknown code."}


def test_an_unmapped_error_keeps_the_pydantic_message(client):
    response = client.post(
        "/api/probe/strict",
        {"name": "a", "site": "not a url"},
        content_type="application/json",
    )

    assert response.status_code == 422
    assert response.json()["error"]["fields"]["site"].startswith(
        "Input should be a valid URL"
    )


def test_a_mapped_type_without_its_ctx_keeps_its_own_message(client, caplog):
    with caplog.at_level(logging.WARNING, logger="live.ninja"):
        response = client.post(
            "/api/probe/strict",
            {"name": "a", "cap": 1},
            content_type="application/json",
        )

    assert response.status_code == 422
    assert response.json()["error"]["fields"] == {"cap": "Keep it at zero."}
    assert "greater_than" in caplog.text


@pytest.mark.parametrize(
    ("extra", "field", "message"),
    [
        ({"low": -1}, "low", "Ensure this value is greater than -1."),
        ({"low": 100}, "low", "Ensure this value is less than 100."),
        ({"step": 7}, "step", "Ensure this value is a multiple of 5."),
        ({"ratio": "half"}, "ratio", "Enter a number."),
        ({"price": "abc"}, "price", "Enter a number."),
        (
            {"price": "123.45"},
            "price",
            "Ensure that there are no more than 4 digits in total.",
        ),
        (
            {"price": "1.234"},
            "price",
            "Ensure that there are no more than 2 decimal places.",
        ),
        (
            {"price": "123.4"},
            "price",
            "Ensure that there are no more than 2 digits before the decimal point.",
        ),
        ({"flag": "perhaps"}, "flag", "Enter a valid boolean."),
        ({"name": 5}, "name", "Enter a valid text."),
        ({"label": "A"}, "label", "Enter a valid value."),
        ({"tags": ["a", "b", "c"]}, "tags", "Ensure this value has at most 2 items."),
        ({"tags": "a"}, "tags", "Enter a valid value."),
        ({"ref": "nope"}, "ref", "Enter a valid UUID."),
        ({"day": "nope"}, "day", "Enter a valid date."),
        ({"when": "nope"}, "when", "Enter a valid date/time."),
        ({"at": "nope"}, "at", "Enter a valid time."),
    ],
)
def test_each_kind_of_field_error_has_its_message(client, extra, field, message):
    payload = {"name": "a", **extra}

    response = client.post(
        "/api/probe/strict", payload, content_type="application/json"
    )

    assert response.status_code == 422
    assert response.json()["error"]["fields"] == {field: message}


def test_every_field_message_has_its_spanish_translation():
    from live.ninja import FIELD_MESSAGES

    ctx = defaultdict(lambda: 2)
    for kind, message in FIELD_MESSAGES.items():
        with translation.override("en"):
            english = str(message % ctx)
        with translation.override("es"):
            spanish = str(message % ctx)
        assert spanish != english, kind


def test_generic_envelope_messages_speak_the_request_language(client, settings):
    settings.MIDDLEWARE = [*settings.MIDDLEWARE, LOCALE_MIDDLEWARE]

    with translation.override("en"):
        missing = client.get("/api/probe/missing", headers={"Accept-Language": "es"})
        boom = client.get("/api/probe/boom", headers={"Accept-Language": "es"})

    assert missing.json() == {
        "error": {"code": "not_found", "message": "No encontrado."}
    }
    assert boom.json() == {
        "error": {"code": "internal_error", "message": "Error interno."}
    }


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "unauthorized"),
        (403, "permission_denied"),
        (404, "not_found"),
        (405, "method_not_allowed"),
        (418, "error"),
    ],
)
def test_ninja_http_error_takes_its_code_from_the_status(client, status, code):
    response = client.get(f"/api/probe/http-error/{status}")

    assert response.status_code == status
    assert response.json() == {"error": {"code": code, "message": "Ninja says no."}}


def test_unexpected_exception_is_500_internal_error_when_not_debug(client, caplog):
    with caplog.at_level(logging.ERROR, logger="live.ninja"):
        response = client.get("/api/probe/boom")

    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "internal_error", "message": "Internal error"}
    }
    assert b"secret detail" not in response.content
    [record] = [r for r in caplog.records if r.name == "live.ninja"]
    assert record.exc_info[0] is RuntimeError


def test_unexpected_exception_is_reraised_in_debug_so_the_debug_page_shows(
    client, settings
):
    settings.DEBUG = True

    with pytest.raises(RuntimeError, match="kaboom"):
        client.get("/api/probe/boom")


# --- Parity: every route bound to one operation, same method kind and schemas -----------------


def test_parity_ok_for_testapp():
    assert ensure_api_parity(api_with(("", testapp_api.router))) == []


def test_parity_detects_route_without_operation():
    problems = ensure_api_parity(
        api_with(("", testapp_api.router), ("", testapp_api.unbound_router))
    )

    assert problems == ["route GET /unbound has no operation"]


def test_parity_uses_the_mounted_path_and_skips_allowed_routes():
    mounted = ensure_api_parity(api)

    assert "route GET /api/probe/boom has no operation" in mounted
    assert not any("/api/things" in problem for problem in mounted)
    allowed = [
        f"/api/probe/{name}"
        for name in ("conflict", "missing", "http-error/{status}", "boom", "strict")
    ]
    assert ensure_api_parity(api, allow=allowed) == []


def test_parity_detects_unknown_operation():
    router = Router()

    @router.get("/nope", response=ThingListOut, operation_id="testapp.thing.nope")
    def nope(request, params: Query[ThingListIn]):
        raise AssertionError("never called")

    assert ensure_api_parity(api_with(("", router))) == [
        "route GET /nope: unknown operation 'testapp.thing.nope'"
    ]


def test_parity_detects_response_schema_mismatch():
    router = Router()

    @router.get("/things", response=ThingOut, operation_id="testapp.thing.list")
    def wrong_response(request, params: Query[ThingListIn]):
        raise AssertionError("never called")

    @router.post("/things", operation_id="testapp.thing.create")
    def no_response(request, data: ThingIn):
        raise AssertionError("never called")

    assert ensure_api_parity(api_with(("", router))) == [
        "route GET /things: responds with ThingOut, operation testapp.thing.list returns ThingListOut",
        "route POST /things: declares no response schema, operation testapp.thing.create returns ThingOut",
    ]


def test_parity_detects_method_kind_mismatch():
    router = Router()

    @router.post("/list", response=ThingListOut, operation_id="testapp.thing.list")
    def query_by_post(request, params: ThingListIn):
        raise AssertionError("never called")

    @router.get("/create", response=ThingOut, operation_id="testapp.thing.create")
    def command_by_get(request, data: Query[ThingIn]):
        raise AssertionError("never called")

    assert ensure_api_parity(api_with(("", router))) == [
        "route POST /list: testapp.thing.list is a query, served only by GET",
        "route GET /create: testapp.thing.create is a command, never served by GET",
    ]


def test_parity_detects_input_schema_mismatch():
    router = Router()

    @router.get("/wrong", response=ThingListOut, operation_id="testapp.thing.list")
    def wrong_input(request, params: Query[ThingIn]):
        raise AssertionError("never called")

    @router.post(
        "/extra", response={201: ThingOut}, operation_id="testapp.thing.create"
    )
    def extra_param(request, data: ThingIn, verbose: bool = False):
        raise AssertionError("never called")

    @router.get(
        "/body",
        response=ThingListOut,
        operation_id="testapp.thing.list",
        url_name="body",
    )
    def query_from_body(request, params: ThingListIn):
        raise AssertionError("never called")

    assert ensure_api_parity(api_with(("", router))) == [
        "route GET /wrong: takes params: ThingIn, operation testapp.thing.list takes ThingListIn",
        "route POST /extra: parameter 'verbose' is not part of the input of testapp.thing.create",
        "route GET /body: a GET takes its input from the query or the path, not the body",
        "operation testapp.thing.list is bound to more than one route: GET /wrong, GET /body",
    ]


def test_parity_accepts_a_route_without_parameters_when_the_input_has_no_fields(
    isolated_registry,
):
    nothing = declare_query("testapp.thing.nothing", input=NoInput, output=ThingListOut)
    router = Router()

    @router.get("/empty", response=ThingListOut, operation_id=nothing.name)
    def no_input(request):
        raise AssertionError("never called")

    assert ensure_api_parity(api_with(("", router))) == []


def test_parity_accepts_a_generic_page_output(isolated_registry):
    page = declare_query("testapp.thing.page", input=ThingListIn, output=Page[ThingOut])
    router = Router()

    @router.get("/page", response=Page[ThingOut], operation_id=page.name)
    def paged(request, params: Query[ThingListIn]):
        raise AssertionError("never called")

    @router.get(
        "/other-page", response=Page[ThingIn], operation_id=page.name, url_name="other"
    )
    def other_page(request, params: Query[ThingListIn]):
        raise AssertionError("never called")

    assert ensure_api_parity(api_with(("", router))) == [
        "route GET /other-page: responds with Page[ThingIn], operation testapp.thing.page returns Page[ThingOut]",
        "operation testapp.thing.page is bound to more than one route: GET /page, GET /other-page",
    ]


def test_bind_takes_method_response_and_operation_id_from_the_operation():
    router = Router()

    @bind(router, "testapp.thing.list", "/things")
    def bound_list(request, params: Query[ThingListIn]):
        raise AssertionError("never called")

    @bind(router, "testapp.thing.create", "/things", status=201)
    def bound_create(request, data: ThingIn):
        raise AssertionError("never called")

    bound = api_with(("", router))
    schema = bound.get_openapi_schema(path_prefix="")
    assert schema["paths"]["/things"]["get"]["operationId"] == "testapp.thing.list"
    assert schema["paths"]["/things"]["post"]["operationId"] == "testapp.thing.create"
    assert set(schema["paths"]["/things"]["post"]["responses"]) == {201}
    assert ensure_api_parity(bound) == []


def test_bind_rejects_an_unknown_operation():
    with pytest.raises(UnknownOperation):
        bind(Router(), "testapp.thing.nope", "/nope")


# --- OpenAPI ------------------------------------------------------------------------------------


def test_operation_id_equals_operation_name_in_openapi():
    schema = api.get_openapi_schema()

    operation_id_by_route = {
        (method, route): details["operationId"]
        for route, methods in schema["paths"].items()
        for method, details in methods.items()
    }
    assert operation_id_by_route[("get", "/api/things")] == "testapp.thing.list"
    assert operation_id_by_route[("post", "/api/things")] == "testapp.thing.create"
    assert operation_id_by_route[("get", "/api/things/{id}")] == "testapp.thing.get"
    assert operation_ids(api) == {
        "testapp.thing.list",
        "testapp.thing.get",
        "testapp.thing.create",
    }


def test_openapi_served_at_api_openapi_json(client):
    response = client.get("/api/openapi.json")

    assert response.status_code == 200
    assert (
        response.json()["paths"]["/api/things"]["get"]["operationId"]
        == "testapp.thing.list"
    )
    assert api.docs_url == "/docs"
    assert client.get("/api/docs").status_code == 200


# --- Mounting the routers of the apps -----------------------------------------------------------


def stand_in(name):
    """Stands in for an installed LiveAppConfig: only what mount_app_routers reads."""
    return SimpleNamespace(name=name, label=name.rsplit(".", 1)[-1])


def test_mount_app_routers_mounts_the_router_of_each_app_with_an_api_module(
    monkeypatch,
):
    # ``tests`` has no api.py: an app without one is skipped.
    monkeypatch.setattr(
        "live.ninja.all_live_app_configs",
        lambda: [stand_in("tests.fakeapp"), stand_in("tests")],
    )
    mounted = NinjaAPI(urls_namespace="live-test-mount")

    assert mount_app_routers(mounted) == ["fakeapp"]
    # The stand-in route is mounted at the API's root, and parity catches that it has no operation.
    assert ensure_api_parity(mounted) == ["route GET /fake has no operation"]


def test_mount_app_routers_refuses_an_api_module_without_router(monkeypatch):
    monkeypatch.setattr(
        "live.ninja.all_live_app_configs", lambda: [stand_in("tests.norouter")]
    )

    with pytest.raises(LiveMisuse, match="tests.norouter.api"):
        mount_app_routers(NinjaAPI(urls_namespace="live-test-norouter"))


def test_mount_app_routers_mounts_the_installed_apps():
    mounted = NinjaAPI(urls_namespace="live-test-mount-installed")

    assert mount_app_routers(mounted) == ["testapp"]
    assert {
        "testapp.thing.list",
        "testapp.thing.get",
        "testapp.thing.create",
    } <= operation_ids(mounted)
