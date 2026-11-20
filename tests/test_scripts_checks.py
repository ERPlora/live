"""``scripts/checks.sh fast``: what a change passes before it is pushed (.githooks/pre-push runs it on the pushed commit).

It runs the tests of the size of each file and of the function limits, ruff's and complexipy's, the lists that only
shrink included, in seconds, without the network or a database. A tree that breaks any of them fails the command, and
its output names the file and the reason.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_function_limits import KNOTTY

REPO = Path(__file__).resolve().parent.parent
COMMAND = "scripts/checks.sh"
BREAKS = {
    "live/filler.py": "".join(f"# filler {line}\n" for line in range(501)),
    "live/wide.py": "def wide(a, b, c, d, e, f):\n    return a\n",
    "live/knotty.py": KNOTTY,
}
REPORTS = {
    "size": "live/filler.py has 501 lines, over its cap of 500",
    "ruff": "live/wide.py:1:5: PLR0913",
    "complexity": "live/knotty.py::knotty scores 16, over 15",
}


def checks(tree: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """The command as the hook runs it: the suite's own pytest settings do not leak into it, and no database is up."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("PYTEST_")}
    env.update(UV_PROJECT_ENVIRONMENT=sys.prefix, DB_HOST="127.0.0.1", DB_PORT="1")
    return subprocess.run(
        ["bash", COMMAND, *args], cwd=tree, env=env, capture_output=True, text=True, timeout=600, check=False
    )


@pytest.fixture
def head_tree(tmp_path):
    """HEAD checked out on its own, with this checkout's command, so that what a test adds stays out of the suite."""
    tree = tmp_path / "tree"
    subprocess.run(["git", "worktree", "add", "--quiet", "--detach", str(tree), "HEAD"], cwd=REPO, check=True)
    if (REPO / COMMAND).is_file():
        shutil.copy2(REPO / COMMAND, tree / COMMAND)
    yield tree
    subprocess.run(["git", "worktree", "remove", "--force", str(tree)], cwd=REPO, check=True)


def test_fast_passes_on_this_tree():
    done = checks(REPO, "fast")
    assert done.returncode == 0, done.stdout[-4000:] + done.stderr[-2000:]


def test_fast_fails_naming_the_file_and_the_reason_of_every_check(head_tree):
    for path, text in BREAKS.items():
        (head_tree / path).write_text(text, encoding="utf-8")
    # The size test measures the tracked files, which is what a push uploads.
    subprocess.run(["git", "add", *BREAKS], cwd=head_tree, check=True)
    done = checks(head_tree, "fast")
    assert done.returncode == 1, done.stdout[-4000:] + done.stderr[-2000:]
    missing = [check for check, report in REPORTS.items() if report not in done.stdout]
    assert missing == [], done.stdout[-8000:]


@pytest.mark.parametrize("args", [(), ("slow",)])
def test_an_unknown_mode_says_which_ones_there_are(args):
    done = checks(REPO, *args)
    assert done.returncode == 2
    assert "fast" in done.stderr
