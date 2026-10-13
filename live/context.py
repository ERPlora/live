"""Who runs an operation and where: the scope, the operation context and its builder.

The scope is pluggable: in hub-next phase 1 it is the first label of the Host (``hub``/``a``), in
phase 2 the hub of ``use_hub``; in saas-next it is the user. Each project provides a
``ContextBuilder`` (``settings.LIVE["context_builder"]``) that builds the context from a request
and refreshes it (re-reading permissions) before every live re-execution. The context is never
built from the payload.
"""

import re
from dataclasses import dataclass, field
from functools import cache
from hashlib import blake2b
from typing import Any, Protocol

from django.conf import settings
from django.utils.module_loading import import_string

from live.errors import LiveMisuse

# Postgres identifiers are at most 63 bytes; an unquoted LISTEN folds to lowercase.
CHANNEL_MAX_LENGTH = 63
_KIND_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_CHANNEL_INVALID_CHARS_RE = re.compile(r"[^a-z0-9_]")


@dataclass(frozen=True)
class Scope:
    """Where data lives (a hub, a user); its channel carries the post-commit notifications."""

    kind: str
    key: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or not _KIND_RE.match(self.kind):
            raise ValueError(f"Invalid scope kind {self.kind!r}: expected ^[a-z][a-z0-9_]{{0,31}}$.")
        if not isinstance(self.key, str) or not self.key:
            raise ValueError("The scope key must be a non-empty string.")

    @property
    def channel(self) -> str:
        channel = _CHANNEL_INVALID_CHARS_RE.sub("_", f"live_{self.kind}_{self.key}".lower())
        if len(channel) > CHANNEL_MAX_LENGTH:
            digest = blake2b(self.key.encode(), digest_size=12).hexdigest()
            channel = f"live_{self.kind}_{digest}"
        return channel


@dataclass(frozen=True)
class OperationContext:
    """The caller of an operation: scope, actor and permissions, never taken from the payload."""

    scope: Scope
    actor: Any
    permissions: frozenset[str] = field(default_factory=frozenset)
    language: str = "en"
    request: Any = None

    def __post_init__(self) -> None:
        if not isinstance(self.permissions, frozenset):
            object.__setattr__(self, "permissions", frozenset(self.permissions))

    def has(self, permission: str | None) -> bool:
        if permission is None or "*" in self.permissions or permission in self.permissions:
            return True
        return any(
            granted.endswith(".*") and permission.startswith(granted[:-1])
            for granted in self.permissions
        )


class ContextBuilder(Protocol):
    def from_request(self, request: Any) -> OperationContext: ...

    def refresh(self, ctx: OperationContext) -> OperationContext: ...


def get_builder() -> ContextBuilder:
    """The project's context builder; a class is instantiated once per setting value."""
    path = getattr(settings, "LIVE", {}).get("context_builder")
    if not path:
        raise LiveMisuse('settings.LIVE["context_builder"] is required (dotted path to a ContextBuilder).')
    return _load_builder(path)


@cache
def _load_builder(path: str) -> ContextBuilder:
    try:
        builder = import_string(path)
    except ImportError as exc:
        raise LiveMisuse(f'settings.LIVE["context_builder"] = {path!r} cannot be imported: {exc}') from exc
    return builder() if isinstance(builder, type) else builder


def system_context(scope: Scope) -> OperationContext:
    """Context for the platform itself (worker, scheduled tasks, event reactions)."""
    return OperationContext(scope=scope, actor="system", permissions=frozenset({"*"}))
