"""`manage.py runserver` of `live`: daphne's, plus the Vite dev server with HMR.

With DEBUG and `LIVE["vite"]`, the autoreloader's parent process starts Vite in its own session
and kills its whole process group at exit (SIGTERM, then SIGKILL after 5 s). The reloaded child
never starts another one; `--novite` skips it.
"""

import contextlib
import functools
import os
import shlex
import signal
import socket
import subprocess
import sys
import threading
import time

import pytest
from daphne.management.commands.runserver import Command as DaphneCommand
from django.core.management import CommandError, get_commands, load_command_class
from django.test import modify_settings
from django.utils import autoreload

from live.management.commands import runserver

VITE = {"command": ["pnpm", "--filter", "hub", "dev"], "cwd": "/srv/hub"}


class FakeProcess:
    def __init__(self, pid=4242, exits_on_term=True, returncode=None):
        self.pid = pid
        self.returncode = returncode
        self.exits_on_term = exits_on_term
        self.waits = []

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.waits.append(timeout)
        if self.returncode is None and timeout is not None and not self.exits_on_term:
            raise subprocess.TimeoutExpired("vite", timeout)
        self.returncode = self.returncode if self.returncode is not None else 0
        return self.returncode


class FakeKillpg:
    def __init__(self, process):
        self.process = process
        self.calls = []

    def __call__(self, pgid, sig):
        self.calls.append((pgid, sig))
        if sig == signal.SIGKILL or self.process.exits_on_term:
            self.process.returncode = -sig


class TestStartVite:
    def test_runs_the_command_in_its_own_session(self):
        calls = []

        def popen(*args, **kwargs):
            calls.append((args, kwargs))
            return FakeProcess()

        process = runserver.start_vite(VITE, popen=popen)

        assert isinstance(process, FakeProcess)
        assert calls == [((["pnpm", "--filter", "hub", "dev"],), {"cwd": "/srv/hub", "start_new_session": True})]

    def test_a_command_string_is_split_into_arguments(self):
        calls = []

        runserver.start_vite({"command": "pnpm --filter hub dev"}, popen=lambda *a, **k: calls.append((a, k)))

        assert calls == [((["pnpm", "--filter", "hub", "dev"],), {"cwd": None, "start_new_session": True})]


class TestStopVite:
    def test_sigterm_to_the_process_group_and_wait(self):
        process = FakeProcess()
        killpg = FakeKillpg(process)

        runserver.stop_vite(process, killpg=killpg, timeout=5.0)

        assert killpg.calls == [(4242, signal.SIGTERM)]
        assert process.waits == [5.0]

    def test_sigkill_when_sigterm_times_out(self):
        process = FakeProcess(exits_on_term=False)
        killpg = FakeKillpg(process)

        runserver.stop_vite(process, killpg=killpg, timeout=5.0)

        assert killpg.calls == [(4242, signal.SIGTERM), (4242, signal.SIGKILL)]
        assert process.waits == [5.0, None]

    def test_an_exited_process_is_left_alone(self):
        process = FakeProcess(returncode=0)
        killpg = FakeKillpg(process)

        runserver.stop_vite(process, killpg=killpg)

        assert killpg.calls == []

    def test_a_group_that_vanished_meanwhile_is_not_an_error(self):
        process = FakeProcess()

        def killpg(pgid, sig):
            raise ProcessLookupError

        runserver.stop_vite(process, killpg=killpg)


class RunningVite(FakeProcess):
    """A Vite that keeps running until the test ends, as a healthy one does while runserver serves."""

    def __init__(self, pid):
        super().__init__(pid=pid)
        self.ended = threading.Event()

    def wait(self, timeout=None):
        self.ended.wait()
        return super().wait(timeout)


@pytest.fixture
def spawned(monkeypatch):
    """Record start_vite and atexit registrations instead of spawning anything."""
    record = {"started": [], "atexit": []}
    process = RunningVite(pid=777)

    def fake_start(cfg, **kwargs):
        record["started"].append(cfg)
        return process

    monkeypatch.setattr(runserver, "start_vite", fake_start)
    monkeypatch.setattr(runserver.atexit, "register", lambda fn, *a, **k: record["atexit"].append((fn, a, k)))
    # A watch that fires must not send SIGINT to pytest itself.
    monkeypatch.setattr(runserver, "ViteWatch", functools.partial(runserver.ViteWatch, interrupt=lambda: None))
    monkeypatch.delenv(autoreload.DJANGO_AUTORELOAD_ENV, raising=False)
    record["process"] = process
    yield record
    process.ended.set()


@pytest.fixture
def debug_with_vite(settings):
    settings.DEBUG = True
    settings.LIVE = {**settings.LIVE, "vite": VITE}


@pytest.fixture
def sigint_ignored():
    """SIGINT ignored, as a script's `runserver &` (no job control) starts runserver; pytest gets its handler back."""
    previous = signal.signal(signal.SIGINT, signal.SIG_IGN)
    yield
    signal.signal(signal.SIGINT, previous)


def options(**overrides):
    return {"use_reloader": True, "use_vite": True, **overrides}


class TestWhenViteStarts:
    def test_the_reloader_parent_starts_vite_and_stops_it_at_exit(self, spawned, debug_with_vite, capsys):
        command = runserver.Command()

        process = command.maybe_start_vite(options())

        assert process is spawned["process"]
        assert spawned["started"] == [VITE]
        assert spawned["atexit"] == [(runserver.stop_vite, (process,), {})]
        assert "Vite: pnpm --filter hub dev (pid 777)" in capsys.readouterr().out

    def test_not_in_the_reloaded_child(self, spawned, debug_with_vite, monkeypatch):
        monkeypatch.setenv(autoreload.DJANGO_AUTORELOAD_ENV, "true")

        assert runserver.Command().maybe_start_vite(options()) is None
        assert spawned["started"] == []

    def test_without_the_reloader_the_only_process_starts_it(self, spawned, debug_with_vite, monkeypatch):
        monkeypatch.setenv(autoreload.DJANGO_AUTORELOAD_ENV, "true")

        assert runserver.Command().maybe_start_vite(options(use_reloader=False)) is not None
        assert spawned["started"] == [VITE]

    def test_not_with_novite(self, spawned, debug_with_vite):
        assert runserver.Command().maybe_start_vite(options(use_vite=False)) is None
        assert spawned["started"] == []

    def test_not_without_debug(self, spawned, debug_with_vite, settings):
        settings.DEBUG = False

        assert runserver.Command().maybe_start_vite(options()) is None
        assert spawned["started"] == []

    def test_not_without_a_vite_setting(self, spawned, settings):
        settings.DEBUG = True
        settings.LIVE = {key: value for key, value in settings.LIVE.items() if key != "vite"}

        assert runserver.Command().maybe_start_vite(options()) is None
        assert spawned["started"] == []

    def test_a_command_that_cannot_start_is_a_visible_error(self, debug_with_vite, monkeypatch):
        def missing(cfg, **kwargs):
            raise FileNotFoundError(2, "No such file or directory", "pnpm")

        monkeypatch.setattr(runserver, "start_vite", missing)
        monkeypatch.delenv(autoreload.DJANGO_AUTORELOAD_ENV, raising=False)

        with pytest.raises(CommandError, match="--novite"):
            runserver.Command().maybe_start_vite(options())

    def test_run_starts_vite_before_the_server(self, spawned, debug_with_vite, monkeypatch):
        order = []
        monkeypatch.setattr(DaphneCommand, "run", lambda self, **opts: order.append(("server", spawned["started"][:])))

        runserver.Command().run(**options())

        assert order == [("server", [VITE])]

    @pytest.mark.parametrize(
        ("use_vite", "handler"), [(True, signal.default_int_handler), (False, signal.SIG_IGN)], ids=["vite", "novite"]
    )
    def test_an_ignored_sigint_is_accepted_again_only_to_watch_vite(
        self, spawned, debug_with_vite, sigint_ignored, monkeypatch, use_vite, handler
    ):
        seen = []
        monkeypatch.setattr(DaphneCommand, "run", lambda self, **opts: seen.append(signal.getsignal(signal.SIGINT)))

        runserver.Command().run(**options(use_vite=use_vite))

        assert seen == [handler]


class TestViteWatch:
    def test_vite_exiting_on_its_own_interrupts_the_server(self):
        interrupts = []
        watch = runserver.ViteWatch(FakeProcess(returncode=1), interrupt=lambda: interrupts.append("SIGINT"))

        watch.wait()

        assert watch.exit_code == 1
        assert interrupts == ["SIGINT"]

    def test_vite_stopped_by_the_stopping_server_is_not_an_error(self):
        interrupts = []
        watch = runserver.ViteWatch(FakeProcess(returncode=-15), interrupt=lambda: interrupts.append("SIGINT"))

        watch.stop()
        watch.wait()

        assert watch.exit_code is None
        assert interrupts == []


class TestCommand:
    def test_novite_is_an_option(self):
        parser = runserver.Command().create_parser("manage.py", "runserver")

        assert parser.parse_args([]).use_vite is True
        assert parser.parse_args(["--novite"]).use_vite is False

    def test_it_is_daphnes_runserver(self):
        assert issubclass(runserver.Command, DaphneCommand)

    def test_django_resolves_lives_command(self):
        assert isinstance(load_command_class("live", "runserver"), runserver.Command)

    def test_live_before_daphne_wins(self):
        with modify_settings(INSTALLED_APPS={"append": "daphne"}):
            assert get_commands()["runserver"] == "live"


# The leader of the real process groups below: it sets SIGTERM to ignored (`ignore-term`) or to its default, starts a
# child in its group (which inherits that), prints the child's pid once both are set up, and sleeps. It never exits
# on its own when its child dies, so its exit status is the signal that reached it. A `sh -c "sleep 60 & wait"` leader
# is not: killpg signals the members one at a time, on macOS the child can die before the signal reaches the shell,
# and the shell then leaves its `wait` and exits 0 on its own (live#15: 14 of 20 runs under load).
LEADER = """
import signal, subprocess, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN if sys.argv[1] == "ignore-term" else signal.SIG_DFL)
child = subprocess.Popen(["sleep", "60"])
print(child.pid, flush=True)
time.sleep(60)
"""


def _dies(pid: int, within: float = 5.0) -> bool:
    """Whether ``pid`` is gone or a zombie within ``within`` seconds (an orphan is reaped by init, not by us)."""
    deadline = time.monotonic() + within
    while True:
        state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
        if not state or state.startswith("Z"):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)


@pytest.fixture
def real_group():
    """Start ``LEADER`` the way Vite is started and return it with its child's pid once both are ready."""
    started = []

    def start(sigterm: str) -> tuple[subprocess.Popen, int]:
        process = runserver.start_vite(
            {"command": [sys.executable, "-c", LEADER, sigterm]},
            popen=functools.partial(subprocess.Popen, stdout=subprocess.PIPE, text=True),
        )
        started.append(process)
        return process, int(process.stdout.readline())

    yield start
    for process in started:  # whatever a failed test left alive
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        process.stdout.close()


class TestRealProcessGroup:
    """The same functions against the OS: the whole group dies, not only the leader."""

    def test_sigterm_stops_a_real_process_group(self, real_group):
        process, child = real_group("default-term")

        runserver.stop_vite(process, timeout=5.0)

        assert process.returncode == -signal.SIGTERM
        assert _dies(child)

    def test_sigkill_stops_a_group_that_ignores_sigterm(self, real_group):
        process, child = real_group("ignore-term")

        runserver.stop_vite(process, timeout=0.5)

        assert process.returncode == -signal.SIGKILL
        assert _dies(child)


# What stands in for Vite in the real servers below: `at-once` exits as Vite does when its port is taken, `serving` does
# the same once runserver answers on its port, and `forever` keeps running until runserver stops it.
FAKE_VITE = """
import socket, sys, time
mode, port = sys.argv[1], int(sys.argv[2])
deadline = time.monotonic() + 30
while mode == "serving" and time.monotonic() < deadline:
    try:
        socket.create_connection(("127.0.0.1", port), timeout=1).close()
        break
    except OSError:
        time.sleep(0.05)
if mode == "forever":
    time.sleep(60)
print(f"Error: Port {port + 5} is already in use", file=sys.stderr, flush=True)
sys.exit(1)
"""

SERVER_SETTINGS = """
from tests.settings import *

DEBUG = True
DATABASES = {}
ASGI_APPLICATION = "runserver_settings.application"
LIVE = {**LIVE, "vite": {"command": %r}}


async def application(scope, receive, send):
    pass
"""

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _answers(port: int, within: float = 30.0) -> bool:
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        with contextlib.suppress(OSError):
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            return True
        time.sleep(0.05)
    return False


@pytest.fixture
def real_server(tmp_path):
    """Start ``manage.py runserver`` for real, with ``FAKE_VITE`` as its Vite, in a process group of its own."""
    started = []

    def start(vite_mode: str, *flags: str, ignoring_sigint: bool = False) -> tuple[subprocess.Popen, int, list[str]]:
        port = _free_port()
        (tmp_path / "fake_vite.py").write_text(FAKE_VITE)
        vite = [sys.executable, str(tmp_path / "fake_vite.py"), vite_mode, str(port)]
        (tmp_path / "runserver_settings.py").write_text(SERVER_SETTINGS % (vite,))
        env = {
            **os.environ,
            "DJANGO_SETTINGS_MODULE": "runserver_settings",
            "PYTHONPATH": os.pathsep.join([str(tmp_path), ROOT]),
        }
        env.pop(autoreload.DJANGO_AUTORELOAD_ENV, None)
        process = subprocess.Popen(
            [sys.executable, "-m", "django", "runserver", f"127.0.0.1:{port}", *flags],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
            # A script's `runserver &` (no job control, as the e2e restarts its stack) starts it with SIGINT ignored.
            preexec_fn=functools.partial(signal.signal, signal.SIGINT, signal.SIG_IGN) if ignoring_sigint else None,
        )
        started.append(process)
        return process, port, vite

    yield start
    for process in started:  # whatever a failed test left alive
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.communicate()


class TestViteExits:
    """A Vite that exits while runserver runs (its port taken by another one) stops runserver with a clear error."""

    @pytest.mark.parametrize("ignoring_sigint", [False, True], ids=["terminal", "background"])
    @pytest.mark.parametrize("flags", [(), ("--noreload",)], ids=["reloader", "noreload"])
    @pytest.mark.parametrize("vite_mode", ["at-once", "serving"])
    def test_the_server_stops_and_says_why(self, real_server, vite_mode, flags, ignoring_sigint):
        process, port, vite = real_server(vite_mode, *flags, ignoring_sigint=ignoring_sigint)

        try:
            _, stderr = process.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            pytest.fail("runserver kept running after its Vite exited")

        assert process.returncode == 1
        error = stderr.splitlines()[-1]
        assert error.startswith("CommandError: ")
        assert shlex.join(vite) in error
        assert "code 1" in error
        assert "VITE_DEV_PORT" in error
        assert "--novite" in error
        assert not _answers(port, within=0.5)

    def test_stopping_the_server_is_not_a_vite_error(self, real_server):
        process, port, _ = real_server("forever")
        assert _answers(port)

        os.killpg(process.pid, signal.SIGINT)  # what CONTROL-C does in a terminal
        _, stderr = process.communicate(timeout=30)

        assert process.returncode == 0
        assert "CommandError" not in stderr
        assert "Traceback" not in stderr
