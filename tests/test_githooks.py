"""The versioned git hooks of .githooks/, which a clone switches on with ``git config core.hooksPath .githooks``.

pre-push runs the machine's global pre-push first, with the same arguments and input, and then
``scripts/checks.sh fast`` on every pushed commit, checked out in a temporary worktree with the Python environment of
the checkout that pushes. A red check stops the push. commit-msg, pre-commit and applypatch-msg hand over to the global
hook of their name, which a repository's core.hooksPath would otherwise hide.

Each test pushes from a throwaway repository, with these hooks and a stand-in for the command that records where and
how it ran and exits with the code its commit carries in ``verdict``.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
HOOKS = ("pre-push", "commit-msg", "pre-commit", "applypatch-msg")
ZERO = "0" * 40
STAND_IN = """#!/usr/bin/env bash
printf '%s|%s|%s\\n' "$*" "$PWD" "${UV_PROJECT_ENVIRONMENT:-}" >> "$CHECKS_LOG"
git rev-parse HEAD >> "$CHECKS_LOG.heads"
exit "$(cat verdict)"
"""
RECORDER = """#!/usr/bin/env bash
printf '%s\\n' "$*" > "$GLOBAL_LOG.$(basename "$0").args"
cat > "$GLOBAL_LOG.$(basename "$0").stdin"
exit "$(cat "$GLOBAL_LOG.verdict")"
"""


class Sandbox:
    def __init__(self, root: Path):
        self.root = root
        self.work = root / "work"
        self.remote = root / "remote.git"
        self.global_hooks = root / "global-hooks"
        self.checks_log = root / "checks.log"
        self.global_log = root / "global"
        self.scratch = root / "tmp"
        self.env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("GIT_") and key != "UV_PROJECT_ENVIRONMENT"
        }
        self.env.update(
            HOME=str(root),
            TMPDIR=str(self.scratch),
            GIT_CONFIG_GLOBAL=str(root / "gitconfig"),
            GIT_CONFIG_NOSYSTEM="1",
            GIT_AUTHOR_NAME="t",
            GIT_AUTHOR_EMAIL="t@example.com",
            GIT_COMMITTER_NAME="t",
            GIT_COMMITTER_EMAIL="t@example.com",
            CHECKS_LOG=str(self.checks_log),
            GLOBAL_LOG=str(self.global_log),
        )

    def run(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            list(args),
            cwd=cwd or self.work,
            env=self.env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=120,
        )

    def git(self, *args: str) -> str:
        done = self.run("git", *args)
        assert done.returncode == 0, done.stderr
        return done.stdout.strip()

    def commit(self, verdict: int, command: bool = True) -> str:
        (self.work / "verdict").write_text(f"{verdict}\n", encoding="utf-8")
        script = self.work / "scripts" / "checks.sh"
        if command:
            script.parent.mkdir(exist_ok=True)
            script.write_text(STAND_IN, encoding="utf-8")
            script.chmod(0o755)
        else:
            script.unlink(missing_ok=True)
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", f"verdict {verdict}")
        return self.git("rev-parse", "HEAD")

    def push(self, *args: str) -> subprocess.CompletedProcess[str]:
        return self.run("git", "push", "origin", *args)

    def remote_tip(self, branch: str) -> str | None:
        done = self.run("git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", cwd=self.remote)
        return done.stdout.strip() or None

    def checks(self) -> list[list[str]]:
        if not self.checks_log.exists():
            return []
        return [line.split("|") for line in self.checks_log.read_text(encoding="utf-8").splitlines()]

    def checked_heads(self) -> list[str]:
        return Path(f"{self.checks_log}.heads").read_text(encoding="utf-8").split()

    def use_global_hooks(self, path: Path, verdict: int = 0) -> None:
        self.global_log.with_suffix(".verdict").write_text(f"{verdict}\n", encoding="utf-8")
        self.git("config", "--global", "core.hooksPath", str(path))

    def global_record(self, hook: str) -> tuple[str, str]:
        return (
            Path(f"{self.global_log}.{hook}.args").read_text(encoding="utf-8"),
            Path(f"{self.global_log}.{hook}.stdin").read_text(encoding="utf-8"),
        )


@pytest.fixture
def sandbox(tmp_path):
    box = Sandbox(tmp_path)
    box.scratch.mkdir()
    box.global_hooks.mkdir()
    for hook in HOOKS:
        recorder = box.global_hooks / hook
        recorder.write_text(RECORDER, encoding="utf-8")
        recorder.chmod(0o755)
    box.run("git", "init", "-q", "--bare", str(box.remote), cwd=tmp_path)
    box.run("git", "init", "-q", "-b", "main", str(box.work), cwd=tmp_path)
    hooks = box.work / ".githooks"
    hooks.mkdir()
    for hook in HOOKS:
        if (REPO / ".githooks" / hook).is_file():
            shutil.copy2(REPO / ".githooks" / hook, hooks / hook)
    (box.work / ".venv").mkdir()
    (box.work / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    box.git("config", "core.hooksPath", ".githooks")
    box.git("config", "commit.gpgsign", "false")
    box.git("remote", "add", "origin", str(box.remote))
    return box


def test_every_hook_is_versioned_and_executable():
    for hook in HOOKS:
        path = REPO / ".githooks" / hook
        assert path.is_file(), f".githooks/{hook} is missing"
        assert os.access(path, os.X_OK), f".githooks/{hook} is not executable"


def test_a_red_check_stops_the_push_and_a_green_one_lets_it_go(sandbox):
    sandbox.commit(verdict=1)
    refused = sandbox.push("main")
    assert refused.returncode != 0
    assert "scripts/checks.sh fast" in refused.stderr
    assert sandbox.remote_tip("main") is None

    head = sandbox.commit(verdict=0)
    accepted = sandbox.push("main")
    assert accepted.returncode == 0, accepted.stderr
    assert sandbox.remote_tip("main") == head
    assert [args for args, _, _ in sandbox.checks()] == ["fast", "fast"]


def test_the_checks_run_on_the_pushed_commit_and_never_on_the_working_tree(sandbox):
    sandbox.commit(verdict=1)
    (sandbox.work / "verdict").write_text("0\n", encoding="utf-8")
    assert sandbox.push("main").returncode != 0

    head = sandbox.commit(verdict=0)
    (sandbox.work / "verdict").write_text("1\n", encoding="utf-8")
    assert sandbox.push("main").returncode == 0
    assert sandbox.remote_tip("main") == head

    places = {Path(where) for _, where, _ in sandbox.checks()}
    assert sandbox.work not in places
    assert all(place.is_relative_to(sandbox.scratch) for place in places)
    assert list(sandbox.scratch.iterdir()) == []
    assert sandbox.git("worktree", "list", "--porcelain").count("worktree ") == 1


def test_git_inside_the_checks_reads_the_pushed_commit_even_when_the_push_names_its_repository(sandbox):
    pushed = sandbox.commit(verdict=0)
    sandbox.commit(verdict=0)
    sandbox.env["GIT_DIR"] = str(sandbox.work / ".git")
    assert sandbox.push(f"{pushed}:refs/heads/a").returncode == 0
    assert sandbox.checked_heads() == [pushed]


@pytest.mark.parametrize("chosen, folder", [(None, ".venv"), ("elsewhere", "elsewhere")])
def test_the_checks_use_the_python_environment_of_the_checkout_that_pushes(sandbox, chosen, folder):
    if chosen:
        sandbox.env["UV_PROJECT_ENVIRONMENT"] = chosen
        (sandbox.work / folder).mkdir()
    sandbox.commit(verdict=0)
    assert sandbox.push("main").returncode == 0
    assert [Path(environment) for _, _, environment in sandbox.checks()] == [sandbox.work / folder]


def test_without_that_environment_the_push_stops_and_none_is_created(sandbox):
    sandbox.commit(verdict=0)
    (sandbox.work / ".venv").rmdir()
    refused = sandbox.push("main")
    assert refused.returncode != 0
    assert "uv sync" in refused.stderr
    assert not (sandbox.work / ".venv").exists()
    assert sandbox.checks() == []


def test_a_pushed_commit_without_the_command_stops_the_push(sandbox):
    sandbox.commit(verdict=0, command=False)
    refused = sandbox.push("main")
    assert refused.returncode != 0
    assert "scripts/checks.sh" in refused.stderr
    assert "origin/main" in refused.stderr
    assert sandbox.remote_tip("main") is None


def test_the_global_pre_push_runs_first_with_the_same_arguments_and_input(sandbox):
    sandbox.use_global_hooks(sandbox.global_hooks)
    head = sandbox.commit(verdict=0)
    assert sandbox.push("main").returncode == 0
    args, stdin = sandbox.global_record("pre-push")
    assert args == f"origin {sandbox.remote}\n"
    assert stdin == f"refs/heads/main {head} refs/heads/main {ZERO}\n"
    assert len(sandbox.checks()) == 1


def test_a_refusal_of_the_global_pre_push_stops_the_push_before_any_check(sandbox):
    sandbox.commit(verdict=0)
    sandbox.use_global_hooks(sandbox.global_hooks, verdict=1)
    assert sandbox.push("main").returncode != 0
    assert sandbox.remote_tip("main") is None
    assert sandbox.checks() == []


def test_a_global_hooks_path_that_is_this_folder_runs_the_checks_once(sandbox):
    sandbox.use_global_hooks(sandbox.work / ".githooks")
    sandbox.commit(verdict=0)
    assert sandbox.push("main").returncode == 0
    assert len(sandbox.checks()) == 1


def test_deleting_a_branch_checks_nothing(sandbox):
    sandbox.commit(verdict=0)
    assert sandbox.push("main", "main:gone").returncode == 0
    sandbox.commit(verdict=1)
    before = len(sandbox.checks())
    deleted = sandbox.push("--delete", "gone")
    assert deleted.returncode == 0, deleted.stderr
    assert sandbox.remote_tip("gone") is None
    assert len(sandbox.checks()) == before


def test_each_pushed_commit_is_checked_once_and_a_red_one_stops_the_whole_push(sandbox):
    first = sandbox.commit(verdict=0)
    second = sandbox.commit(verdict=0)
    assert sandbox.push(f"{first}:refs/heads/a", f"{second}:refs/heads/b", f"{first}:refs/heads/c").returncode == 0
    assert len(sandbox.checks()) == 2

    sandbox.commit(verdict=1)
    assert sandbox.push("main", f"{second}:refs/heads/d").returncode != 0
    assert sandbox.remote_tip("main") is None
    assert sandbox.remote_tip("d") is None


@pytest.mark.parametrize("hook", ["commit-msg", "pre-commit", "applypatch-msg"])
def test_the_other_hooks_hand_over_to_the_global_hook_of_their_name(sandbox, hook):
    sandbox.use_global_hooks(sandbox.global_hooks, verdict=3)
    done = sandbox.run(str(sandbox.work / ".githooks" / hook), "MSG_FILE")
    assert done.returncode == 3
    assert sandbox.global_record(hook)[0] == "MSG_FILE\n"


@pytest.mark.parametrize("hook", ["commit-msg", "pre-commit", "applypatch-msg"])
def test_without_a_global_hook_the_other_hooks_let_git_go_on(sandbox, hook):
    assert sandbox.run(str(sandbox.work / ".githooks" / hook), "MSG_FILE").returncode == 0


def test_a_refusal_of_the_global_commit_msg_stops_the_commit(sandbox, tmp_path):
    only_commit_msg = tmp_path / "only-commit-msg"
    only_commit_msg.mkdir()
    (only_commit_msg / "commit-msg").write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
    (only_commit_msg / "commit-msg").chmod(0o755)
    sandbox.git("config", "--global", "core.hooksPath", str(only_commit_msg))
    (sandbox.work / "note").write_text("x\n", encoding="utf-8")
    sandbox.git("add", "note")
    assert sandbox.run("git", "commit", "-q", "-m", "note").returncode != 0
