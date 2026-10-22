"""reCAPTCHA Enterprise (score-based, invisible): the assessment and the verdict on a form (live.recaptcha).

Google is never called: ``urlopen`` is replaced by a fake that records the request and answers what each test
needs (an assessment, an HTTP error, a timeout, junk).
"""

import io
import json
import logging
import urllib.error
from urllib.parse import parse_qs, urlsplit

import pytest
from django.test import RequestFactory
from django.utils import translation

from live import recaptcha
from live.errors import LiveMisuse, OperationError
from live.recaptcha import (
    Assessment,
    RecaptchaFailed,
    RecaptchaMisconfigured,
    RecaptchaUnavailable,
)

SITE_KEY = "6Le-test-site-key"
API_KEY = "AIza-test-api-key-never-logged"


def answer(*, valid=True, action="login", score=0.9, reasons=(), invalid_reason=None) -> dict:
    """An assessment as Google's REST API answers it (projects.assessments.create)."""
    token_properties = {"valid": valid, "action": action, "hostname": "erplora.com"}
    if invalid_reason:
        token_properties["invalidReason"] = invalid_reason
    return {
        "name": "projects/123/assessments/abc",
        "event": {"token": "t", "siteKey": SITE_KEY, "expectedAction": action},
        "riskAnalysis": {"score": score, "reasons": list(reasons)},
        "tokenProperties": token_properties,
    }


class FakeGoogle:
    """Stands in for ``urllib.request.urlopen``: records each request and answers ``reply`` (or raises it)."""

    def __init__(self, reply):
        self.reply = reply
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append((request, timeout))
        if isinstance(self.reply, BaseException):
            raise self.reply
        body = self.reply if isinstance(self.reply, bytes) else json.dumps(self.reply).encode()
        return io.BytesIO(body)

    @property
    def event(self) -> dict:
        request, _ = self.requests[-1]
        return json.loads(request.data)["event"]


@pytest.fixture
def recaptcha_on(settings):
    settings.LIVE = {
        **settings.LIVE,
        "recaptcha": {"project": "erplora", "site_key": SITE_KEY, "api_key": API_KEY, "enabled": True},
    }
    return settings


@pytest.fixture
def google(monkeypatch):
    def install(reply):
        fake = FakeGoogle(reply)
        monkeypatch.setattr(recaptcha, "urlopen", fake)
        return fake

    return install


@pytest.fixture(autouse=True)
def forget_the_warning():
    recaptcha._reset_disabled_warning()
    recaptcha._reset_unavailable_counts()
    yield
    recaptcha._reset_disabled_warning()
    recaptcha._reset_unavailable_counts()


def form_post(remote_addr="203.0.113.7", user_agent="Mozilla/5.0 (test)"):
    return RequestFactory().post("/contact/submit/", REMOTE_ADDR=remote_addr, HTTP_USER_AGENT=user_agent)


# --- assess: the request to Google and the reading of its answer -------------------------------------------------


def test_assess_posts_the_event_to_the_projects_assessments_with_the_api_key(recaptcha_on, google):
    fake = google(answer())

    recaptcha.assess("the-token", action="login", remote_ip="203.0.113.7", user_agent="UA/1")

    request, timeout = fake.requests[0]
    url = urlsplit(request.full_url)
    assert request.get_method() == "POST"
    assert (url.scheme, url.netloc, url.path) == (
        "https",
        "recaptchaenterprise.googleapis.com",
        "/v1/projects/erplora/assessments",
    )
    assert parse_qs(url.query) == {"key": [API_KEY]}
    assert request.get_header("Content-type") == "application/json"
    assert timeout == 5
    assert fake.event == {
        "token": "the-token",
        "siteKey": SITE_KEY,
        "expectedAction": "login",
        "userIpAddress": "203.0.113.7",
        "userAgent": "UA/1",
    }


def test_assess_leaves_out_what_it_does_not_know(recaptcha_on, google):
    fake = google(answer())

    recaptcha.assess("the-token", action="login")

    assert fake.event == {"token": "the-token", "siteKey": SITE_KEY, "expectedAction": "login"}


def test_assess_reads_score_validity_action_and_reasons(recaptcha_on, google):
    google(answer(score=0.3, reasons=["AUTOMATION", "TOO_MUCH_TRAFFIC"]))

    assert recaptcha.assess("t", action="login") == Assessment(
        score=0.3, valid=True, action_matches=True, reasons=("AUTOMATION", "TOO_MUCH_TRAFFIC")
    )


def test_assess_says_when_the_token_was_made_for_another_action(recaptcha_on, google):
    google(answer(action="signup"))

    assert recaptcha.assess("t", action="login").action_matches is False


def test_assess_gives_the_invalid_reason_of_a_bad_token(recaptcha_on, google):
    google(answer(valid=False, action="", score=0.0, invalid_reason="MALFORMED"))

    result = recaptcha.assess("t", action="login")

    assert (result.valid, result.reasons) == (False, ("MALFORMED",))


@pytest.mark.parametrize(
    "failure",
    [
        TimeoutError("timed out"),
        urllib.error.URLError("unreachable"),
        urllib.error.HTTPError("https://x", 500, "Internal Server Error", {}, io.BytesIO(b"{}")),
        urllib.error.HTTPError("https://x", 403, "Forbidden", {}, io.BytesIO(b"{}")),
    ],
    ids=["timeout", "unreachable", "http-500", "http-403"],
)
def test_assess_raises_unavailable_when_google_cannot_be_asked(recaptcha_on, google, failure):
    google(failure)

    with pytest.raises(RecaptchaUnavailable):
        recaptcha.assess("t", action="login")


@pytest.mark.parametrize("status", [400, 403, 429])
def test_assess_calls_a_4xx_of_google_misconfigured(recaptcha_on, google, status):
    """A bad key, a project without the API, the quota or the billing: Google answers, but not about the token."""
    google(urllib.error.HTTPError("https://x", status, "Client Error", {}, io.BytesIO(b"{}")))

    with pytest.raises(RecaptchaMisconfigured):
        recaptcha.assess("t", action="login")


@pytest.mark.parametrize("body", [b"not json", b"[]", b'{"riskAnalysis": {"score": 0.9}}'], ids=["junk", "list", "no-token"])
def test_assess_raises_unavailable_on_an_answer_it_cannot_read(recaptcha_on, google, body):
    google(body)

    with pytest.raises(RecaptchaUnavailable):
        recaptcha.assess("t", action="login")


# --- verify_or_raise: the verdict on a form ---------------------------------------------------------------------


def test_a_human_passes_and_gets_the_assessment(recaptcha_on, google):
    google(answer(score=0.9))

    result = recaptcha.verify_or_raise(form_post(), "the-token", "login")

    assert result is not None and result.score == 0.9


def test_the_visitors_address_and_browser_go_to_google(recaptcha_on, google):
    fake = google(answer())

    recaptcha.verify_or_raise(form_post(remote_addr="198.51.100.4", user_agent="Firefox/140"), "t", "login")

    assert (fake.event["userIpAddress"], fake.event["userAgent"]) == ("198.51.100.4", "Firefox/140")


def test_the_minimum_score_itself_passes(recaptcha_on, google):
    google(answer(score=0.5))

    assert recaptcha.verify_or_raise(form_post(), "t", "login") is not None


def test_a_low_score_is_refused_with_400_recaptcha_failed(recaptcha_on, google):
    google(answer(score=0.4, reasons=["AUTOMATION"]))

    with pytest.raises(RecaptchaFailed) as refused:
        recaptcha.verify_or_raise(form_post(), "t", "login")

    assert isinstance(refused.value, OperationError)
    assert (refused.value.status, refused.value.code) == (400, "recaptcha_failed")
    assert refused.value.envelope()["error"]["code"] == "recaptcha_failed"


def test_the_minimum_score_comes_from_the_settings(recaptcha_on, google):
    recaptcha_on.LIVE = {**recaptcha_on.LIVE, "recaptcha": {**recaptcha_on.LIVE["recaptcha"], "min_score": 0.7}}
    google(answer(score=0.6))

    with pytest.raises(RecaptchaFailed):
        recaptcha.verify_or_raise(form_post(), "t", "login")


def test_a_token_of_another_action_is_refused(recaptcha_on, google):
    google(answer(action="signup", score=0.9))

    with pytest.raises(RecaptchaFailed):
        recaptcha.verify_or_raise(form_post(), "t", "login")


def test_an_invalid_token_is_refused(recaptcha_on, google):
    google(answer(valid=False, score=0.9, invalid_reason="DUPE"))

    with pytest.raises(RecaptchaFailed):
        recaptcha.verify_or_raise(form_post(), "t", "login")


@pytest.mark.parametrize("token", [None, "", "   ", 42], ids=["none", "empty", "blank", "not-a-string"])
def test_a_missing_token_is_refused_without_asking_google(recaptcha_on, google, token):
    fake = google(answer())

    with pytest.raises(RecaptchaFailed):
        recaptcha.verify_or_raise(form_post(), token, "login")

    assert fake.requests == []


def test_an_oversized_token_is_refused_without_asking_google(recaptcha_on, google):
    fake = google(answer())

    with pytest.raises(RecaptchaFailed):
        recaptcha.verify_or_raise(form_post(), "x" * (recaptcha.MAX_TOKEN_LENGTH + 1), "login")

    assert fake.requests == []


@pytest.mark.parametrize(
    "failure",
    [TimeoutError("timed out"), urllib.error.HTTPError("https://x", 500, "Server Error", {}, io.BytesIO(b""))],
    ids=["timeout", "http-500"],
)
def test_google_down_fails_closed_and_is_logged_without_the_key(recaptcha_on, google, caplog, failure):
    google(failure)

    with caplog.at_level(logging.WARNING, logger="live.recaptcha"), pytest.raises(RecaptchaFailed):
        recaptcha.verify_or_raise(form_post(), "t", "signup")

    assert any(record.levelno >= logging.ERROR for record in caplog.records)
    assert API_KEY not in caplog.text


def test_the_refusal_speaks_english_and_spanish(recaptcha_on, google):
    google(answer(score=0.1))

    for language, expected in (
        ("en", "We could not check that you are a person. Try again."),
        ("es", "No hemos podido comprobar que eres una persona. Vuelve a intentarlo."),
    ):
        with translation.override(language), pytest.raises(RecaptchaFailed) as refused:
            recaptcha.verify_or_raise(form_post(), "t", "login")
        assert refused.value.message == expected


# --- Google unavailable: the break-glass of the doors of an identified account ---------------------------------
# The sign-in and its second factors (the mailed code, the authenticator app) are already behind the password or the
# code and their attempt limits: when Google cannot be asked, they let the request through, loudly (ERROR, CRITICAL
# for a 4xx: the key, the quota, the billing), so a Google outage never locks everyone out, the staff included. A
# verdict of Google still refuses there, and every other door stays closed.

UNAVAILABLE = [
    TimeoutError("timed out"),
    urllib.error.URLError("unreachable"),
    urllib.error.HTTPError("https://x", 503, "Service Unavailable", {}, io.BytesIO(b"{}")),
    b"<html>not an assessment</html>",
]
UNAVAILABLE_IDS = ["timeout", "unreachable", "http-503", "unreadable"]
LET_THROUGH = ["login", "login_code", "mfa_authenticate"]
KEPT_CLOSED = ["signup", "password_reset", "password_reset_confirm", "verify_email", "verify_email_resend", "contact", "demo_request"]


def test_the_doors_that_let_through_by_default_are_the_sign_in_and_its_second_factors():
    assert frozenset(LET_THROUGH) == recaptcha.DEFAULT_FAIL_OPEN_ON_UNAVAILABLE


@pytest.mark.parametrize("failure", UNAVAILABLE, ids=UNAVAILABLE_IDS)
@pytest.mark.parametrize("action", LET_THROUGH)
def test_google_unavailable_lets_the_sign_in_through_and_says_so(recaptcha_on, google, caplog, action, failure):
    google(failure)

    with caplog.at_level(logging.WARNING, logger="live.recaptcha"):
        assert recaptcha.verify_or_raise(form_post(), "t", action) is None

    [record] = caplog.records
    assert record.levelno == logging.ERROR
    assert record.getMessage().startswith(f"recaptcha.unavailable action={action} ")
    assert "let_through=True" in record.getMessage()
    assert recaptcha.unavailable_counts() == {(action, "unavailable"): 1}


@pytest.mark.parametrize("status", [400, 403])
def test_a_4xx_lets_the_sign_in_through_and_is_critical(recaptcha_on, google, caplog, status):
    google(urllib.error.HTTPError("https://x", status, "Client Error", {}, io.BytesIO(b"{}")))

    with caplog.at_level(logging.WARNING, logger="live.recaptcha"):
        assert recaptcha.verify_or_raise(form_post(), "t", "login") is None

    [record] = caplog.records
    assert record.levelno == logging.CRITICAL
    assert record.getMessage().startswith("recaptcha.misconfigured action=login ")
    assert API_KEY not in caplog.text
    assert recaptcha.unavailable_counts() == {("login", "misconfigured"): 1}


@pytest.mark.parametrize("failure", [*UNAVAILABLE, urllib.error.HTTPError("https://x", 403, "Forbidden", {}, io.BytesIO(b""))], ids=[*UNAVAILABLE_IDS, "http-403"])
@pytest.mark.parametrize("action", KEPT_CLOSED)
def test_google_unavailable_keeps_every_other_door_closed(recaptcha_on, google, caplog, action, failure):
    google(failure)

    with caplog.at_level(logging.WARNING, logger="live.recaptcha"), pytest.raises(RecaptchaFailed):
        recaptcha.verify_or_raise(form_post(), "t", action)

    assert "let_through=False" in caplog.text


@pytest.mark.parametrize(
    ("token", "reply"),
    [
        ("t", answer(action="login", score=0.1)),
        ("t", answer(valid=False, invalid_reason="EXPIRED")),
        ("t", answer(action="signup")),
        ("", answer()),
    ],
    ids=["low-score", "invalid", "other-action", "no-token"],
)
def test_a_verdict_of_google_still_refuses_the_sign_in(recaptcha_on, google, token, reply):
    google(reply)

    with pytest.raises(RecaptchaFailed):
        recaptcha.verify_or_raise(form_post(), token, "login")


def test_the_doors_that_let_through_come_from_the_settings(recaptcha_on, google):
    recaptcha_on.LIVE = {
        **recaptcha_on.LIVE,
        "recaptcha": {**recaptcha_on.LIVE["recaptcha"], "fail_open_on_unavailable": frozenset({"contact"})},
    }
    google(TimeoutError("timed out"))

    assert recaptcha.verify_or_raise(form_post(), "t", "contact") is None
    with pytest.raises(RecaptchaFailed):
        recaptcha.verify_or_raise(form_post(), "t", "login")


def test_the_counts_add_up_per_door_and_kind(recaptcha_on, google):
    google(TimeoutError("timed out"))
    recaptcha.verify_or_raise(form_post(), "t", "login")
    recaptcha.verify_or_raise(form_post(), "t", "login")
    with pytest.raises(RecaptchaFailed):
        recaptcha.verify_or_raise(form_post(), "t", "signup")

    assert recaptcha.unavailable_counts() == {("login", "unavailable"): 2, ("signup", "unavailable"): 1}


@pytest.mark.parametrize("value", ["login", [1], {"login": True}], ids=["a-string", "not-names", "a-dict"])
def test_doors_that_let_through_that_are_not_a_set_of_names_are_a_misuse(recaptcha_on, value):
    recaptcha_on.LIVE = {
        **recaptcha_on.LIVE,
        "recaptcha": {**recaptcha_on.LIVE["recaptcha"], "fail_open_on_unavailable": value},
    }

    with pytest.raises(LiveMisuse):
        recaptcha.verify_or_raise(form_post(), "t", "login")


# --- switched off and misconfigured -----------------------------------------------------------------------------


def test_switched_off_it_lets_the_form_through_and_warns_once(settings, google, caplog):
    settings.LIVE = {**settings.LIVE, "recaptcha": {"enabled": False}}
    fake = google(answer())

    with caplog.at_level(logging.WARNING, logger="live.recaptcha"):
        assert recaptcha.verify_or_raise(form_post(), None, "login") is None
        assert recaptcha.verify_or_raise(form_post(), None, "signup") is None

    assert fake.requests == []
    assert [record.levelno for record in caplog.records] == [logging.WARNING]


def test_without_settings_it_is_off(settings, google):
    settings.LIVE = {key: value for key, value in settings.LIVE.items() if key != "recaptcha"}
    google(answer())

    assert recaptcha.is_enabled() is False
    assert recaptcha.verify_or_raise(form_post(), None, "login") is None


@pytest.mark.parametrize("missing", ["project", "site_key", "api_key"])
def test_switched_on_without_a_key_is_a_misuse(recaptcha_on, missing):
    recaptcha_on.LIVE = {**recaptcha_on.LIVE, "recaptcha": {**recaptcha_on.LIVE["recaptcha"], missing: ""}}

    with pytest.raises(LiveMisuse):
        recaptcha.verify_or_raise(form_post(), "t", "login")


@pytest.mark.parametrize("min_score", [-0.1, 1.1, "high"])
def test_a_minimum_score_outside_zero_to_one_is_a_misuse(recaptcha_on, min_score):
    recaptcha_on.LIVE = {**recaptcha_on.LIVE, "recaptcha": {**recaptcha_on.LIVE["recaptcha"], "min_score": min_score}}

    with pytest.raises(LiveMisuse):
        recaptcha.verify_or_raise(form_post(), "t", "login")


def test_the_endpoint_may_be_another_one(recaptcha_on, google):
    recaptcha_on.LIVE = {
        **recaptcha_on.LIVE,
        "recaptcha": {**recaptcha_on.LIVE["recaptcha"], "endpoint": "http://127.0.0.1:8018/v1/projects/erplora/assessments"},
    }
    fake = google(answer())

    recaptcha.assess("t", action="login")

    url = urlsplit(fake.requests[0][0].full_url)
    assert (url.netloc, url.path) == ("127.0.0.1:8018", "/v1/projects/erplora/assessments")


def test_the_site_key_is_public_and_empty_when_off(recaptcha_on, settings):
    assert recaptcha.site_key() == SITE_KEY
    settings.LIVE = {**settings.LIVE, "recaptcha": {"enabled": False, "site_key": SITE_KEY}}
    assert recaptcha.site_key() == ""


# --- the Content Security Policy Google's scripts need -----------------------------------------------------------


def test_with_recaptcha_adds_googles_sources_to_a_fresh_copy():
    policy = {
        "default-src": ["'self'"],
        "script-src": ["'self'", "'nonce'"],
        "connect-src": ["'self'"],
    }

    widened = recaptcha.with_recaptcha(policy)

    assert widened["script-src"] == [
        "'self'",
        "'nonce'",
        "https://www.google.com/recaptcha/",
        "https://www.gstatic.com/recaptcha/",
    ]
    assert widened["frame-src"] == [
        "'self'",
        "https://www.google.com/recaptcha/",
        "https://recaptcha.google.com/recaptcha/",
    ]
    assert widened["connect-src"] == ["'self'", "https://www.google.com/recaptcha/"]
    assert "trusted-types" not in widened
    assert policy["script-src"] == ["'self'", "'nonce'"]


def test_with_recaptcha_admits_googles_trusted_types_policy_and_adds_nothing_twice():
    policy = {
        "default-src": ["'self'"],
        "frame-src": ["https://www.google.com/recaptcha/"],
        "trusted-types": ["default", "vue", "'allow-duplicates'"],
    }

    widened = recaptcha.with_recaptcha(recaptcha.with_recaptcha(policy))

    assert widened["trusted-types"] == ["default", "vue", "'allow-duplicates'", "goog#html"]
    assert widened["frame-src"] == ["https://www.google.com/recaptcha/", "https://recaptcha.google.com/recaptcha/"]
