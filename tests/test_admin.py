"""The outbox is visible in the Django admin, read-only: events are only written by commands.

The suite does not install ``django.contrib.admin`` (its catalogs and system checks would leak into
other tests), so each test turns it on with ``override_settings``: its ``ready()`` autodiscovers
``live.admin`` exactly as hub-next and saas-next do.
"""

import pytest
from django.conf import settings
from django.test import override_settings
from live.models import OutboxEvent


@pytest.fixture
def model_admin():
    with override_settings(INSTALLED_APPS=[*settings.INSTALLED_APPS, "django.contrib.admin"]):
        from django.contrib import admin

        yield admin.site.get_model_admin(OutboxEvent)


@pytest.fixture
def superuser_request(rf, admin_user):
    request = rf.get("/admin/live/outboxevent/")
    request.user = admin_user
    return request


@pytest.fixture
def event(db):
    return OutboxEvent.objects.create(scope_kind="hub", scope_key="a", name="testapp.thing.created")


def test_outbox_event_is_registered_with_its_admin(model_admin):
    from live.admin import OutboxEventAdmin

    assert isinstance(model_admin, OutboxEventAdmin)


def test_every_field_is_read_only(model_admin, superuser_request, event):
    every_field = {field.name for field in OutboxEvent._meta.fields}

    assert set(model_admin.get_readonly_fields(superuser_request)) == every_field
    assert set(model_admin.get_readonly_fields(superuser_request, event)) == every_field


def test_not_even_a_superuser_adds_changes_or_deletes_an_event(model_admin, superuser_request, event):
    assert model_admin.has_view_permission(superuser_request, event)
    assert not model_admin.has_add_permission(superuser_request)
    assert not model_admin.has_change_permission(superuser_request, event)
    assert not model_admin.has_delete_permission(superuser_request, event)
