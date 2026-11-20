"""Every function keeps to the limits of complexity, statements, branches, returns and arguments (ruff), and to a
cognitive complexity of 15 (complexipy).

The functions over ruff's limits today carry a ``# noqa: <rule>``; RUF100 fails the one that is no longer needed, so the
list of exceptions only shrinks. The argument limits do not apply to the tests: pytest fixtures are arguments.

complexipy scores Sonar's cognitive complexity: each branch, loop or jump adds one, plus one for every level it is
nested in, which the cyclomatic complexity of C901 does not weigh. The functions over 15 when it came in are frozen in
complexipy-snapshot.json, complexipy's own baseline, with their scores. A function over 15 without an entry, or over
its entry, fails; so does an entry above its function's score, or whose function is gone, until a plain
``uv run complexipy`` lowers or removes it. Against origin/main the snapshot gains no entry and no entry scores more.
An entry is matched by its function's name, whatever its file, so it follows a function moved to another module. No
ignore comment switches the limit off, and the migrations, which are generated, are not read.
"""

import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TEST_FILES = ("tests/**", "**/test_*.py", "**/conftest.py")
SNAPSHOT = "complexipy-snapshot.json"
BASELINE = "origin/main"
COGNITIVE_LIMIT = 15
COMPLEXIPY_CONFIGURATION = {
    "paths": ["."],
    "exclude": ["**/migrations/**"],
    "max-complexity-allowed": COGNITIVE_LIMIT,
    "no-ignore": True,
}
# Five nested ifs score 1 + 2 + 3 + 4 + 5 = 15, and the last one at the top makes it 16: C901 counts 7 and lets it by.
KNOTTY = """def knotty(a, b, c, d, e):  # complexipy: ignore
    if a:
        if b:
            if c:
                if d:
                    if e:
                        return 1
    if e:
        return 2
    return 0
"""
FLAT = KNOTTY.replace("knotty", "flat").replace("    if e:\n        return 2\n", "")

Key = tuple[str, str]


def complexipy(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    script = Path(sys.executable).with_name("complexipy")
    return subprocess.run([str(script), *args], cwd=cwd, capture_output=True, text=True, check=False)


def scores(cache: Path, cwd: Path = ROOT) -> dict[Key, int]:
    """Each function's score, keyed by file and name as complexipy keys its snapshot: methods as ``Class::name``, and
    of the functions of one file that share a name, each after the first as ``name#<position>``."""
    report = ("--output-format", "json", "--output", "-", "--cache-dir", str(cache))
    result = complexipy("--snapshot-ignore", "--quiet", *report, cwd=cwd)
    # It exits with 1 both when a function is over the limit and when it cannot run; only a run prints the report.
    assert result.returncode in (0, 1) and result.stdout.lstrip().startswith("["), result.stderr
    found: dict[Key, int] = {}
    for function in sorted(json.loads(result.stdout), key=lambda function: (function["path"], function["line_start"])):
        path, name = function["path"], function["function_name"]
        key, times = (path, name), 1
        while key in found:
            times += 1
            key = (path, f"{name}#{times}")
        found[key] = function["complexity"]
    return found


def over_limit(found: dict[Key, int]) -> dict[Key, int]:
    return {key: score for key, score in found.items() if score > COGNITIVE_LIMIT}


def entries(text: str) -> dict[Key, int]:
    return {
        (file["path"], function["name"]): function["complexity"]
        for file in json.loads(text)
        for function in file["functions"]
    }


def against_snapshot(over: dict[Key, int], frozen: dict[Key, int]) -> list[str]:
    """How the functions over the limit and the snapshot's entries disagree."""
    problems = [
        f"{path}::{name} scores {score}, over {COGNITIVE_LIMIT}: simplify it"
        for (path, name), score in sorted(over.items())
        if (path, name) not in frozen
    ]
    problems += [
        f"{path}::{name} scores {score}, more than the {frozen[(path, name)]} it is frozen at: simplify it"
        for (path, name), score in sorted(over.items())
        if score > frozen.get((path, name), score)
    ]
    problems += [
        f"{path}::{name} is frozen at {score} but is gone or now scores {over.get((path, name), 'within the limit')}: "
        "run `uv run complexipy` to lower or remove its entry"
        for (path, name), score in sorted(frozen.items())
        if over.get((path, name), 0) < score
    ]
    return problems


def gained(now: dict[Key, int], before: dict[Key, int]) -> list[str]:
    """The entries of ``now`` that ``before`` does not cover. Entries are matched by name, whatever their file: the
    entries of one name, highest first, each need one of ``before`` at no lower score. At the same score, the one that
    stayed in its file goes first, so that a copy is the one reported."""
    found = []
    for name in sorted({name for _, name in now}):
        theirs = {path: score for (path, other), score in before.items() if other == name}
        mine = sorted(
            ((score, path in theirs, path) for (path, other), score in now.items() if other == name), reverse=True
        )
        ceilings = sorted(theirs.values(), reverse=True)
        found += [
            f"{path}::{name} at {score}"
            for place, (score, _, path) in enumerate(mine)
            if place >= len(ceilings) or score > ceilings[place]
        ]
    return found


def snapshot_on_baseline() -> str | None:
    """The snapshot on origin/main, or ``None`` while it has none. A missing origin/main fails, never passes."""
    found = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{BASELINE}^{{commit}}"], cwd=ROOT, capture_output=True, check=False
    )
    assert found.returncode == 0, f"{BASELINE} is missing: run `git fetch origin main` before the suite"
    shown = subprocess.run(
        ["git", "show", f"{BASELINE}:{SNAPSHOT}"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    return shown.stdout if shown.returncode == 0 else None


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


def test_complexipy_reads_the_limit_and_the_code_from_pyproject():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"].get("complexipy")

    assert config == COMPLEXIPY_CONFIGURATION


def test_no_function_scores_more_than_the_limit_or_its_frozen_entry(tmp_path):
    frozen = entries((ROOT / SNAPSHOT).read_text(encoding="utf-8"))

    found = against_snapshot(over_limit(scores(tmp_path)), frozen)

    assert found == [], (
        f"Functions over the cognitive complexity limit of {COGNITIVE_LIMIT}, or {SNAPSHOT} out of step with them. "
        "Split a new or a grown function into smaller ones instead of freezing it:\n" + "\n".join(found)
    )


def test_the_snapshot_never_gains_an_entry_or_a_point():
    baseline = snapshot_on_baseline()
    if baseline is None:
        pytest.skip(f"{BASELINE} has no {SNAPSHOT} yet: this is the change that freezes the functions over the limit")

    found = gained(entries((ROOT / SNAPSHOT).read_text(encoding="utf-8")), entries(baseline))

    assert found == [], f"{SNAPSHOT} only shrinks: simplify the function instead of freezing it.\n" + "\n".join(found)


def test_the_snapshot_on_the_baseline_is_read_there(monkeypatch):
    monkeypatch.setitem(globals(), "BASELINE", "HEAD")
    committed = subprocess.run(["git", "show", f"HEAD:{SNAPSHOT}"], cwd=ROOT, capture_output=True, text=True, check=True)

    assert snapshot_on_baseline() == committed.stdout


def test_a_baseline_without_the_snapshot_has_nothing_to_compare_with(monkeypatch):
    monkeypatch.setitem(globals(), "BASELINE", "HEAD")
    monkeypatch.setitem(globals(), "SNAPSHOT", "no-such-complexipy-snapshot.json")

    assert snapshot_on_baseline() is None


def test_a_missing_origin_main_fails_instead_of_skipping(monkeypatch):
    monkeypatch.setitem(globals(), "BASELINE", "origin/no-such-branch-for-the-snapshot")

    with pytest.raises(AssertionError, match="origin/no-such-branch-for-the-snapshot is missing"):
        snapshot_on_baseline()


def configured_tree(tmp_path: Path) -> Path:
    """An empty tree with this repo's pyproject.toml, and so its ruff and complexipy configuration."""
    tree = tmp_path / "tree"
    (tree / "live" / "migrations").mkdir(parents=True)
    shutil.copy(ROOT / "pyproject.toml", tree / "pyproject.toml")
    return tree


def test_a_function_nested_past_15_fails_although_ruff_lets_it_by_and_one_at_15_passes(tmp_path):
    tree = configured_tree(tmp_path)
    (tree / "live" / "knotty.py").write_text(KNOTTY + "\n\n" + FLAT, encoding="utf-8")
    (tree / "live" / "migrations" / "0002_knotty.py").write_text(KNOTTY, encoding="utf-8")
    ruff = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--no-cache", "."], cwd=tree, capture_output=True, text=True, check=False
    )

    assert ruff.returncode == 0, ruff.stdout + ruff.stderr
    assert against_snapshot(over_limit(scores(tmp_path / "cache", cwd=tree)), {}) == [
        "live/knotty.py::knotty scores 16, over 15: simplify it"
    ]


def test_scores_key_methods_by_class_and_a_repeated_name_by_its_position(tmp_path):
    tree = configured_tree(tmp_path)
    method = "class Knot:\n" + "".join(f"    {line}\n" for line in KNOTTY.replace("(a,", "(self, a,").splitlines())
    (tree / "live" / "knots.py").write_text(f"{KNOTTY}\n\n{KNOTTY}\n\n{method}", encoding="utf-8")

    assert over_limit(scores(tmp_path / "cache", cwd=tree)) == {
        ("live/knots.py", "knotty"): 16,
        ("live/knots.py", "knotty#2"): 16,
        ("live/knots.py", "Knot::knotty"): 16,
    }


def test_a_function_over_the_limit_without_an_entry_or_above_it_is_reported_and_a_stale_entry_too():
    over = {("live/a.py", "new"): 16, ("live/a.py", "grown"): 30, ("live/a.py", "kept"): 20, ("live/a.py", "less"): 18}
    frozen = {("live/a.py", "grown"): 25, ("live/a.py", "kept"): 20, ("live/a.py", "less"): 22, ("live/b.py", "gone"): 17}

    assert against_snapshot(over, frozen) == [
        "live/a.py::new scores 16, over 15: simplify it",
        "live/a.py::grown scores 30, more than the 25 it is frozen at: simplify it",
        "live/a.py::less is frozen at 22 but is gone or now scores 18: run `uv run complexipy` to lower or remove its "
        "entry",
        "live/b.py::gone is frozen at 17 but is gone or now scores within the limit: run `uv run complexipy` to lower "
        "or remove its entry",
    ]


def test_an_entry_follows_its_function_to_another_file_at_no_higher_score():
    before = {("live/checks.py", "_asks_problems"): 27, ("live/a.py", "run"): 30, ("live/b.py", "run"): 20}
    now = {("live/checks_asks.py", "_asks_problems"): 25, ("live/c.py", "run"): 20, ("live/d.py", "run"): 30}

    assert gained(now, before) == []


def test_a_new_entry_a_higher_score_a_rename_or_a_copy_is_gained():
    before = {("live/a.py", "run"): 30, ("live/b.py", "home"): 20}
    now = {
        ("live/a.py", "run"): 30,
        ("live/c.py", "run"): 30,
        ("live/b.py", "home"): 21,
        ("live/b.py", "house"): 20,
        ("live/e.py", "fresh"): 16,
    }

    assert gained(now, before) == [
        "live/e.py::fresh at 16",
        "live/b.py::home at 21",
        "live/b.py::house at 20",
        "live/c.py::run at 30",
    ]
