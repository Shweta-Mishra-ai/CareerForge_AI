"""The source tree itself: no invisible or direction-changing characters ("Trojan Source"), no leftover modules."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SUSPECT = {*range(0x200B, 0x2010), *range(0x202A, 0x202F), *range(0x2060, 0x2065), *range(0x2066, 0x206A), 0xFEFF}
SOURCES = sorted(
    p
    for pattern in ("careerforge/**/*.py", "careerforge/**/*.j2", "careerforge/**/*.css", "tools/*.py", "app.py")
    for p in ROOT.glob(pattern)
)


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: str(p.relative_to(ROOT)))
def test_no_invisible_or_bidirectional_characters_in_source(path):
    bad = [
        (n, hex(ord(c)))
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        for c in line
        if ord(c) in SUSPECT
    ]
    assert bad == [], f"write these as escapes (\\uXXXX) so a reader can see them: {bad[:3]}"


def test_there_is_no_leftover_code_outside_the_package():
    stray = [p.name for p in ROOT.iterdir() if p.is_dir() and p.name in {"core", "templates"} and any(p.rglob("*.py"))]
    assert stray == [], "the old core/ and templates/ modules were removed in the merge"
