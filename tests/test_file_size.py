"""Every tracked code file stays under its size cap; the ones over it today are listed in .file-size-allow.

A line of the list is ``<ceiling> <path> #<issue>``: the ceiling is the file's size the day it was listed, rounded up to
a hundred. The list only shrinks: against origin/main it never gains a path nor raises a ceiling, a listed file that
fits again leaves it, and a file that shrinks below its ceiling's hundred lowers it.
"""

import subprocess
from pathlib import Path, PurePosixPath

import pytest

ROOT = Path(__file__).resolve().parent.parent
ALLOW = ".file-size-allow"
BASELINE = "origin/main"
PRODUCTION_CAP = 1000
TEST_CAP = 1500
EXTENSIONS = (".py", ".sh")
GENERATED_DIRS = frozenset({"migrations"})


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 0, f"git {' '.join(args)} failed: {result.stderr}"
    return result.stdout


def is_test(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return parts[0] == "tests" or parts[-1].startswith("test_") or parts[-1] == "conftest.py"


def cap(path: str) -> int:
    return TEST_CAP if is_test(path) else PRODUCTION_CAP


def ceiling_for(lines: int) -> int:
    """The size rounded up to a hundred."""
    return -(-lines // 100) * 100


def parse_allow(text: str) -> tuple[dict[str, int], list[str]]:
    """``({path: ceiling}, problems)``; blank lines and lines starting with ``#`` are comments."""
    ceilings: dict[str, int] = {}
    problems = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) != 3 or not fields[0].isdigit() or not fields[2].startswith("#"):
            problems.append(f"{ALLOW}:{number}: {line!r} is not '<ceiling> <path> #<issue>'")
        elif fields[1] in ceilings:
            problems.append(f"{ALLOW}:{number}: {fields[1]} is listed twice")
        else:
            ceilings[fields[1]] = int(fields[0])
    return ceilings, problems


def size_problems(sizes: dict[str, int], ceilings: dict[str, int]) -> list[str]:
    """What breaks the caps: ``sizes`` are the lines of each code file, ``ceilings`` the list."""
    problems = [
        f"{path} has {lines} lines, over its cap of {cap(path)}: split it by responsibility"
        for path, lines in sizes.items()
        if path not in ceilings and lines > cap(path)
    ]
    for path, ceiling in ceilings.items():
        problems += listed_problems(path, sizes.get(path), ceiling)
    return problems


def listed_problems(path: str, lines: int | None, ceiling: int) -> list[str]:
    if lines is None:
        return [f"{path} is listed in {ALLOW} but is not a tracked code file: remove its line"]
    if lines <= cap(path):
        return [f"{path} has {lines} lines and fits its cap of {cap(path)}: remove its line from {ALLOW}"]
    if lines > ceiling:
        return [f"{path} has {lines} lines, over its ceiling of {ceiling} in {ALLOW}: it may not grow"]
    if ceiling > ceiling_for(lines):
        return [f"{path} has {lines} lines: lower its ceiling in {ALLOW} from {ceiling} to {ceiling_for(lines)}"]
    return []


def ratchet_problems(ceilings: dict[str, int], baseline: dict[str, int]) -> list[str]:
    """The list against the one of the baseline: no new path, no higher ceiling."""
    return [
        f"{path} is not listed in {BASELINE}'s {ALLOW}: the list only shrinks"
        if path not in baseline
        else f"{path}'s ceiling {ceiling} is over {baseline[path]}, the one in {BASELINE}: the list only shrinks"
        for path, ceiling in ceilings.items()
        if ceiling > baseline.get(path, -1)
    ]


def tracked_sizes() -> dict[str, int]:
    paths = git("ls-files", "-z", "--", *(f"*{extension}" for extension in EXTENSIONS)).split("\0")
    return {
        path: len((ROOT / path).read_bytes().splitlines())
        for path in paths
        if path and (ROOT / path).is_file() and not GENERATED_DIRS & set(PurePosixPath(path).parts)
    }


def baseline_text() -> str | None:
    """The list on origin/main, or ``None`` while origin/main has none. A missing origin/main fails, never passes."""
    found = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{BASELINE}^{{commit}}"], cwd=ROOT, capture_output=True, check=False
    )
    assert found.returncode == 0, f"{BASELINE} is missing: run `git fetch origin main` before the suite"
    if not git("ls-tree", "--name-only", BASELINE, "--", ALLOW).strip():
        return None
    return git("show", f"{BASELINE}:{ALLOW}")


# The rules, on made-up files


def test_a_production_file_over_1000_lines_outside_the_list_fails():
    assert size_problems({"live/big.py": 1001, "live/fits.py": 1000}, {}) == [
        "live/big.py has 1001 lines, over its cap of 1000: split it by responsibility"
    ]


@pytest.mark.parametrize("path", ["tests/helpers.py", "live/test_thing.py", "live/conftest.py", "tests/run.sh"])
def test_a_test_file_has_a_cap_of_1500_lines(path):
    assert size_problems({path: 1500}, {}) == []
    assert size_problems({path: 1501}, {}) == [f"{path} has 1501 lines, over its cap of 1500: split it by responsibility"]


def test_a_listed_file_over_its_ceiling_fails():
    assert size_problems({"live/big.py": 2301}, {"live/big.py": 2300}) == [
        f"live/big.py has 2301 lines, over its ceiling of 2300 in {ALLOW}: it may not grow"
    ]


def test_a_listed_file_up_to_its_ceiling_passes():
    sizes = {"live/big.py": 2300, "tests/test_big.py": 3601}

    assert size_problems(sizes, {"live/big.py": 2300, "tests/test_big.py": 3700}) == []


def test_a_listed_file_that_fits_its_cap_again_fails():
    assert size_problems({"live/big.py": 1000}, {"live/big.py": 2300}) == [
        f"live/big.py has 1000 lines and fits its cap of 1000: remove its line from {ALLOW}"
    ]


def test_a_listed_file_that_does_not_exist_fails():
    assert size_problems({}, {"live/gone.py": 2300}) == [
        f"live/gone.py is listed in {ALLOW} but is not a tracked code file: remove its line"
    ]


def test_a_listed_file_that_shrinks_below_its_ceilings_hundred_lowers_it():
    assert size_problems({"live/big.py": 2150}, {"live/big.py": 2300}) == [
        f"live/big.py has 2150 lines: lower its ceiling in {ALLOW} from 2300 to 2200"
    ]


def test_the_list_may_not_gain_a_path_nor_raise_a_ceiling_against_the_baseline():
    baseline = {"live/big.py": 2300, "tests/test_big.py": 3700}

    assert ratchet_problems({"live/big.py": 2200}, baseline) == []
    assert ratchet_problems({"live/big.py": 2400, "live/new.py": 1100}, baseline) == [
        f"live/big.py's ceiling 2400 is over 2300, the one in {BASELINE}: the list only shrinks",
        f"live/new.py is not listed in {BASELINE}'s {ALLOW}: the list only shrinks",
    ]


@pytest.mark.parametrize(
    "line", ["2300 live/big.py", "big live/big.py #141", "2300 live/big.py 141", "2300 live/big.py #141 extra"]
)
def test_a_malformed_line_of_the_list_fails(line):
    assert parse_allow(line) == ({}, [f"{ALLOW}:1: {line!r} is not '<ceiling> <path> #<issue>'"])


def test_the_list_skips_comments_and_rejects_a_path_listed_twice():
    text = "# a comment\n\n2300 live/big.py #141\n2400 live/big.py #141\n"

    assert parse_allow(text) == ({"live/big.py": 2300}, [f"{ALLOW}:4: live/big.py is listed twice"])


def test_a_missing_origin_main_fails_instead_of_passing(monkeypatch):
    monkeypatch.setitem(globals(), "BASELINE", "origin/no-such-branch-for-the-size-list")

    with pytest.raises(AssertionError, match="origin/no-such-branch-for-the-size-list is missing"):
        baseline_text()


def test_a_baseline_without_the_list_has_nothing_to_compare_with(monkeypatch):
    monkeypatch.setitem(globals(), "BASELINE", "HEAD")
    monkeypatch.setitem(globals(), "ALLOW", ".no-such-size-list")

    assert baseline_text() is None


# The rules, on this repo


def test_every_code_file_of_the_repo_keeps_to_its_cap_or_its_ceiling():
    ceilings, problems = parse_allow((ROOT / ALLOW).read_text())
    problems += size_problems(tracked_sizes(), ceilings)

    assert not problems, "\n".join(problems)


def test_the_list_only_shrinks_against_origin_main():
    baseline = baseline_text()
    if baseline is None:
        pytest.skip(f"{BASELINE} has no {ALLOW} yet: this branch brings the first one")
    ceilings, _ = parse_allow((ROOT / ALLOW).read_text())
    problems = ratchet_problems(ceilings, parse_allow(baseline)[0])

    assert not problems, "\n".join(problems)
