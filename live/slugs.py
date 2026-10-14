"""Hub slugs: the first label of a hub's host (``<slug>.erplora.com``), shared by hub-next and saas-next.

A slug is one DNS label (``HUB_SLUG_RE``): lowercase letters, digits and hyphens, never a hyphen at
the start or the end, 3–63 characters, never punycode (``xn--``) and never one of the reserved
system names (``RESERVED_HUB_SLUGS``). Of those, ``hubs`` is ERPlora's own platform host (the Hub's
admin for the staff; round 13, PLAN §18), ``pre`` is the team's pre-production environment
(``pre.erplora.com``, whose hubs live under ``*.pre.erplora.com``), ``hub`` stays reserved and the rest
are blocked so no customer takes them.
Hubs are served under the wildcard certificate ``*.erplora.com``: there is no limit to their number.

``settings.LIVE["hub_slug_min_length"]`` (default 3) only lowers the minimum in local development,
where the demo hubs are ``a`` and ``b``. ``HUB_SLUG_RE`` admits one character or 3–63, never two,
and its ``$`` admits a trailing newline: check with ``validate_hub_slug`` or ``hub_slug_validator``,
never with ``RegexValidator(HUB_SLUG_RE)``.
"""

import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from live.errors import LiveMisuse

HUB_SLUG_MIN_LENGTH = 3
HUB_SLUG_MAX_LENGTH = 63
HUB_SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{1,61}[a-z0-9])?$")
PUNYCODE_PREFIX = "xn--"

RESERVED_HUB_SLUGS: frozenset[str] = frozenset(
    {
        # ERPlora's own platform host (`hubs`, the Hub's admin for the staff; round 13) and `hub`.
        "hub", "hubs",
        # The platform and its parts.
        "erplora", "saas", "platform", "system", "sys", "internal",
        # Web, mail and DNS.
        "www", "mail", "webmail", "smtp", "imap", "pop", "mx", "ns1", "ns2", "ftp",
        # Serving and environments.
        "cdn", "static", "assets", "api", "ws", "dev", "test", "staging", "pre", "demo", "localhost",
        # Authority and support.
        "admin", "administrator", "root", "superuser", "staff", "support", "help", "status", "security",
        "abuse", "postmaster", "hostmaster", "webmaster", "noreply", "no-reply",
        # Product words a customer could be misled by.
        "app", "apps", "login", "auth", "account", "accounts", "billing", "pay", "payments", "invoice",
        "shop", "store", "docs", "blog",
    }
)  # fmt: skip

# Error codes of ``validate_hub_slug`` (the ``ValueError``'s message) and of ``hub_slug_validator``.
RESERVED = "reserved"
INVALID_FORMAT = "invalid_format"
TOO_SHORT = "too_short"
TOO_LONG = "too_long"
PUNYCODE = "punycode"

_MESSAGES = {
    RESERVED: _("This name is reserved."),
    INVALID_FORMAT: _("Use only lowercase letters, digits and hyphens, without a hyphen at the start or the end."),
    TOO_SHORT: _("Use at least %(min)d characters."),
    TOO_LONG: _("Use at most %(max)d characters."),
    PUNYCODE: _("The name cannot start with “xn--”."),
}


def hub_slug_min_length() -> int:
    """The minimum length in force: ``settings.LIVE["hub_slug_min_length"]``, 3 by default."""
    value = getattr(settings, "LIVE", {}).get("hub_slug_min_length", HUB_SLUG_MIN_LENGTH)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= HUB_SLUG_MAX_LENGTH:
        raise LiveMisuse(
            f'settings.LIVE["hub_slug_min_length"] = {value!r} must be an int from 1 to {HUB_SLUG_MAX_LENGTH}.'
        )
    return value


def is_reserved_hub_slug(slug: str) -> bool:
    """Whether ``slug`` is a reserved name, in any case (host names are case-insensitive)."""
    return slug.lower() in RESERVED_HUB_SLUGS


def validate_hub_slug(slug: str) -> str:
    """Return ``slug`` if it may name a hub; else raise ``ValueError`` whose message is the code."""
    if not isinstance(slug, str):
        # One exception for every bad slug, so a caller handles a single case.
        raise ValueError(INVALID_FORMAT)  # noqa: TRY004
    if is_reserved_hub_slug(slug):
        raise ValueError(RESERVED)
    if len(slug) > HUB_SLUG_MAX_LENGTH:
        raise ValueError(TOO_LONG)
    if len(slug) < hub_slug_min_length():
        raise ValueError(TOO_SHORT)
    if slug.startswith(PUNYCODE_PREFIX):
        raise ValueError(PUNYCODE)
    if not HUB_SLUG_RE.fullmatch(slug):
        raise ValueError(INVALID_FORMAT)
    return slug


def hub_slug_validator(value: str) -> None:
    """Validator of a model or form field that holds a hub slug (``validators=[hub_slug_validator]``)."""
    try:
        validate_hub_slug(value)
    except ValueError as exc:
        code = str(exc)
        params = {"min": hub_slug_min_length(), "max": HUB_SLUG_MAX_LENGTH}
        raise ValidationError(_MESSAGES[code], code=code, params=params) from None
