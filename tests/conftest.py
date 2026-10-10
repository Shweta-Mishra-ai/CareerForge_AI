import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def fixture_text():
    """Load a fixture file by name, e.g. fixture_text('cv_standard.txt')."""

    def _load(name: str) -> str:
        return (FIXTURES / name).read_text(encoding="utf-8")

    return _load
