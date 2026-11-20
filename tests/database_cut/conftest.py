"""The project of the database cut tests, set up around each of them."""

import pytest
from django.db import connections
from django.test import Client
from live.operations import registry

from tests.database_cut.cutting import admin_dsn, set_read_only
from tests.database_cut.project import MIDDLEWARE, OPERATIONS, WAIT_SECONDS, runs, script


@pytest.fixture(autouse=True)
def project(settings, transactional_db, db_dsn):
    settings.ROOT_URLCONF = "tests.database_cut.project"
    settings.MIDDLEWARE = MIDDLEWARE
    settings.LIVE = {
        **settings.LIVE,
        "context_builder": "tests.database_cut.project.ProbeBuilder",
        "database_cut": {"wait_seconds": WAIT_SECONDS, "no_wait_prefixes": ("/internal/",)},
    }
    admin_dsn[:] = [db_dsn]
    runs.clear()
    script.clear()
    for op in OPERATIONS:
        registry[op.name] = op
    yield
    for op in OPERATIONS:
        registry.pop(op.name, None)
    set_read_only(False)
    # A connection this test cut must not reach the flush between tests.
    connections.close_all()


@pytest.fixture
def client():
    return Client(raise_request_exception=False)
