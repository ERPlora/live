"""The test settings run against Postgres and install the live app."""

import json
import os
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest
from django.conf import settings
from django.db import connection

from tests.testapp.models import Thing

ROOT = Path(__file__).resolve().parent.parent


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


def _test_database_names(environment):
    """The test database name of every alias of tests/settings.py, loaded fresh under ``environment``."""
    probe = (
        "import json, tests.settings as s; "
        "print(json.dumps({alias: db.get('TEST', {}).get('NAME') for alias, db in s.DATABASES.items()}))"
    )
    base = {key: value for key, value in os.environ.items() if key != "TEST_DB_NAME"}
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=ROOT, env=base | environment, capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize(
    ("environment", "expected"),
    [({}, None), ({"TEST_DB_NAME": "test_live_session"}, "test_live_session")],
)
def test_test_database_name_comes_from_the_environment(environment, expected):
    """Two runs of the suite at once (another session, the pre-push hook) each set their own TEST_DB_NAME, so
    neither drops the other's test database. Unset, Django's default stays (test_ + NAME). Both aliases get the
    same name: they are one test database."""
    assert _test_database_names(environment) == {"default": expected, "other": expected}
