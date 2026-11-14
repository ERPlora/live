"""The suite's settings plus an app whose services and queries are packages (tests/test_apps.py, in a fresh interpreter)."""

from tests.settings import *

INSTALLED_APPS = [*INSTALLED_APPS, "tests.packagedoors"]
