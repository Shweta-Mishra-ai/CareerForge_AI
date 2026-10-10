import sys
from pathlib import Path

import pytest

pytest_plugins = ["e2e_fixtures"]

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


@pytest.fixture
def ui_env(monkeypatch):
    """Hermetic UI tests: no real secrets file, no environment keys, no network AI. Returns a configurator."""
    from careerforge.ui import state

    config: dict[str, str] = {}
    monkeypatch.setattr(state, "_site_config", lambda: dict(config))
    monkeypatch.setattr(
        state, "_cached_client", lambda *a, **k: (_ for _ in ()).throw(AssertionError("unexpected real AI client"))
    )

    class Env:
        def site(self, **values: str) -> None:
            config.update(values)

        def ai(self, client) -> None:
            """Pretend the site owner configured a key and make the app use `client`."""
            config.setdefault("GEMINI_API_KEY", "test-key-not-real")
            monkeypatch.setattr(state, "_cached_client", lambda *a, **k: client)

    return Env()
