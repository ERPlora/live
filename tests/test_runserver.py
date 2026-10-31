"""`manage.py runserver` of `live`: daphne's, plus the Vite dev server with HMR (plan §4.6).

With DEBUG and `LIVE["vite"]`, the autoreloader's parent process starts Vite in its own session
and kills its whole process group at exit (SIGTERM, then SIGKILL after 5 s). The reloaded child
never starts another one; `--novite` skips it.
"""

import contextlib
import functools
import os
import signal
import subprocess
import sys
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


@pytest.fixture
def spawned(monkeypatch):
    """Record start_vite and atexit registrations instead of spawning anything."""
    record = {"started": [], "atexit": []}
    process = FakeProcess(pid=777)

    def fake_start(cfg, **kwargs):
        record["started"].append(cfg)
        return process

    monkeypatch.setattr(runserver, "start_vite", fake_start)
    monkeypatch.setattr(runserver.atexit, "register", lambda fn, *a, **k: record["atexit"].append((fn, a, k)))
    monkeypatch.delenv(autoreload.DJANGO_AUTORELOAD_ENV, raising=False)
    record["process"] = process
    return record


@pytest.fixture
def debug_with_vite(settings):
    settings.DEBUG = True
    settings.LIVE = {**settings.LIVE, "vite": VITE}


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
