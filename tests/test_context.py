"""Scopes, operation contexts and the pluggable context builder."""

import dataclasses
import re
from hashlib import blake2b

import pytest
from live.context import OperationContext, Scope, get_builder, system_context
from live.errors import LiveMisuse

CHANNEL_RE = re.compile(r"^[a-z0-9_]{1,63}$")


class FakeBuilder:
    """Context builder used by the get_builder tests (loaded by dotted path)."""

    def from_request(self, request):
        return OperationContext(scope=Scope("hub", "a"), actor="user", permissions=frozenset())

    def refresh(self, ctx):
        return ctx


class OtherFakeBuilder(FakeBuilder):
    pass


fake_builder_instance = FakeBuilder()


def make_ctx(*permissions):
    return OperationContext(scope=Scope("hub", "a"), actor="user", permissions=frozenset(permissions))


# Scope.channel


def test_channel_is_prefixed_with_live_and_the_kind():
    assert Scope("hub", "a").channel == "live_hub_a"


def test_channel_is_lowercased_and_sanitized():
    channel = Scope("hub", "My-Shop.Example").channel

    assert channel == "live_hub_my_shop_example"
    assert CHANNEL_RE.match(channel)


def test_channel_of_a_long_key_is_hashed_and_fits_in_63_chars():
    key = "x" * 80

    channel = Scope("user", key).channel

    assert channel == "live_user_" + blake2b(key.encode(), digest_size=12).hexdigest()
    assert len(channel) <= 63
    assert CHANNEL_RE.match(channel)


def test_channel_at_the_limit_is_not_hashed():
    key = "k" * (63 - len("live_hub_"))

    assert Scope("hub", key).channel == f"live_hub_{key}"


def test_distinct_long_keys_get_distinct_channels():
    assert Scope("user", "a" * 80).channel != Scope("user", "b" * 80).channel


@pytest.mark.parametrize(("kind", "key"), [("", "a"), ("hub", ""), ("Hub", "a"), ("hub-x", "a"), ("h" * 33, "a")])
def test_invalid_kind_or_empty_key_is_rejected(kind, key):
    with pytest.raises(ValueError):
        Scope(kind, key)


def test_scope_is_immutable():
    with pytest.raises(dataclasses.FrozenInstanceError):
        Scope("hub", "a").key = "b"


# OperationContext.has


def test_no_permission_required_is_always_granted():
    assert make_ctx().has(None)


def test_star_grants_everything():
    assert make_ctx("*").has("demo.manage")


def test_exact_permission_is_granted():
    ctx = make_ctx("demo.view")

    assert ctx.has("demo.view")
    assert not ctx.has("demo.manage")


def test_prefix_wildcard_grants_permissions_of_that_app_only():
    ctx = make_ctx("demo.*")

    assert ctx.has("demo.view")
    assert ctx.has("demo.manage")
    assert not ctx.has("demox.view")
    assert not ctx.has("other.view")


def test_empty_permissions_grant_nothing():
    assert not make_ctx().has("demo.view")


def test_context_defaults_and_permissions_are_frozen():
    ctx = OperationContext(scope=Scope("hub", "a"), actor="user", permissions={"demo.view"})

    assert ctx.language == "en"
    assert ctx.request is None
    assert ctx.permissions == frozenset({"demo.view"})
    assert isinstance(ctx.permissions, frozenset)


# system_context


def test_system_context_acts_as_system_with_every_permission():
    scope = Scope("hub", "a")

    ctx = system_context(scope)

    assert ctx.scope == scope
    assert ctx.actor == "system"
    assert ctx.permissions == frozenset({"*"})
    assert ctx.has("anything.at_all")


# get_builder


def test_get_builder_without_live_setting_is_misuse(settings):
    if hasattr(settings, "LIVE"):
        del settings.LIVE

    with pytest.raises(LiveMisuse):
        get_builder()


def test_get_builder_without_context_builder_key_is_misuse(settings):
    settings.LIVE = {}

    with pytest.raises(LiveMisuse):
        get_builder()


def test_get_builder_with_unimportable_path_is_misuse(settings):
    settings.LIVE = {"context_builder": "tests.test_context.DoesNotExist"}

    with pytest.raises(LiveMisuse):
        get_builder()


def test_get_builder_instantiates_a_class_once_per_setting_value(settings):
    settings.LIVE = {"context_builder": "tests.test_context.FakeBuilder"}

    first = get_builder()

    assert isinstance(first, FakeBuilder)
    assert get_builder() is first

    settings.LIVE = {"context_builder": "tests.test_context.OtherFakeBuilder"}

    assert isinstance(get_builder(), OtherFakeBuilder)


def test_get_builder_uses_an_instance_as_is(settings):
    settings.LIVE = {"context_builder": "tests.test_context.fake_builder_instance"}

    assert get_builder() is fake_builder_instance
