"""``manage.py runserver``: daphne's ASGI server plus the Vite dev server with HMR (plan §4.6).

``live`` goes before ``daphne`` in ``INSTALLED_APPS`` so this command wins. With DEBUG and
``LIVE["vite"] = {"command": [...], "cwd": ...}``, the autoreloader's parent process (the one that
lives as long as the terminal session) starts Vite in its own session, so a Python reload never
restarts it, and kills its whole process group at exit: SIGTERM, then SIGKILL after 5 s.
``--novite`` skips it.
"""

from __future__ import annotations

import atexit
import os
import shlex
import signal
import subprocess
from typing import Any

from daphne.management.commands.runserver import Command as DaphneRunserverCommand
from django.conf import settings
from django.core.management import CommandError
from django.utils import autoreload


def _argv(cfg: dict[str, Any]) -> list[str]:
    command = cfg["command"]
    return shlex.split(command) if isinstance(command, str) else list(command)


def start_vite(cfg: dict[str, Any], *, popen=subprocess.Popen) -> subprocess.Popen:
    """Start ``cfg["command"]`` in ``cfg["cwd"]`` as the leader of a new process group."""
    return popen(_argv(cfg), cwd=cfg.get("cwd"), start_new_session=True)


def stop_vite(proc: subprocess.Popen, *, killpg=os.killpg, timeout: float = 5.0) -> None:
    """SIGTERM Vite's process group, then SIGKILL if it is still alive after ``timeout`` seconds."""
    if proc.poll() is not None:
        return
    # With start_new_session the group id is the leader's pid.
    try:
        killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            killpg(proc.pid, signal.SIGKILL)
            proc.wait()
    except ProcessLookupError:
        pass


class Command(DaphneRunserverCommand):
    help = "Start the ASGI development server and, with DEBUG, the Vite dev server (HMR)."

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--novite",
            action="store_false",
            dest="use_vite",
            help="Do not start the Vite dev server.",
        )

    def run(self, **options):
        self.maybe_start_vite(options)
        super().run(**options)

    def maybe_start_vite(self, options: dict[str, Any]) -> subprocess.Popen | None:
        """Start Vite when DEBUG, ``LIVE["vite"]`` and no ``--novite``, in the reloader's parent only."""
        cfg = getattr(settings, "LIVE", {}).get("vite")
        if not (settings.DEBUG and cfg and options.get("use_vite", True)):
            return None
        in_reloaded_child = os.environ.get(autoreload.DJANGO_AUTORELOAD_ENV) == "true"
        if options.get("use_reloader", True) and in_reloaded_child:
            return None
        command = shlex.join(_argv(cfg))
        try:
            process = start_vite(cfg)
        except OSError as exc:
            raise CommandError(f"Vite: cannot start `{command}` ({exc}); run with --novite to skip it.") from exc
        atexit.register(stop_vite, process)
        self.stdout.write(f"Vite: {command} (pid {process.pid})")
        return process
