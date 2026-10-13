"""Outbox: events recorded in the command's transaction and one NOTIFY after the COMMIT.

The NOTIFY is observed from a raw psycopg session in autocommit, outside Django, the way another
process (the live broker) sees it; a second raw session reads the outbox table to see what is
committed and what is not.
"""

import json
import logging

import psycopg
import pytest
from django.apps import apps
from django.conf import settings
from django.db import connection, transaction
from django.test import override_settings
from django.utils.connection import ConnectionDoesNotExist
from live import operations, outbox
from live.context import OperationContext, Scope
from live.errors import Conflict, LiveMisuse
from live.models import OutboxEvent
from live.operations import operation, registry
from live.outbox import MAX_NOTIFY_BYTES, channel_for, notify, record_event

from tests.testapp.models import Thing
from tests.testapp.schemas import ThingIn, ThingOut
from tests.testapp.services import create_thing, create_thing_twice_event, fail_after_event

SCOPE = Scope("hub", "a")
OTHER_SCOPE = Scope("hub", "b")
# How long a test waits for a notification that should arrive; one that must not arrive is
# awaited for QUIET seconds.
WAIT = 1.0
QUIET = 0.3


@pytest.fixture(autouse=True)
def isolated_registry():
    saved = dict(registry)
    yield
    registry.clear()
    registry.update(saved)


@pytest.fixture
def listen(db_dsn):
    """Open raw autocommit sessions that LISTEN on a scope's channel; closed after the test."""
    sessions = []

    def open_session(scope=SCOPE):
        session = psycopg.connect(db_dsn, autocommit=True)
        sessions.append(session)
        session.execute(f"LISTEN {channel_for(scope)}")
        return session

    yield open_session
    for session in sessions:
        session.close()


@pytest.fixture
def raw(db_dsn):
    """A raw autocommit session that only sees what is committed."""
    with psycopg.connect(db_dsn, autocommit=True) as session:
        yield session


def received(session, timeout=WAIT, stop_after=None):
    return [
        (note.channel, json.loads(note.payload))
        for note in session.notifies(timeout=timeout, stop_after=stop_after)
    ]


def committed_rows(session):
    return session.execute(
        "SELECT name, scope_kind, scope_key, actor, payload FROM live_outboxevent ORDER BY created_at, id"
    ).fetchall()


def make_ctx(scope=SCOPE, actor="user"):
    return OperationContext(scope=scope, actor=actor, permissions=frozenset({"testapp.*"}))


def declare(name, *, kind, body):
    """Register an ad-hoc operation whose function pretends to live in an app module."""

    def fn(ctx, data):
        return body(ctx, data)

    fn.__module__ = "x.queries" if kind == "query" else "x.services"
    return operation(name, kind=kind, permission=None, input=ThingIn, output=ThingOut)(fn)


def echo(ctx, data):
    return {"id": 1, "name": data.name}


# Misuse: only a running command records events, with a valid name


@pytest.mark.django_db
def test_record_event_outside_a_command_is_misuse():
    with pytest.raises(LiveMisuse):
        record_event(make_ctx(), "testapp.thing.created")

    with pytest.raises(LiveMisuse), transaction.atomic():
        record_event(make_ctx(), "testapp.thing.created")

    assert not OutboxEvent.objects.exists()


@pytest.mark.django_db
def test_record_event_inside_a_query_is_misuse():
    def body(ctx, data):
        record_event(ctx, "x.thing.created")
        return echo(ctx, data)

    query = declare("x.thing.peek", kind="query", body=body)

    # LiveMisuse before the INSERT, not the READ ONLY error of the database.
    with pytest.raises(LiveMisuse):
        query(make_ctx(), ThingIn(name="a"))

    assert not OutboxEvent.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("name", ["bad.name", "x.thing.created.extra", "X.thing.created", ""])
def test_record_event_with_a_name_that_is_not_app_entity_fact_is_misuse(name):
    def body(ctx, data):
        record_event(ctx, name)
        return echo(ctx, data)

    command = declare("x.thing.create", kind="command", body=body)

    with pytest.raises(LiveMisuse):
        command(make_ctx(), ThingIn(name="a"))

    assert not OutboxEvent.objects.exists()


@pytest.mark.django_db
def test_record_event_returns_the_saved_event_with_scope_actor_and_payload():
    seen = []

    def body(ctx, data):
        seen.append(record_event(ctx, "x.thing.created", {"name": data.name}))
        seen.append(record_event(ctx, "x.thing.touched"))
        return echo(ctx, data)

    declare("x.thing.create", kind="command", body=body)(make_ctx(actor="u" * 200), ThingIn(name="a"))

    created, touched = seen
    assert isinstance(created, OutboxEvent)
    assert OutboxEvent.objects.get(pk=created.pk).payload == {"name": "a"}
    assert (created.scope_kind, created.scope_key, created.name) == ("hub", "a", "x.thing.created")
    assert created.actor == "u" * 128
    assert touched.payload == {}
    assert created.pk.int < touched.pk.int


# Same transaction as the command; NOTIFY only after its COMMIT


@pytest.mark.django_db(transaction=True)
def test_event_row_is_written_in_the_same_transaction(raw):
    with transaction.atomic():
        thing = create_thing(make_ctx(), ThingIn(name="a"))
        assert OutboxEvent.objects.count() == 1
        assert committed_rows(raw) == []

    assert committed_rows(raw) == [("testapp.thing.created", "hub", "a", "user", {"id": thing.id})]


@pytest.mark.django_db(transaction=True)
def test_notify_arrives_only_after_commit(listen, raw):
    listener = listen()

    with transaction.atomic():
        create_thing(make_ctx(), ThingIn(name="a"))
        assert received(listener, timeout=QUIET) == []

    assert received(listener, stop_after=1) == [(SCOPE.channel, {"events": ["testapp.thing.created"]})]
    # Whoever reacts to the notification already sees the committed row.
    assert [row[0] for row in committed_rows(raw)] == ["testapp.thing.created"]

    create_thing(make_ctx(), ThingIn(name="b"))

    assert received(listener, stop_after=1) == [(SCOPE.channel, {"events": ["testapp.thing.created"]})]


@pytest.mark.django_db(transaction=True)
def test_notify_runs_once_the_row_is_committed_and_outside_any_transaction(monkeypatch, raw):
    # Here the control database is the one the command writes to, where Postgres would hold a
    # NOTIFY sent inside the transaction until the COMMIT anyway; in hub-next phase 2 they differ,
    # so what is checked is when notify runs, not only when the notification arrives.
    seen = []

    def spy(scope, names):
        seen.append((len(committed_rows(raw)), connection.in_atomic_block, names))
        outbox.notify(scope, names)

    monkeypatch.setattr(operations, "notify_hook", spy)

    with transaction.atomic():
        create_thing(make_ctx(), ThingIn(name="a"))
        assert seen == []

    assert seen == [(1, False, ["testapp.thing.created"])]


@pytest.mark.django_db(transaction=True)
def test_a_rolled_back_command_leaves_no_row_and_sends_no_notify(listen, raw):
    listener = listen()

    with pytest.raises(Conflict):
        fail_after_event(make_ctx(), ThingIn(name="rejected"))

    with pytest.raises(RuntimeError), transaction.atomic():
        create_thing(make_ctx(), ThingIn(name="rolled back"))
        raise RuntimeError("boom")

    assert committed_rows(raw) == []
    assert not Thing.objects.exists()
    assert received(listener, timeout=QUIET) == []


@pytest.mark.django_db(transaction=True)
def test_event_names_are_deduplicated_in_one_notify(listen, raw):
    listener = listen()

    create_thing_twice_event(make_ctx(), ThingIn(name="a"))

    assert [row[0] for row in committed_rows(raw)] == ["testapp.thing.created", "testapp.thing.created"]
    assert received(listener) == [(SCOPE.channel, {"events": ["testapp.thing.created"]})]


@pytest.mark.django_db(transaction=True)
def test_notify_sends_sorted_unique_names_in_compact_json(listen):
    listener = listen()

    notify(SCOPE, ["b.thing.updated", "a.thing.created", "b.thing.updated"])

    (note,) = list(listener.notifies(timeout=WAIT))
    assert note.payload == '{"events":["a.thing.created","b.thing.updated"]}'


@pytest.mark.django_db(transaction=True)
def test_oversized_payload_collapses_to_star(listen):
    listener = listen()
    names = [f"app.entity_{index:03d}.{'x' * 80}" for index in range(80)]
    assert len(json.dumps({"events": names}).encode()) > MAX_NOTIFY_BYTES

    notify(SCOPE, names)

    assert received(listener) == [(SCOPE.channel, {"events": ["*"]})]


@pytest.mark.django_db(transaction=True)
def test_a_command_notifies_only_its_own_scope(listen):
    listener_a = listen(SCOPE)
    listener_b = listen(OTHER_SCOPE)

    create_thing(make_ctx(scope=OTHER_SCOPE), ThingIn(name="b"))

    assert received(listener_b, stop_after=1) == [(OTHER_SCOPE.channel, {"events": ["testapp.thing.created"]})]
    assert received(listener_a, timeout=QUIET) == []


# Wiring and configuration


def test_notify_hook_is_wired_by_app_ready(monkeypatch):
    assert operations.notify_hook is outbox.notify

    monkeypatch.setattr(operations, "notify_hook", None)
    apps.get_app_config("live").ready()

    assert operations.notify_hook is outbox.notify


def test_channel_matches_scope_channel():
    long_scope = Scope("user", "k" * 100)

    assert channel_for(SCOPE) == SCOPE.channel == "live_hub_a"
    assert channel_for(long_scope) == long_scope.channel


@pytest.mark.django_db
def test_notify_runs_on_the_control_alias_from_settings():
    with override_settings(LIVE={**settings.LIVE, "control_alias": "control"}):
        with pytest.raises(ConnectionDoesNotExist):
            notify(SCOPE, ["testapp.thing.created"])


@pytest.mark.django_db
def test_notify_inside_a_transaction_warns_because_it_waits_for_that_commit(caplog):
    with caplog.at_level(logging.WARNING, logger="live.outbox"):
        notify(SCOPE, ["testapp.thing.created"])

    assert "inside a transaction" in caplog.text
