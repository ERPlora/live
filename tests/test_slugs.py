"""Hub slugs (live.slugs): one shared rule and one shared list of reserved names (Ioan, 2026-10-13)."""

import pytest
from django.core.exceptions import ValidationError
from django.utils import translation
from live.errors import LiveMisuse
from live.slugs import (
    HUB_SLUG_MAX_LENGTH,
    HUB_SLUG_MIN_LENGTH,
    HUB_SLUG_RE,
    RESERVED_HUB_SLUGS,
    hub_slug_min_length,
    hub_slug_validator,
    is_reserved_hub_slug,
    validate_hub_slug,
)

# Ioan's list, as he gave it, plus `hubs`: that is ERPlora's own platform host (round 13, PLAN §18);
# `hub` stays reserved and the rest are blocked names.
IOAN_LIST = (
    "hub, hubs, erplora, saas, platform, system, sys, internal, www, mail, webmail, smtp, imap, pop, mx, ns1, "
    "ns2, ftp, cdn, static, assets, api, ws, dev, test, staging, demo, localhost, admin, administrator, "
    "root, superuser, staff, support, help, status, security, abuse, postmaster, hostmaster, webmaster, "
    "noreply, no-reply, app, apps, login, auth, account, accounts, billing, pay, payments, invoice, shop, "
    "store, docs, blog"
)


def test_the_reserved_list_is_exactly_ioans():
    assert isinstance(RESERVED_HUB_SLUGS, frozenset)
    assert RESERVED_HUB_SLUGS == frozenset(IOAN_LIST.split(", "))


def test_the_limits():
    assert (HUB_SLUG_MIN_LENGTH, HUB_SLUG_MAX_LENGTH) == (3, 63)


@pytest.mark.parametrize("slug", ["hub", "www", "mail", "no-reply", "localhost", "WWW", "Hub"])
def test_reserved_names_are_reserved_in_any_case(slug):
    assert is_reserved_hub_slug(slug)


@pytest.mark.parametrize("slug", ["acme", "my-hub", "www2", "a"])
def test_other_names_are_not_reserved(slug):
    assert not is_reserved_hub_slug(slug)


# Round 13 (PLAN §18): `hubs.erplora.com` is the platform host, the Hub's admin for the staff.
@pytest.mark.parametrize("slug", ["hubs", "HUBS", "Hubs"])
def test_hubs_is_reserved_because_it_is_the_platform_host(slug):
    assert is_reserved_hub_slug(slug)
    with pytest.raises(ValueError, match="^reserved$"):
        validate_hub_slug(slug)


@pytest.mark.parametrize("slug", ["abc", "acme", "bar-123", "0day", "123", "a" * 63, "a-b", "x" + "-" * 61 + "y"])
def test_valid_slugs_are_returned_as_they_are(slug):
    assert validate_hub_slug(slug) == slug


@pytest.mark.parametrize(
    ("slug", "code"),
    [
        ("hub", "reserved"),
        ("www", "reserved"),
        ("WWW", "reserved"),
        ("ws", "reserved"),
        ("a", "too_short"),
        ("ab", "too_short"),
        ("", "too_short"),
        ("a" * 64, "too_long"),
        ("xn--bcher-kva", "punycode"),
        ("-abc", "invalid_format"),
        ("abc-", "invalid_format"),
        ("Acme", "invalid_format"),
        ("ac_me", "invalid_format"),
        ("ac.me", "invalid_format"),
        ("acmé", "invalid_format"),
        ("ac me", "invalid_format"),
        ("acme\n", "invalid_format"),
        (None, "invalid_format"),
        (42, "invalid_format"),
    ],
)
def test_invalid_slugs_raise_a_code(slug, code):
    with pytest.raises(ValueError, match=f"^{code}$"):
        validate_hub_slug(slug)


def test_the_regex_is_one_dns_label():
    assert HUB_SLUG_RE.fullmatch("a")
    assert HUB_SLUG_RE.fullmatch("abc")
    assert not HUB_SLUG_RE.fullmatch("ab")  # one character or 3–63, never two
    assert not HUB_SLUG_RE.fullmatch("a" * 64)


class TestMinLengthSetting:
    def test_defaults_to_three(self, settings):
        settings.LIVE = {key: value for key, value in settings.LIVE.items() if key != "hub_slug_min_length"}
        assert hub_slug_min_length() == 3

    def test_local_development_may_open_one_letter_hubs(self, settings):
        settings.LIVE = {**settings.LIVE, "hub_slug_min_length": 1}
        assert (validate_hub_slug("a"), validate_hub_slug("b")) == ("a", "b")

    def test_two_letters_never_fit_the_rule(self, settings):
        settings.LIVE = {**settings.LIVE, "hub_slug_min_length": 1}
        with pytest.raises(ValueError, match="^invalid_format$"):
            validate_hub_slug("ab")

    def test_reserved_names_stay_reserved_with_any_minimum(self, settings):
        settings.LIVE = {**settings.LIVE, "hub_slug_min_length": 1}
        with pytest.raises(ValueError, match="^reserved$"):
            validate_hub_slug("www")

    @pytest.mark.parametrize("value", [0, 64, "1", True, None, 2.0])
    def test_a_wrong_setting_is_a_misuse(self, settings, value):
        settings.LIVE = {**settings.LIVE, "hub_slug_min_length": value}
        with pytest.raises(LiveMisuse, match="hub_slug_min_length"):
            hub_slug_min_length()


class TestValidator:
    def test_a_valid_slug_passes(self):
        assert hub_slug_validator("acme") is None

    @pytest.mark.parametrize(
        ("slug", "code", "message"),
        [
            ("www", "reserved", "This name is reserved."),
            ("ab", "too_short", "Use at least 3 characters."),
            ("a" * 64, "too_long", "Use at most 63 characters."),
            ("xn--bcher-kva", "punycode", "The name cannot start with “xn--”."),
            (
                "-abc",
                "invalid_format",
                "Use only lowercase letters, digits and hyphens, without a hyphen at the start or the end.",
            ),
        ],
    )
    def test_an_invalid_slug_is_a_validation_error_with_its_code(self, slug, code, message):
        with pytest.raises(ValidationError) as caught:
            hub_slug_validator(slug)
        assert caught.value.code == code
        assert caught.value.messages == [message]

    @pytest.mark.parametrize(
        ("slug", "message"),
        [
            ("www", "Este nombre está reservado."),
            ("ab", "Usa al menos 3 caracteres."),
            ("a" * 64, "Usa como máximo 63 caracteres."),
            ("xn--bcher-kva", "El nombre no puede empezar por «xn--»."),
            ("-abc", "Usa solo minúsculas, números y guiones, sin guion al principio ni al final."),
        ],
    )
    def test_the_messages_are_translated(self, slug, message):
        with translation.override("es"):
            with pytest.raises(ValidationError) as caught:
                hub_slug_validator(slug)
            # Lazy messages: read them while Spanish is active.
            assert caught.value.messages == [message]


def test_ci_must_fail_on_purpose():
    # Deliberately red: proves the CI check catches a failing test (reverted in the next commit).
    assert 1 == 2
