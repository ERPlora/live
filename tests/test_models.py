"""Models of the live package: UUIDv7 keys and the outbox event."""

import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import models
from live.models import OutboxEvent, UUIDModel


def make_event(**overrides):
    fields = {"scope_kind": "hub", "scope_key": "a", "name": "testapp.thing.created"}
    return OutboxEvent(**{**fields, **overrides})


def test_uuid_model_is_abstract_with_a_uuid_primary_key():
    assert UUIDModel._meta.abstract
    pk = OutboxEvent._meta.pk

    assert isinstance(pk, models.UUIDField)
    assert pk.name == "id"
    assert pk.default is uuid.uuid7
    assert not pk.editable


def test_primary_key_is_a_uuid7():
    assert make_event().pk.version == 7


@pytest.mark.django_db
def test_primary_keys_of_rows_created_in_sequence_are_time_ordered():
    first = make_event()
    first.save()
    second = make_event()
    second.save()

    assert first.pk.int < second.pk.int
    assert list(OutboxEvent.objects.values_list("pk", flat=True)) == [first.pk, second.pk]


@pytest.mark.django_db  # full_clean also checks the primary key is unique
@pytest.mark.parametrize("name", ["bad.name", "testapp.thing.created.extra", "Testapp.thing.created", "testapp..created"])
def test_full_clean_rejects_a_name_that_is_not_app_entity_fact(name):
    with pytest.raises(ValidationError) as info:
        make_event(name=name).full_clean()

    assert "name" in info.value.message_dict


@pytest.mark.django_db
def test_full_clean_accepts_a_three_part_name():
    make_event(name="testapp.thing.line_added").full_clean()


@pytest.mark.django_db
def test_payload_and_actor_are_optional():
    event = make_event()

    event.full_clean()
    assert event.payload == {}
    assert event.actor == ""
    assert event.delivered_at is None
    assert event.created_at is not None


@pytest.mark.django_db
def test_payload_accepts_uuids_and_decimals():
    key = uuid.uuid7()
    make_event(payload={"id": key, "total": Decimal("12.50")}).save()

    assert OutboxEvent.objects.get().payload == {"id": str(key), "total": "12.50"}


def test_meta_declares_the_scope_index_and_ordering():
    meta = OutboxEvent._meta

    assert [index.fields for index in meta.indexes] == [["scope_kind", "scope_key", "created_at"]]
    assert meta.ordering == ["created_at", "id"]
    assert meta.db_table == "live_outboxevent"
