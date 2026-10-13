"""The live package registers its own AppConfig, wires the outbox and discovers the operations."""

import json
import os
import subprocess
import sys
from pathlib import Path

from django.apps import apps
from live import operations, outbox
from live.operations import registry

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
TESTAPP_OPERATIONS = {
    "testapp.thing.list",
    "testapp.thing.get",
    "testapp.thing.sneaky_write",
    "testapp.thing.create",
    "testapp.thing.create_twice_event",
    "testapp.thing.fail_after_event",
}
# Run in a fresh interpreter: in this one the test modules have already imported the testapp.
FRESH_SETUP = """
import json, sys
import django
django.setup()
from django.core.checks.registry import registry
from live import operations, outbox
print(json.dumps({
    "operations": sorted(operations.registry),
    "modules": sorted(name for name in sys.modules if name.startswith("tests.testapp.")),
    "hook_wired": operations.notify_hook is outbox.notify,
    "check_tags": sorted(registry.tags_available()),
    "checks": sorted(f"{check.__module__}.{check.__name__}" for check in registry.get_checks()),
}))
"""


def fresh_setup() -> dict:
    result = subprocess.run(
        [sys.executable, "-c", FRESH_SETUP],
        cwd=PACKAGE_ROOT,
        env={**os.environ, "DJANGO_SETTINGS_MODULE": "tests.settings"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_live_app_config_is_registered_with_label_live():
    config = apps.get_app_config("live")

    assert type(config).__name__ == "LiveConfig"
    assert type(config).__module__ == "live.apps"
    assert config.name == "live"
    assert config.label == "live"


def test_django_setup_discovers_the_queries_and_services_of_installed_apps():
    state = fresh_setup()

    assert TESTAPP_OPERATIONS <= set(state["operations"])
    assert {"tests.testapp.queries", "tests.testapp.services"} <= set(state["modules"])


def test_django_setup_wires_the_outbox_as_notify_hook():
    assert fresh_setup()["hook_wired"] is True


def test_django_setup_registers_the_app_metadata_checks():
    state = fresh_setup()

    assert "live" in state["check_tags"]
    assert "live.checks.check_app_metadata" in state["checks"]


def test_ready_can_run_again_without_registering_twice(monkeypatch):
    before = dict(registry)
    monkeypatch.setattr(operations, "notify_hook", None)

    apps.get_app_config("live").ready()
    apps.get_app_config("live").ready()

    assert registry == before
    assert operations.notify_hook is outbox.notify
