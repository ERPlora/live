"""reCAPTCHA Enterprise, score-based and invisible: is the one who sends a form a person?

The page loads Google's ``enterprise.js`` with the site key and, on submit, asks it for a token tied to the form's
action (``grecaptcha.enterprise.execute(siteKey, {action})``); the form carries it (``recaptcha_token``). The server
asks Google for an assessment of that token (``assess``) and ``verify_or_raise`` turns it into a verdict: the form
goes on, or a 400 ``recaptcha_failed`` (``RecaptchaFailed``, an ``OperationError``, so the envelope of the API).
Nobody sees a checkbox or a puzzle. Refused: no token, a token Google says is invalid (malformed, expired, used
twice, of another site), a token of another action, a score under ``min_score``, and Google itself unreachable or
answering something unreadable (fail closed: a public form is never let through unverified; the cause is logged).

Settings, ``LIVE["recaptcha"]``:

- ``enabled``: off (the default, and local development without keys), every form goes through and a warning is
  logged once per process;
- ``project``: the Google Cloud project of the keys (``erplora``);
- ``site_key``: the public key the page loads ``enterprise.js`` with (``site_key()``, empty when off);
- ``api_key``: the secret key of the assessments' REST API (never logged);
- ``min_score``: from 0 to 1, 0.5 by default (Google's own default threshold);
- ``endpoint``: the assessments' URL, Google's for ``project`` by default.

REST API: ``POST https://recaptchaenterprise.googleapis.com/v1/projects/<project>/assessments?key=<api_key>`` with
``{"event": {"token", "siteKey", "expectedAction", "userIpAddress", "userAgent"}}``, answered with
``tokenProperties`` (``valid``, ``invalidReason``, ``action``) and ``riskAnalysis`` (``score``, ``reasons``)
(https://docs.cloud.google.com/recaptcha/docs/create-assessment-website). Plain ``urllib``: one POST, no
dependency, 5 seconds at most.

``with_recaptcha(policy)`` adds what Google's scripts need to a Content Security Policy (its FAQ, «CSP»): its two
script origins, its frames and its connection, and ``goog#html``, the Trusted Types policy its script creates.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.http import HttpRequest
from django.utils.translation import gettext_lazy as _

from live.errors import LiveMisuse, OperationError

logger = logging.getLogger(__name__)

#: Google's default threshold: 1.0 is very likely a person, 0.0 very likely a bot.
DEFAULT_MIN_SCORE = 0.5
#: Seconds the assessment may take before the form is refused (fail closed).
TIMEOUT_SECONDS = 5
#: Google's assessments of a project.
GOOGLE_ENDPOINT = "https://recaptchaenterprise.googleapis.com/v1/projects/{project}/assessments"
#: A token is about 2 KB; anything far longer is not one and never reaches Google.
MAX_TOKEN_LENGTH = 8 * 1024
#: The Trusted Types policy Google's ``recaptcha__<lang>.js`` creates (Closure's ``goog#html``).
TRUSTED_TYPES_POLICY = "goog#html"
#: What Google's scripts need, by directive (reCAPTCHA FAQ, «Content Security Policy»).
CSP_SOURCES: dict[str, list[str]] = {
    "script-src": ["https://www.google.com/recaptcha/", "https://www.gstatic.com/recaptcha/"],
    "frame-src": ["https://www.google.com/recaptcha/", "https://recaptcha.google.com/recaptcha/"],
    "connect-src": ["https://www.google.com/recaptcha/"],
}


@dataclass(frozen=True)
class Assessment:
    """Google's reading of a token: its score (0–1), whether the token is valid, whether it was made for the
    expected action, and the reasons (``invalidReason`` of an invalid token, else ``riskAnalysis.reasons``)."""

    score: float
    valid: bool
    action_matches: bool
    reasons: tuple[str, ...]


class RecaptchaUnavailable(Exception):
    """Google could not be asked (timeout, network, an HTTP error) or answered something unreadable."""


class RecaptchaFailed(OperationError):
    """The form was not sent by a person, as far as reCAPTCHA can tell (or it could not tell)."""

    status = 400
    code = "recaptcha_failed"

    def __init__(self) -> None:
        super().__init__(str(_("We could not check that you are a person. Try again.")))


_warned_disabled = False


def _reset_disabled_warning() -> None:
    """Forget that the warning of a switched-off reCAPTCHA was logged (tests)."""
    global _warned_disabled
    _warned_disabled = False


def _settings() -> dict[str, Any]:
    return getattr(settings, "LIVE", {}).get("recaptcha") or {}


def is_enabled() -> bool:
    return bool(_settings().get("enabled", False))


def _config() -> dict[str, Any]:
    """The settings of a switched-on reCAPTCHA, checked: every key present, ``min_score`` from 0 to 1."""
    conf = _settings()
    missing = [name for name in ("project", "site_key", "api_key") if not conf.get(name)]
    if missing:
        raise LiveMisuse(f'settings.LIVE["recaptcha"] is enabled without {", ".join(missing)}.')
    min_score = conf.get("min_score", DEFAULT_MIN_SCORE)
    if isinstance(min_score, bool) or not isinstance(min_score, int | float) or not 0 <= min_score <= 1:
        raise LiveMisuse(f'settings.LIVE["recaptcha"]["min_score"] = {min_score!r} must be a number from 0 to 1.')
    return {
        **conf,
        "min_score": float(min_score),
        "endpoint": conf.get("endpoint") or GOOGLE_ENDPOINT.format(project=conf["project"]),
    }


def site_key() -> str:
    """The public key the page loads ``enterprise.js`` with; empty when reCAPTCHA is off (no script, no token)."""
    return str(_settings().get("site_key") or "") if is_enabled() else ""


def assess(
    token: str, *, action: str, remote_ip: str | None = None, user_agent: str | None = None
) -> Assessment:
    """Google's assessment of ``token`` for ``action``; ``RecaptchaUnavailable`` when it cannot be had."""
    conf = _config()
    event = {"token": token, "siteKey": conf["site_key"], "expectedAction": action}
    if remote_ip:
        event["userIpAddress"] = remote_ip
    if user_agent:
        event["userAgent"] = user_agent
    request = Request(
        f"{conf['endpoint']}?{urlencode({'key': conf['api_key']})}",
        data=json.dumps({"event": event}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read()
    except HTTPError as error:
        # The URL carries the API key: only the status is told.
        raise RecaptchaUnavailable(f"HTTP {error.code}") from None
    except (TimeoutError, OSError) as error:
        raise RecaptchaUnavailable(type(error).__name__) from None
    try:
        payload = json.loads(body)
        properties = payload["tokenProperties"]
        risk = payload.get("riskAnalysis") or {}
        valid = properties.get("valid") is True
        reasons = (
            (str(properties.get("invalidReason") or "INVALID_REASON_UNSPECIFIED"),)
            if not valid
            else tuple(str(reason) for reason in risk.get("reasons") or ())
        )
        return Assessment(
            score=float(risk.get("score") or 0.0),
            valid=valid,
            action_matches=properties.get("action") == action,
            reasons=reasons,
        )
    except (ValueError, TypeError, KeyError, AttributeError):
        raise RecaptchaUnavailable("unreadable answer") from None


def verify_or_raise(request: HttpRequest, token: Any, action: str) -> Assessment | None:
    """The verdict on a form of ``action``: its assessment, or ``RecaptchaFailed`` (400 ``recaptcha_failed``).

    ``None`` when reCAPTCHA is off: the form goes through, and the first time a warning is logged.
    """
    global _warned_disabled
    if not is_enabled():
        if not _warned_disabled:
            _warned_disabled = True
            logger.warning("recaptcha.disabled: the forms are not checked for bots (LIVE['recaptcha'] off)")
        return None
    conf = _config()
    if not isinstance(token, str) or not token.strip() or len(token) > MAX_TOKEN_LENGTH:
        logger.info("recaptcha.refused action=%s reason=MISSING_TOKEN", action)
        raise RecaptchaFailed()
    try:
        result = assess(
            token.strip(),
            action=action,
            remote_ip=request.META.get("REMOTE_ADDR") or None,
            user_agent=request.headers.get("User-Agent") or None,
        )
    except RecaptchaUnavailable as error:
        logger.error("recaptcha.unavailable action=%s cause=%s", action, error)
        raise RecaptchaFailed() from None
    if not result.valid or not result.action_matches or result.score < conf["min_score"]:
        logger.info(
            "recaptcha.refused action=%s valid=%s action_matches=%s score=%.2f reasons=%s",
            action,
            result.valid,
            result.action_matches,
            result.score,
            ",".join(result.reasons) or "-",
        )
        raise RecaptchaFailed()
    return result


def with_recaptcha(policy: dict[str, list[str]]) -> dict[str, list[str]]:
    """``policy`` (a fresh copy) admitting Google's reCAPTCHA scripts, frames and connection.

    A directive the policy did not have starts from its ``default-src``, so what it admitted before it still
    admits. ``trusted-types``, when the policy has it, admits ``goog#html``. Nothing is added twice.
    """
    result = {name: list(sources) for name, sources in policy.items()}
    for name, sources in CSP_SOURCES.items():
        current = result.get(name, list(result.get("default-src", [])))
        result[name] = [*current, *(source for source in sources if source not in current)]
    if "trusted-types" in result and TRUSTED_TYPES_POLICY not in result["trusted-types"]:
        result["trusted-types"].append(TRUSTED_TYPES_POLICY)
    return result
