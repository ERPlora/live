"""Every tracked code file stays under its size cap; the ones over it are listed in .file-size-allow.

A line of the list is ``<ceiling> <path> #<issue>``: the ceiling is the file's exact size. A listed file may change but
never grows past it, and the change that shrinks the file lowers the ceiling to the new size. The list only shrinks:
against origin/main it never gains a path nor raises a ceiling, and a listed file that fits again leaves it. The caps
only come down; the change that lowers one regenerates the list, with each file at most at its size on origin/main.
A shell script past 100 lines is rewritten in Python; a shell test, under tests/ or named *.test.sh, may reach 1500.
"""

import os
import re
import subprocess
from pathlib import Path, PurePosixPath

import pytest

ROOT = Path(__file__).resolve().parent.parent
ALLOW = ".file-size-allow"
BASELINE = "origin/main"
PRODUCTION_CAP = 500
TEST_CAP = 1000
SHELL_CAP = 100
SHELL_TEST_CAP = 1500
EXTENSIONS = (".py", ".sh")
GENERATED_DIRS = frozenset({"migrations"})
ISSUE_RE = re.compile(r"#[0-9]+")
CAPS_RE = re.compile(r"^([A-Z_]+_CAP) = ([0-9]+)$", re.MULTILINE)
SELF = Path(__file__).resolve().relative_to(ROOT).as_posix()


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 0, f"git {' '.join(args)} failed: {result.stderr}"
    return result.stdout


def is_test(path: str) -> bool:
    parts = PurePosixPath(path).parts
    name = parts[-1]
    return (
        parts[0] == "tests"
        or (name.startswith("test_") and name.endswith(".py"))
        or name == "conftest.py"
        or name.endswith(".test.sh")
    )


def is_shell(path: str) -> bool:
    return path.endswith(".sh")


def cap(path: str) -> int:
    if is_shell(path):
        return SHELL_TEST_CAP if is_test(path) else SHELL_CAP
    return TEST_CAP if is_test(path) else PRODUCTION_CAP


def parse_allow(text: str) -> tuple[dict[str, int], list[str]]:
    """``({path: ceiling}, problems)``; blank lines and lines starting with ``#`` are comments."""
    ceilings: dict[str, int] = {}
    problems = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) != 3 or not fields[0].isdigit() or not ISSUE_RE.fullmatch(fields[2]):
            problems.append(f"{ALLOW}:{number}: {line!r} is not '<ceiling> <path> #<issue>'")
        elif fields[1] in ceilings:
            problems.append(f"{ALLOW}:{number}: {fields[1]} is listed twice")
        else:
            ceilings[fields[1]] = int(fields[0])
    return ceilings, problems


def size_problems(sizes: dict[str, int], ceilings: dict[str, int]) -> list[str]:
    """What breaks the caps: ``sizes`` are the lines of each code file, ``ceilings`` the list."""
    problems = [
        f"{path} has {lines} lines, over its cap of {cap(path)}: {advice(path)}"
        for path, lines in sizes.items()
        if path not in ceilings and lines > cap(path)
    ]
    for path, ceiling in ceilings.items():
        problems += listed_problems(path, sizes.get(path), ceiling)
    return problems


def advice(path: str) -> str:
    return "rewrite it in Python" if is_shell(path) and not is_test(path) else "split it by responsibility"


def listed_problems(path: str, lines: int | None, ceiling: int) -> list[str]:
    if lines is None:
        return [f"{path} is listed in {ALLOW} but is not a tracked code file: remove its line"]
    if lines <= cap(path):
        return [f"{path} has {lines} lines and fits its cap of {cap(path)}: remove its line from {ALLOW}"]
    if lines > ceiling:
        return [f"{path} has {lines} lines, over its ceiling of {ceiling} in {ALLOW}: it may not grow"]
    if ceiling > lines:
        return [f"{path} has {lines} lines: lower its ceiling in {ALLOW} from {ceiling} to {lines}"]
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


def cap_problems(caps: dict[str, int], baseline: dict[str, int]) -> list[str]:
    """No cap of the baseline may rise or go; a cap the baseline does not have yet has nothing to compare with."""
    problems = []
    for name, before in baseline.items():
        if name not in caps:
            problems.append(f"{name} is gone, it was {before} on {BASELINE}: a cap only comes down")
        elif caps[name] > before:
            problems.append(f"{name} {caps[name]} is over {before}, the one on {BASELINE}: a cap only comes down")
    return problems


def parse_caps(text: str) -> dict[str, int]:
    """Every ``<NAME>_CAP = <lines>`` this file's source sets, by name."""
    caps = {name: int(lines) for name, lines in CAPS_RE.findall(text)}
    assert {"PRODUCTION_CAP", "TEST_CAP"} <= caps.keys(), f"cannot read PRODUCTION_CAP and TEST_CAP from {SELF}"
    return caps


def allowed_ceilings(
    baseline_list: dict[str, int], baseline_sizes: dict[str, int], caps: dict[str, int], baseline_caps: dict[str, int]
) -> dict[str, int]:
    """The most the list may hold: the baseline's list, unless this change lowers a cap and so regenerates the list,
    which may then hold any file up to its size on the baseline (``baseline_sizes``)."""
    lowered = any(caps.get(name, before) < before for name, before in baseline_caps.items())
    return baseline_sizes if lowered else baseline_list


def size_on_baseline(path: str) -> int | None:
    """The file's lines on the baseline, counted as ``tracked_sizes`` does; ``None`` where it does not exist there."""
    found = subprocess.run(["git", "cat-file", "blob", f"{BASELINE}:{path}"], cwd=ROOT, capture_output=True, check=False)
    return len(found.stdout.splitlines()) if found.returncode == 0 else None


def tracked_sizes() -> dict[str, int]:
    paths = git("ls-files", "-z", "--", *(f"*{extension}" for extension in EXTENSIONS)).split("\0")
    return {
        path: len((ROOT / path).read_bytes().splitlines())
        for path in paths
        if path and (ROOT / path).is_file() and not GENERATED_DIRS & set(PurePosixPath(path).parts)
    }


def own_caps() -> dict[str, int]:
    return parse_caps(Path(__file__).read_text())


def baseline_caps() -> dict[str, int]:
    return parse_caps(git("show", f"{BASELINE}:{SELF}"))


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

MADE_UP_CAPS = {"PRODUCTION_CAP": 500, "TEST_CAP": 1000, "SHELL_CAP": 100, "SHELL_TEST_CAP": 1500}


@pytest.fixture
def scratch_git(tmp_path, monkeypatch):
    """Runs git in a new repo at ``tmp_path``, made the ROOT of this test, without the user's git configuration."""
    identity = {f"GIT_{role}_{field}": "size-test" for role in ("AUTHOR", "COMMITTER") for field in ("NAME", "EMAIL")}
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", **identity}

    def run(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, env=env, check=True)

    run("init", "-q")
    monkeypatch.setitem(globals(), "ROOT", tmp_path)
    return run


def test_a_production_file_over_500_lines_outside_the_list_fails():
    assert size_problems({"live/big.py": 501, "live/fits.py": 500}, {}) == [
        "live/big.py has 501 lines, over its cap of 500: split it by responsibility"
    ]


@pytest.mark.parametrize("path", ["tests/helpers.py", "live/test_thing.py", "live/conftest.py"])
def test_a_test_file_has_a_cap_of_1000_lines(path):
    assert size_problems({path: 1000}, {}) == []
    assert size_problems({path: 1001}, {}) == [f"{path} has 1001 lines, over its cap of 1000: split it by responsibility"]


@pytest.mark.parametrize("path", ["live/run.sh", "live/test_run.sh", ".githooks/pre-push.sh"])
def test_a_shell_script_over_100_lines_fails_with_the_advice_to_rewrite_it_in_python(path):
    assert size_problems({path: 100}, {}) == []
    assert size_problems({path: 101}, {}) == [f"{path} has 101 lines, over its cap of 100: rewrite it in Python"]


@pytest.mark.parametrize("path", ["tests/run.sh", ".githooks/pre-push.test.sh"])
def test_a_shell_test_has_a_cap_of_1500_lines(path):
    assert size_problems({path: 101}, {}) == []
    assert size_problems({path: 1500}, {}) == []
    assert size_problems({path: 1501}, {}) == [f"{path} has 1501 lines, over its cap of 1500: split it by responsibility"]


def test_a_listed_file_over_its_ceiling_fails():
    assert size_problems({"live/big.py": 2301}, {"live/big.py": 2300}) == [
        f"live/big.py has 2301 lines, over its ceiling of 2300 in {ALLOW}: it may not grow"
    ]


def test_a_listed_file_at_its_ceiling_passes():
    sizes = {"live/big.py": 2300, "tests/test_big.py": 3601}

    assert size_problems(sizes, {"live/big.py": 2300, "tests/test_big.py": 3601}) == []


def test_a_listed_file_that_fits_its_cap_again_fails():
    assert size_problems({"live/big.py": 500}, {"live/big.py": 2300}) == [
        f"live/big.py has 500 lines and fits its cap of 500: remove its line from {ALLOW}"
    ]


def test_a_listed_file_that_does_not_exist_fails():
    assert size_problems({}, {"live/gone.py": 2300}) == [
        f"live/gone.py is listed in {ALLOW} but is not a tracked code file: remove its line"
    ]


def test_a_listed_file_that_shrinks_lowers_its_ceiling_to_its_exact_size():
    assert size_problems({"live/big.py": 2299}, {"live/big.py": 2300}) == [
        f"live/big.py has 2299 lines: lower its ceiling in {ALLOW} from 2300 to 2299"
    ]


def test_the_list_may_not_gain_a_path_nor_raise_a_ceiling_against_the_baseline():
    baseline = {"live/big.py": 2300, "tests/test_big.py": 3700}

    assert ratchet_problems({"live/big.py": 2200}, baseline) == []
    assert ratchet_problems({"live/big.py": 2400, "live/new.py": 1100}, baseline) == [
        f"live/big.py's ceiling 2400 is over 2300, the one in {BASELINE}: the list only shrinks",
        f"live/new.py is not listed in {BASELINE}'s {ALLOW}: the list only shrinks",
    ]


def test_a_cap_may_not_rise_against_the_baseline():
    looser = {"PRODUCTION_CAP": 1000, "TEST_CAP": 1500, "SHELL_CAP": 500, "SHELL_TEST_CAP": 2000}
    higher = {"PRODUCTION_CAP": 501, "TEST_CAP": 1001, "SHELL_CAP": 101, "SHELL_TEST_CAP": 1501}

    assert cap_problems(MADE_UP_CAPS, MADE_UP_CAPS) == []
    assert cap_problems(MADE_UP_CAPS, looser) == []
    assert cap_problems(higher, MADE_UP_CAPS) == [
        f"PRODUCTION_CAP 501 is over 500, the one on {BASELINE}: a cap only comes down",
        f"TEST_CAP 1001 is over 1000, the one on {BASELINE}: a cap only comes down",
        f"SHELL_CAP 101 is over 100, the one on {BASELINE}: a cap only comes down",
        f"SHELL_TEST_CAP 1501 is over 1500, the one on {BASELINE}: a cap only comes down",
    ]


def test_a_cap_of_the_baseline_may_not_go():
    assert cap_problems({"PRODUCTION_CAP": 500, "TEST_CAP": 1000, "SHELL_TEST_CAP": 1500}, MADE_UP_CAPS) == [
        f"SHELL_CAP is gone, it was 100 on {BASELINE}: a cap only comes down"
    ]


def test_a_cap_the_baseline_does_not_have_yet_has_nothing_to_compare_with():
    assert cap_problems(MADE_UP_CAPS, {"PRODUCTION_CAP": 500, "TEST_CAP": 1000}) == []


def test_the_caps_are_read_from_the_size_test():
    text = "PRODUCTION_CAP = 400\nTEST_CAP = 900\nSHELL_CAP = 80\nSHELL_TEST_CAP = 1200\nOTHER = 1\n"

    assert parse_caps(text) == {"PRODUCTION_CAP": 400, "TEST_CAP": 900, "SHELL_CAP": 80, "SHELL_TEST_CAP": 1200}
    with pytest.raises(AssertionError, match="cannot read PRODUCTION_CAP and TEST_CAP"):
        parse_caps("PRODUCTION_CAP = 400\nSHELL_CAP = 80\n")


def test_the_caps_this_change_compares_are_all_the_caps_of_this_test():
    assert own_caps() == {
        "PRODUCTION_CAP": PRODUCTION_CAP,
        "TEST_CAP": TEST_CAP,
        "SHELL_CAP": SHELL_CAP,
        "SHELL_TEST_CAP": SHELL_TEST_CAP,
    }


def test_the_caps_of_the_baseline_are_read_from_this_test_there(monkeypatch):
    shown = []
    monkeypatch.setitem(globals(), "git", lambda *args: shown.append(args) or "PRODUCTION_CAP = 400\nTEST_CAP = 900\n")

    assert baseline_caps() == {"PRODUCTION_CAP": 400, "TEST_CAP": 900}
    assert shown == [("show", f"{BASELINE}:tests/test_file_size.py")]


@pytest.mark.parametrize(
    "lowered", [{"PRODUCTION_CAP": 400}, {"TEST_CAP": 900}, {"SHELL_CAP": 90}, {"SHELL_TEST_CAP": 1400}]
)
def test_the_change_that_lowers_a_cap_may_list_any_file_up_to_its_size_on_the_baseline(lowered):
    sizes = {"live/big.py": 720, "tests/test_big.py": 1349}
    allowed = allowed_ceilings({}, sizes, {**MADE_UP_CAPS, **lowered}, MADE_UP_CAPS)

    assert ratchet_problems({"live/big.py": 720, "tests/test_big.py": 1349}, allowed) == []
    assert ratchet_problems({"live/big.py": 721, "live/new.py": 600}, allowed) == [
        f"live/big.py's ceiling 721 is over 720, the one in {BASELINE}: the list only shrinks",
        f"live/new.py is not listed in {BASELINE}'s {ALLOW}: the list only shrinks",
    ]


@pytest.mark.parametrize("caps", [{}, {"PRODUCTION_CAP": 600}, {"SHELL_CAP": 200}])
def test_any_other_change_may_only_keep_or_shrink_the_list_of_the_baseline(caps):
    sizes = {"live/big.py": 720, "live/other.py": 650}
    allowed = allowed_ceilings({"live/big.py": 720}, sizes, {**MADE_UP_CAPS, **caps}, MADE_UP_CAPS)

    assert allowed == {"live/big.py": 720}


def test_the_size_on_the_baseline_is_read_there_and_counted_as_in_the_working_tree(tmp_path, scratch_git, monkeypatch):
    # A file that grew in the branch, committed or not, must not pass for its size on the baseline.
    def commit(content: bytes) -> None:
        (tmp_path / "big.py").write_bytes(content)
        scratch_git("add", "big.py")
        scratch_git("commit", "-qm", "big.py")

    commit(b"a\nb\r\nc")
    scratch_git("branch", "base")
    commit(b"a\nb\nc\nd\n")
    (tmp_path / "big.py").write_bytes(b"a\nb\nc\nd\ne\n")
    monkeypatch.setitem(globals(), "BASELINE", "base")

    assert size_on_baseline("big.py") == 3
    assert size_on_baseline("gone.py") is None


def test_the_shell_scripts_of_the_repo_are_measured_with_their_caps(tmp_path, scratch_git):
    (tmp_path / "tests").mkdir()
    (tmp_path / "ci").mkdir()
    sizes = {"run.sh": 101, "fits.sh": 100, "ci/deploy.test.sh": 101, "tests/run.sh": 1501}
    for path, lines in sizes.items():
        (tmp_path / path).write_text("echo\n" * lines)
    scratch_git("add", "-N", *sizes)

    assert size_problems(tracked_sizes(), {}) == [
        "run.sh has 101 lines, over its cap of 100: rewrite it in Python",
        "tests/run.sh has 1501 lines, over its cap of 1500: split it by responsibility",
    ]


@pytest.mark.parametrize(
    "line",
    ["2300 live/big.py", "big live/big.py #141", "2300 live/big.py 141", "2300 live/big.py #", "2300 live/big.py #141 x"],
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


def test_the_caps_never_rise_against_origin_main():
    problems = cap_problems(own_caps(), baseline_caps())

    assert not problems, "\n".join(problems)


def test_the_list_only_shrinks_against_origin_main():
    baseline = baseline_text()
    if baseline is None:
        pytest.skip(f"{BASELINE} has no {ALLOW} yet: this branch brings the first one")
    ceilings, _ = parse_allow((ROOT / ALLOW).read_text())
    sizes = {path: lines for path in ceilings if (lines := size_on_baseline(path)) is not None}
    allowed = allowed_ceilings(parse_allow(baseline)[0], sizes, own_caps(), baseline_caps())
    problems = ratchet_problems(ceilings, allowed)

    assert not problems, "\n".join(problems)
