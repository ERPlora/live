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


# --- Its section in the admin's index speaks the staff's language -------------------------------------------------


def names_shown_in_the_admin():
    """The section of the app and the names of each of its models, as the admin's index shows them."""
    from django.apps import apps

    config = apps.get_app_config("live")
    names = {"app": config.verbose_name}
    for model in config.get_models():
        names[f"{model.__name__} (one)"] = model._meta.verbose_name
        names[f"{model.__name__} (many)"] = model._meta.verbose_name_plural
    return names


def test_the_section_and_its_models_have_names_a_catalog_translates():
    """A name in plain text, or taken from the class, stays in English in every language (the index of erplora.com's
    admin showed «Live › Outbox events» in Spanish)."""
    from django.utils.functional import Promise

    assert [where for where, name in names_shown_in_the_admin().items() if not isinstance(name, Promise)] == []


def test_every_name_of_the_section_has_its_spanish():
    from django.utils import translation

    names = names_shown_in_the_admin()
    with translation.override("en"):
        english = {where: str(name) for where, name in names.items()}
    with translation.override("es"):
        spanish = {where: str(name) for where, name in names.items()}

    assert [where for where in names if spanish[where] == english[where]] == []
