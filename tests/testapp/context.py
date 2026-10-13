"""Context builder of the test suite (tests only).

Scope = first label of the Host (``a.localhost`` → ``a``); actor = the authenticated user, if
any; permissions = the comma-separated ``X-Test-Permissions`` header. A real builder never trusts
a header for permissions: this one exists so tests can choose them per request.
"""

from live.context import OperationContext, Scope

PERMISSIONS_HEADER = "X-Test-Permissions"


class TestContextBuilder:
    __test__ = False  # not a pytest test class

    def from_request(self, request) -> OperationContext:
        user = getattr(request, "user", None)
        header = request.headers.get(PERMISSIONS_HEADER, "")
        return OperationContext(
            scope=Scope("host", request.get_host().split(":", 1)[0].split(".", 1)[0]),
            actor=user if user is not None and user.is_authenticated else None,
            permissions=frozenset(name.strip() for name in header.split(",") if name.strip()),
            language=getattr(request, "LANGUAGE_CODE", "en"),
            request=request,
        )

    def refresh(self, ctx: OperationContext) -> OperationContext:
        return ctx
