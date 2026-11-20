"""``manage.py runserver``: daphne's ASGI server plus the Vite dev server with HMR.

``live`` goes before ``daphne`` in ``INSTALLED_APPS`` so this command wins. With DEBUG and
``LIVE["vite"] = {"command": [...], "cwd": ...}``, the autoreloader's parent process (the one that
lives as long as the terminal session) starts Vite in its own session, so a Python reload never
restarts it, and kills its whole process group at exit: SIGTERM, then SIGKILL after 5 s.
If Vite exits on its own while the server runs (another Vite holds its port, or it crashed), the
server stops too and says so, rather than serve pages whose code comes from whatever answers on that
port. ``--novite`` skips it.
"""

from __future__ import annotations

import atexit
import os
import shlex
import signal
import subprocess
import threading
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


def _accept_sigint() -> None:
    """Let ``_interrupt_main`` reach the server: a script's ``runserver &`` (no job control) starts it ignored."""
    if signal.getsignal(signal.SIGINT) == signal.SIG_IGN:
        signal.signal(signal.SIGINT, signal.default_int_handler)


def _interrupt_main() -> None:
    """Stop the server as CONTROL-C does, waking the main thread even while it waits for the reloaded child."""
    signal.pthread_kill(threading.main_thread().ident, signal.SIGINT)


class ViteWatch:
    """Interrupt the server when its Vite exits, unless the server is already stopping."""

    def __init__(self, process: subprocess.Popen, *, interrupt=_interrupt_main):
        self.process = process
        self.exit_code: int | None = None
        self._interrupt = interrupt
        self._stopping = threading.Event()
        self._thread = threading.Thread(target=self.wait, name="vite-watch", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        """From now on Vite exits because the server stops it."""
        self._stopping.set()

    def wait(self) -> None:
        """Block until Vite exits; interrupt the server if it was not stopping already."""
        code = self.process.wait()
        if not self._stopping.is_set():
            self.exit_code = code
            self._interrupt()

    def error(self) -> CommandError:
        return CommandError(
            f"Vite: `{shlex.join(self.process.args)}` exited with code {self.exit_code}, so the server stopped; "
            "if another Vite holds its port, set another VITE_DEV_PORT, or run with --novite."
        )


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
        vite = self.maybe_start_vite(options)
        if vite is None:
            super().run(**options)
            return
        _accept_sigint()
        watch = ViteWatch(vite)
        try:
            watch.start()
            super().run(**options)
        except KeyboardInterrupt:
            if watch.exit_code is None:
                raise
        finally:
            watch.stop()
        if watch.exit_code is not None:
            raise watch.error()

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
