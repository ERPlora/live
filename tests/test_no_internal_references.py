"""Code is read by people who have never seen the project's planning documents.

Comments, docstrings, test names and log messages have to make sense on their own, so the code
never points at a plan section, a planning round or phase, a delivery slice, a private tracker or
a person's note. Markdown files are left out: they are where the plans live.
"""

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# Built from its code point so that this file does not trip its own scan.
SECTION_SIGN = "\N{SECTION SIGN}"

INTERNAL_REFERENCE = re.compile(
    "|".join(
        (
            SECTION_SIGN + r" ?[0-9]",
            r"(Plan|PLAN)(-[A-Z]+)?(\.md)? ?" + SECTION_SIGN,
            r"[Rr](onda|ound) [0-9]+",
            r"[Pp]hase [0-9]|[Ff]ase [0-9]",
            r"[Tt]ajada S?[0-9]",
            r"\b(pm|knowledge)#[0-9]",
            r"\bIoan\b",
        )
    )
)


def code_files():
    """Tracked files plus new ones not ignored, so a reference is caught before its first commit."""
    listing = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=REPO,
        check=True,
        capture_output=True,
    ).stdout
    paths = sorted({p for p in listing.decode().split("\0") if p})
    return [p for p in paths if not p.endswith(".md") and (REPO / p).is_file()]


def internal_references(paths):
    found = []
    for path in paths:
        data = (REPO / path).read_bytes()
        if b"\0" in data:
            continue
        for number, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
            if INTERNAL_REFERENCE.search(line):
                found.append(f"{path}:{number}: {line.strip()}")
    return found


def test_code_never_points_at_internal_plans():
    paths = code_files()
    assert "tests/test_no_internal_references.py" in paths, "git ls-files listed no code"
    found = internal_references(paths)
    assert not found, "Code that points at internal plans, rounds or notes:\n" + "\n".join(found)


@pytest.mark.parametrize(
    "text",
    [
        "Voice and video calls (Plan " + SECTION_SIGN + "66)",
        "see PLAN-HUB " + SECTION_SIGN + "84",
        "PLAN.md" + SECTION_SIGN + "5",
        "the shared schema (round " + "16)",
        "PLAN-HUB round " + "2026-10-21",
        "ronda " + "2026-11-10e",
        "the relay of phase " + "2",
        "en la fase " + "1",
        "tajada " + "S3",
        "as agreed in pm" + "#43",
        "knowledge" + "#120 has the list",
        "(Io" + "an, 2026-10-13)",
    ],
)
def test_the_scan_catches_each_kind_of_reference(text):
    assert INTERNAL_REFERENCE.search(text)


@pytest.mark.parametrize(
    "text",
    [
        "total = round(amount, 2)",
        "Plan the refund before the payment",
        "the two-phase commit of the outbox",
        "hub#12 fixed the retry",
        "Section 5 of the AEAT schema",
    ],
)
def test_the_scan_leaves_ordinary_text_alone(text):
    assert not INTERNAL_REFERENCE.search(text)
