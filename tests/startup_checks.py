"""The system checks a fresh Django process registers on its own, for the tests that a startup imports a check module."""

import os
import subprocess
import sys
from pathlib import Path

SCRIPT = (
    "import django; django.setup()\n"
    "from django.core.checks.registry import registry\n"
    "print(sorted(f'{check.__module__}.{check.__name__}' for check in registry.get_checks()))"
)


def checks_registered_at_startup() -> str:
    """The ``module.function`` of every check registered by ``django.setup()`` in a process where no test imported
    anything first."""
    result = subprocess.run(
        [sys.executable, "-c", SCRIPT],
        cwd=Path(__file__).resolve().parent.parent,
        env={**os.environ, "DJANGO_SETTINGS_MODULE": "tests.settings"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout
