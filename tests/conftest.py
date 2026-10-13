"""Shared fixtures for the erplora-live test suite."""

import pytest
from django.db import connections
from psycopg.conninfo import make_conninfo


@pytest.fixture
def db_dsn(django_db_setup):
    """DSN of the test database, for raw psycopg connections (e.g. a LISTEN session)."""
    params = connections["default"].settings_dict
    return make_conninfo(
        dbname=params["NAME"],
        user=params["USER"],
        password=params["PASSWORD"],
        host=params["HOST"],
        port=params["PORT"],
    )
