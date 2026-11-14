"""Every function keeps to the limits of complexity, statements, branches, returns and arguments (ruff).

The functions over them today carry a ``# noqa: <rule>``; RUF100 fails the one that is no longer needed, so the list of
exceptions only shrinks. The argument limits do not apply to the tests: pytest fixtures are arguments.
"""

import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEST_FILES = ("tests/**", "**/test_*.py", "**/conftest.py")


def test_ruff_checks_the_function_limits_and_nothing_else():
    ruff = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["ruff"]
    lint = ruff["lint"]

    assert lint["select"] == ["C901", "PLR0911", "PLR0912", "PLR0913", "PLR0915", "PLR0917", "RUF100"]
    assert lint["mccabe"] == {"max-complexity": 10}
    assert lint["pylint"] == {
        "max-args": 5,
        "max-positional-args": 5,
        "max-branches": 12,
        "max-returns": 6,
        "max-statements": 50,
    }
    assert lint["per-file-ignores"] == dict.fromkeys(TEST_FILES, ["PLR0913", "PLR0917"])
    assert ruff["format"] == {"exclude": ["*"]}


def test_no_function_passes_the_limits():
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--no-cache", "--output-format", "concise", "."],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
