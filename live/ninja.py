"""Ninja binding: every route of an app's ``api.py`` calls exactly one operation.

``run_operation`` builds the context from the request (never from the payload) and calls the same
``Operation`` that the live stream, the assistant and the API keys call. ``install_error_handlers``
turns every failure of the API into the single envelope ``{"error": {"code", "message",
"fields"?}}``. ``ensure_api_parity`` is the guardrail that keeps routes explicit yet honest: each
route carries ``operation_id`` = the name of a registered operation, a query is served by GET and
a command never is, the success response is the operation's output and its only parameter is the
operation's input.
"""

import logging
import re
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator
from functools import partial
from importlib import import_module
from importlib.util import find_spec
from typing import Any

from asgiref.sync import sync_to_async
from django.conf import settings
from django.http import Http404
from django.urls import NoReverseMatch
from django.utils.translation import gettext, ngettext_lazy
from django.utils.translation import gettext_lazy as _
from ninja import NinjaAPI, Router, Schema
from ninja.constants import NOT_SET
from ninja.errors import HttpError, ValidationError, ValidationErrorContext
from ninja.operation import Operation as Route
from ninja.utils import normalize_path

from live.context import get_builder
from live.errors import InvalidPayload, LiveMisuse, NotFound, OperationError
from live.meta import all_live_app_configs
from live.operations import Operation, get, registry

logger = logging.getLogger(__name__)

# Routes of the API that are not operations: the schema, its docs and the live stream.
DEFAULT_ALLOW = ("/api/openapi.json", "/api/docs", "/api/live")
# Key of ``fields`` for an error that belongs to the whole payload, as in Django forms.
NON_FIELD_ERRORS = "__all__"
HTTP_ERROR_CODES = {
    401: "unauthorized",
    403: "permission_denied",
    404: "not_found",
    405: "method_not_allowed",
}
# Where a route may take the operation's input from: a GET has no body.
_INPUT_SOURCES = {True: ("query", "path"), False: ("body", "path")}

_ENTER_A_VALID_VALUE = _("Enter a valid value.")
_ENTER_A_NUMBER = _("Enter a number.")
_ENTER_A_WHOLE_NUMBER = _("Enter a whole number.")
_SELECT_A_VALID_CHOICE = _("Select a valid choice.")
_ENTER_A_VALID_BOOLEAN = _("Enter a valid boolean.")
_ENTER_A_VALID_UUID = _("Enter a valid UUID.")
_ENTER_A_VALID_DATE = _("Enter a valid date.")
_ENTER_A_VALID_DATETIME = _("Enter a valid date/time.")
_ENTER_A_VALID_TIME = _("Enter a valid time.")
# The 422 message of each pydantic error type, in the request's language, with the error's ``ctx``
# interpolated. A type not listed keeps pydantic's (English) message.
FIELD_MESSAGES = {
    "missing": _("This field is required."),
    "extra_forbidden": _("This field is not allowed."),
    "string_type": _("Enter a valid text."),
    "string_too_short": ngettext_lazy(
        "Ensure this value has at least %(min_length)d character.",
        "Ensure this value has at least %(min_length)d characters.",
        "min_length",
    ),
    "string_too_long": ngettext_lazy(
        "Ensure this value has at most %(max_length)d character.",
        "Ensure this value has at most %(max_length)d characters.",
        "max_length",
    ),
    "string_pattern_mismatch": _ENTER_A_VALID_VALUE,
    "too_short": ngettext_lazy(
        "Ensure this value has at least %(min_length)d item.",
        "Ensure this value has at least %(min_length)d items.",
        "min_length",
    ),
    "too_long": ngettext_lazy(
        "Ensure this value has at most %(max_length)d item.",
        "Ensure this value has at most %(max_length)d items.",
        "max_length",
    ),
    "greater_than": _("Ensure this value is greater than %(gt)s."),
    "greater_than_equal": _("Ensure this value is greater than or equal to %(ge)s."),
    "less_than": _("Ensure this value is less than %(lt)s."),
    "less_than_equal": _("Ensure this value is less than or equal to %(le)s."),
    "multiple_of": _("Ensure this value is a multiple of %(multiple_of)s."),
    "int_type": _ENTER_A_WHOLE_NUMBER,
    "int_parsing": _ENTER_A_WHOLE_NUMBER,
    "int_from_float": _ENTER_A_WHOLE_NUMBER,
    "float_type": _ENTER_A_NUMBER,
    "float_parsing": _ENTER_A_NUMBER,
    "decimal_type": _ENTER_A_NUMBER,
    "decimal_parsing": _ENTER_A_NUMBER,
    "decimal_max_digits": ngettext_lazy(
        "Ensure that there are no more than %(max_digits)d digit in total.",
        "Ensure that there are no more than %(max_digits)d digits in total.",
        "max_digits",
    ),
    "decimal_max_places": ngettext_lazy(
        "Ensure that there are no more than %(decimal_places)d decimal place.",
        "Ensure that there are no more than %(decimal_places)d decimal places.",
        "decimal_places",
    ),
    "decimal_whole_digits": ngettext_lazy(
        "Ensure that there are no more than %(whole_digits)d digit before the decimal point.",
        "Ensure that there are no more than %(whole_digits)d digits before the decimal point.",
        "whole_digits",
    ),
    "bool_type": _ENTER_A_VALID_BOOLEAN,
    "bool_parsing": _ENTER_A_VALID_BOOLEAN,
    "literal_error": _SELECT_A_VALID_CHOICE,
    "enum": _SELECT_A_VALID_CHOICE,
    "uuid_type": _ENTER_A_VALID_UUID,
    "uuid_parsing": _ENTER_A_VALID_UUID,
    "date_type": _ENTER_A_VALID_DATE,
    "date_parsing": _ENTER_A_VALID_DATE,
    "date_from_datetime_parsing": _ENTER_A_VALID_DATE,
    "date_from_datetime_inexact": _ENTER_A_VALID_DATE,
    "datetime_type": _ENTER_A_VALID_DATETIME,
    "datetime_parsing": _ENTER_A_VALID_DATETIME,
    "datetime_from_date_parsing": _ENTER_A_VALID_DATETIME,
    "datetime_object_invalid": _ENTER_A_VALID_DATETIME,
    "time_type": _ENTER_A_VALID_TIME,
    "time_parsing": _ENTER_A_VALID_TIME,
    "json_invalid": _("Enter a valid JSON."),
    "list_type": _ENTER_A_VALID_VALUE,
    "dict_type": _ENTER_A_VALID_VALUE,
    "model_type": _ENTER_A_VALID_VALUE,
    "model_attributes_type": _ENTER_A_VALID_VALUE,
}
# Types whose message is the app's own: the exception a validator raised (``ctx["error"]``).
_VALIDATOR_ERRORS = frozenset({"value_error", "assertion_error"})


# --- Calling the operation ----------------------------------------------------------------------


async def run_operation(
    request: Any, op: Operation | str, data: Schema | None = None
) -> Schema:
    """Run ``op`` (or the operation named so) for the caller of ``request``, from an async route."""
    op, data = _prepare(op, data)
    ctx = await sync_to_async(get_builder().from_request)(request)
    return await sync_to_async(op)(ctx, data)


def run_operation_sync(
    request: Any, op: Operation | str, data: Schema | None = None
) -> Schema:
    """Same as ``run_operation``, for a sync route."""
    op, data = _prepare(op, data)
    return op(get_builder().from_request(request), data)


def _prepare(op: Operation | str, data: Schema | None) -> tuple[Operation, Schema]:
    if isinstance(op, str):
        op = get(op)
    if data is None:
        data = op.input()
    elif not isinstance(data, op.input):
        raise LiveMisuse(
            f"{op.name} takes a {op.input.__name__}, the route passed a {type(data).__name__}."
        )
    return op, data


def bind(
    router: Router,
    op_name: str,
    path: str,
    *,
    method: str | None = None,
    status: int = 200,
    **options: Any,
) -> Callable:
    """Route decorator whose method, response and ``operation_id`` come from the operation.

    A query is served by GET; a command by POST unless ``method`` says otherwise. The route body
    stays explicit: it still calls ``run_operation``.
    """
    op = get(op_name)
    method = (method or ("GET" if op.kind == "query" else "POST")).upper()
    return router.api_operation(
        [method], path, response={status: op.output}, operation_id=op.name, **options
    )


# --- Mounting the routers of the apps ----------------------------------------------------------


def mount_app_routers(api: NinjaAPI) -> list[str]:
    """Mount the ``router`` of every app's ``api.py`` at the API's root; returns their labels.

    Every app of ours (``all_live_app_configs``: platform apps and modules) is looked at, in
    ``INSTALLED_APPS`` order; one without ``api.py`` is skipped. An ``api.py`` without ``router``
    (a ninja ``Router``) is a misuse.
    """
    mounted = []
    for config in all_live_app_configs():
        module_name = f"{config.name}.api"
        if find_spec(module_name) is None:
            continue
        router = getattr(import_module(module_name), "router", None)
        if not isinstance(router, Router):
            raise LiveMisuse(f"{module_name} must define `router`, a ninja Router.")
        api.add_router("", router)
        mounted.append(config.label)
    return mounted


# --- The single error envelope ------------------------------------------------------------------


def install_error_handlers(api: NinjaAPI) -> None:
    """Answer every failure of ``api`` with the error envelope (in DEBUG, a crash still raises)."""

    def operation_error(request: Any, exc: OperationError) -> Any:
        exc.reached_client()
        return api.create_response(request, exc.envelope(), status=exc.status)

    def invalid_payload(request: Any, exc: ValidationError) -> Any:
        return operation_error(
            request,
            InvalidPayload(gettext("Invalid payload"), fields=_fields(exc.errors)),
        )

    def not_found(request: Any, exc: Http404) -> Any:
        return operation_error(request, NotFound(gettext("Not found")))

    def http_error(request: Any, exc: HttpError) -> Any:
        code = HTTP_ERROR_CODES.get(exc.status_code, "error")
        return operation_error(
            request, OperationError(exc.message, code=code, status=exc.status_code)
        )

    def unexpected(request: Any, exc: Exception) -> Any:
        if settings.DEBUG:
            raise exc
        logger.error(
            "Unhandled error in %s %s", request.method, request.path, exc_info=exc
        )
        return operation_error(
            request,
            OperationError(
                gettext("Internal error"), code="internal_error", status=500
            ),
        )

    api.add_exception_handler(OperationError, operation_error)
    api.add_exception_handler(ValidationError, invalid_payload)
    api.add_exception_handler(Http404, not_found)
    api.add_exception_handler(HttpError, http_error)
    api.add_exception_handler(Exception, unexpected)
    api.validation_error_from_error_contexts = partial(
        _without_body_parameter_name, api.validation_error_from_error_contexts
    )


def _without_body_parameter_name(
    build: Callable[[list[ValidationErrorContext]], ValidationError],
    error_contexts: list[ValidationErrorContext],
) -> ValidationError:
    """Drop the route's parameter name from body errors: ``("body", "data", "name")`` → ``("body", "name")``.

    Ninja reads a single body parameter as ``{<parameter>: <body>}``, so its errors carry a name
    the client never sent.
    """
    error = build(error_contexts)
    names = {
        getattr(context.model, "__read_from_single_attr__", None)
        for context in error_contexts
        if context.model.__ninja_param_source__ == "body"
    } - {None}
    for item in error.errors:
        loc = tuple(item["loc"])
        if len(loc) > 1 and loc[0] == "body" and loc[1] in names:
            item["loc"] = (loc[0], *loc[2:])
    return error


def _fields(errors: Iterable[dict]) -> dict[str, str]:
    """One message per field path, without the source (``body``, ``query``, ``path``…)."""
    fields: dict[str, str] = {}
    for error in errors:
        field = (
            ".".join(str(part) for part in tuple(error.get("loc", ()))[1:])
            or NON_FIELD_ERRORS
        )
        if field not in fields:
            fields[field] = _field_message(error)
    return fields


def _field_message(error: dict) -> str:
    """The message of one pydantic ``error`` in the request's language (``FIELD_MESSAGES``)."""
    kind = error.get("type")
    ctx = error.get("ctx") or {}
    if kind in _VALIDATOR_ERRORS:
        return str(ctx.get("error") or "") or str(_ENTER_A_VALID_VALUE)
    message = FIELD_MESSAGES.get(kind)
    if message is not None:
        try:
            return str(message % ctx)
        except (KeyError, TypeError, ValueError):
            # A custom error that reuses a pydantic type without its ctx: its own text below.
            logger.warning("No ctx to format the %r message: %r", kind, ctx)
    return error.get("msg") or str(_ENTER_A_VALID_VALUE)


# --- Parity: route ↔ operation ------------------------------------------------------------------


def ensure_api_parity(
    api: NinjaAPI, *, allow: Iterable[str] = DEFAULT_ALLOW
) -> list[str]:
    """Every problem binding the routes of ``api`` to operations; empty when they all match.

    ``allow`` lists full URL paths (as mounted, e.g. ``/api/live``) that are not operations.
    """
    allowed = set(allow)
    problems: list[str] = []
    routes_by_operation: dict[str, list[str]] = defaultdict(list)
    for path, route in _routes(api):
        if path in allowed:
            continue
        label = f"{'/'.join(route.methods)} {path}"
        if not route.operation_id:
            problems.append(f"route {label} has no operation")
            continue
        op = registry.get(route.operation_id)
        if op is None:
            problems.append(f"route {label}: unknown operation {route.operation_id!r}")
            continue
        routes_by_operation[op.name].append(label)
        problems += _method_problems(label, route, op)
        problems += _response_problems(label, route, op)
        problems += _input_problems(label, route, op)
    for name, labels in routes_by_operation.items():
        if len(labels) > 1:
            problems.append(
                f"operation {name} is bound to more than one route: {', '.join(labels)}"
            )
    return problems


def operation_ids(api: NinjaAPI) -> set[str]:
    """The ``operation_id`` of every route of ``api`` that declares one."""
    return {route.operation_id for _, route in _routes(api) if route.operation_id}


def _routes(api: NinjaAPI) -> Iterator[tuple[str, Route]]:
    """Each route of ``api`` with its full path, walked as ninja does to build the OpenAPI schema."""
    try:
        root = api.get_root_path({})
    except NoReverseMatch:  # not mounted in the URLconf: paths start at "/"
        root = "/"
    for bound_router in api._get_bound_routers():
        for path, path_view in bound_router.path_operations.items():
            full_path = normalize_path("/".join(("", root, bound_router.prefix, path)))
            full_path = re.sub(r"{[^}:]+:", "{", full_path)  # "{int:id}" → "{id}"
            for route in path_view.operations:
                yield full_path, route


def _method_problems(label: str, route: Route, op: Operation) -> list[str]:
    methods = set(route.methods)
    if op.kind == "query" and methods != {"GET"}:
        return [f"route {label}: {op.name} is a query, served only by GET"]
    if op.kind == "command" and "GET" in methods:
        return [f"route {label}: {op.name} is a command, never served by GET"]
    return []


def _response_problems(label: str, route: Route, op: Operation) -> list[str]:
    success = {
        status: model
        for status, model in route.response_models.items()
        if isinstance(status, int) and 200 <= status < 300
    }
    if not success or NOT_SET in success.values():
        return [
            f"route {label}: declares no response schema, operation {op.name} returns {op.output.__name__}"
        ]
    problems = []
    for model in success.values():
        declared = None if model is None else model.model_fields["response"].annotation
        if not _same_schema(declared, op.output):
            problems.append(
                f"route {label}: responds with {_type_name(declared)}, operation {op.name} returns {op.output.__name__}"
            )
    return problems


def _input_problems(label: str, route: Route, op: Operation) -> list[str]:
    params = list(route.signature.params)
    inputs = [param for param in params if _same_schema(param.annotation, op.input)]
    if not inputs:
        if not params and not op.input.model_fields:
            return []
        declared = (
            ", ".join(
                f"{param.name}: {_type_name(param.annotation)}" for param in params
            )
            or "no input"
        )
        return [
            f"route {label}: takes {declared}, operation {op.name} takes {op.input.__name__}"
        ]
    problems = [
        f"route {label}: parameter {param.name!r} is not part of the input of {op.name}"
        for param in params
        if param is not inputs[0]
    ]
    is_get = "GET" in route.methods
    source = type(inputs[0].source)._param_source()
    allowed = _INPUT_SOURCES[is_get]
    if source not in allowed:
        method = "a GET" if is_get else f"a {'/'.join(route.methods)}"
        problems.append(
            f"route {label}: {method} takes its input from the {' or the '.join(allowed)}, not the {source}"
        )
    return problems


def _same_schema(declared: Any, expected: type[Schema]) -> bool:
    """Same class, or the same generic parametrization (``Page[ThingOut]``) built twice."""
    if declared is expected:
        return True
    return isinstance(declared, type) and (
        declared.__module__,
        declared.__qualname__,
    ) == (
        expected.__module__,
        expected.__qualname__,
    )


def _type_name(annotation: Any) -> str:
    if annotation is None:
        return "an empty response"
    return annotation.__name__ if isinstance(annotation, type) else repr(annotation)
