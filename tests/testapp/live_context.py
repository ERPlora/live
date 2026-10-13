"""Context builder of the live-stream tests (tests only).

Scope = first label of the Host (``a.localhost`` → ``host:a``); actor = the ``X-Test-User``
header; permissions = the comma-separated ``X-Test-Permissions`` header. ``refresh`` re-reads the
class-level switches so a test can revoke an actor's permissions or sign it out mid-stream, as a
real builder re-reads memberships and sessions before every live re-execution.
"""

import dataclasses
import threading

from live.context import OperationContext, Scope
from live.errors import Unauthorized

USER_HEADER = "X-Test-User"
PERMISSIONS_HEADER = "X-Test-Permissions"


class LiveTestContextBuilder:
    __test__ = False  # not a pytest test class

    revoked: set[str] = set()
    signed_out: set[str] = set()
    refreshes = 0
    _lock = threading.Lock()

    @classmethod
    def reset(cls) -> None:
        cls.revoked = set()
        cls.signed_out = set()
        cls.refreshes = 0

    def from_request(self, request) -> OperationContext:
        header = request.headers.get(PERMISSIONS_HEADER, "")
        return OperationContext(
            scope=Scope("host", request.get_host().split(":", 1)[0].split(".", 1)[0]),
            actor=request.headers.get(USER_HEADER) or None,
            permissions=frozenset(name.strip() for name in header.split(",") if name.strip()),
            request=request,
        )

    def refresh(self, ctx: OperationContext) -> OperationContext:
        with self._lock:
            type(self).refreshes += 1
        if ctx.actor in self.signed_out:
            raise Unauthorized("The session was revoked.")
        if ctx.actor in self.revoked:
            return dataclasses.replace(ctx, permissions=frozenset())
        return ctx
