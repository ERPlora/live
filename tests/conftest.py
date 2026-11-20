"""Shared fixtures for the erplora-live test suite."""

import pytest
from django.db import connections
from live.executor import Executor
from psycopg.conninfo import make_conninfo

# An app that tests/test_apps.py loads in a fresh interpreter; its test-named modules are fixtures, not tests.
collect_ignore = ["packagedoors"]


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


@pytest.fixture
def make_executor():
    created = []

    def make(**options):
        options.setdefault("debounce", 0.05)
        executor = Executor(**options)
        created.append(executor)
        return executor

    yield make
    for executor in created:
        executor.reset()
        executor.shutdown()
