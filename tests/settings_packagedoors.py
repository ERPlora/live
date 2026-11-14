"""The suite's settings plus an app whose services and queries are packages (tests/test_apps.py, in a fresh interpreter)."""

from tests.settings import *  # noqa: F403

INSTALLED_APPS = [*INSTALLED_APPS, "tests.packagedoors"]  # noqa: F405
