"""Errors raised by operations and the single error envelope sent to clients.

Every failure an operation reports to its caller is an ``OperationError``: the ninja route, the
live stream and the assistant turn it into ``{"error": {"code", "message", "fields"?}}`` with its
HTTP status. ``fields`` (per field) is only present when the error carries it, i.e. the 422.

``LiveMisuse`` is different: it is a programming error (a misdeclared operation, a missing
setting) and is never sent to a client as an envelope.
"""

from django.core.exceptions import ImproperlyConfigured


class OperationError(Exception):
    """An expected failure of an operation, sent to the client as the error envelope."""

    status: int = 400
    code: str = "error"
    #: For a passing failure that ran nothing (such as a hub busy for a moment, refused before any statement): the
    #: seconds after which the same call may succeed. ``None`` for any other failure, and always for one that may have
    #: done something. The live executor tries the query again after it (``live.executor``).
    retry_after: float | None = None

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status: int | None = None,
        fields: dict[str, str] | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status is not None:
            self.status = status
        if retry_after is not None:
            self.retry_after = retry_after
        self.fields = dict(fields) if fields else None

    def envelope(self) -> dict:
        error: dict = {"code": self.code, "message": self.message}
        if self.fields:
            error["fields"] = dict(self.fields)
        return {"error": error}


class Unauthorized(OperationError):
    status = 401
    code = "unauthorized"


class PermissionDenied(OperationError):
    status = 403
    code = "permission_denied"


class NotFound(OperationError):
    status = 404
    code = "not_found"


class AppInactive(OperationError):
    status = 404
    code = "app_inactive"


class Conflict(OperationError):
    """A 409 whose code is a domain code chosen by the app (e.g. ``demo.item_done``)."""

    status = 409

    def __init__(self, message: str, *, code: str, fields: dict[str, str] | None = None) -> None:
        super().__init__(message, code=code, fields=fields)


class InvalidPayload(OperationError):
    status = 422
    code = "invalid_payload"


class LiveMisuse(ImproperlyConfigured):
    """A programming error in how the live package is used; never sent to a client."""
