"""The test settings run against Postgres and install the live app."""

import psycopg
import pytest
from django.conf import settings
from django.db import connection

from tests.testapp.models import Thing


def test_default_database_uses_postgresql():
    assert settings.DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql"


def test_live_app_is_installed():
    assert "live" in settings.INSTALLED_APPS


@pytest.mark.django_db
def test_test_database_is_migrated():
    Thing.objects.create(name="first")

    assert Thing.objects.filter(name="first").count() == 1


@pytest.mark.django_db
def test_db_dsn_connects_to_the_test_database(db_dsn):
    with psycopg.connect(db_dsn, autocommit=True) as raw:
        (current,) = raw.execute("SELECT current_database()").fetchone()

    assert current == connection.settings_dict["NAME"]
    assert current.startswith("test_")
