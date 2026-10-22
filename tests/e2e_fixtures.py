"""Fixtures for the browser tests (registered as a plugin in conftest.py)."""

import re

import pytest
from e2e_support import FIXTURES, AppServer, FakeGemini, chromium_path
from playwright.sync_api import expect, sync_playwright
from test_grounding import faithful_standard
from test_render_cv import ready
from test_writing import GOOD_PARAS

CV = FIXTURES / "cv_ready.txt"
JD = (
    "Senior Backend Engineer\nRequirements: 5+ years of Python or Go; Kafka, PostgreSQL, Redis, Kubernetes, Docker, "
    "AWS, REST API design, CI/CD; mentoring engineers. Nice to have: Terraform, gRPC."
)
PROFILE = ready(faithful_standard())
BENIGN_CONSOLE = re.compile(
    r"favicon|Failed to load resource: the server responded with a status of 40[34]|ResizeObserver"
)


# ── fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    s = AppServer(tmp_path_factory.mktemp("plain"))
    yield s
    s.stop()


@pytest.fixture(scope="module")
def ai():
    replies = {
        "data-extraction engine": PROFILE.model_dump(mode="json"),
        "reword THEIR OWN CV bullets": {
            "bullets": [
                {"id": "1", "text": "Reduced p95 API latency from 480ms to 190ms by introducing Redis caching."},
                {"id": "3", "text": "Built REST API endpoints in Flask serving 50k requests/min."},
            ]
        },
        "BODY of a cover letter": {"paragraphs": GOOD_PARAS},
        "prepare a job seeker for an interview": {
            "questions": [
                {
                    "category": "technical",
                    "question": "How did you reduce API latency at Finlytics?",
                    "why_asked": "Performance work",
                    "cv_evidence": "Cut p95 API latency from 480ms to 190ms by introducing Redis caching.",
                    "tips": "Use STAR.",
                }
            ]
        },
    }
    fake = FakeGemini(replies)
    yield fake
    fake.close()


@pytest.fixture(scope="module")
def ai_server(tmp_path_factory, ai):
    secrets = {
        "GEMINI_API_KEY": "fake-e2e-key-1234567890",
        "CAREERFORGE_GEMINI_MODELS": "fake-model",
        "CAREERFORGE_GEMINI_BASE_URL": ai.url,
    }
    s = AppServer(tmp_path_factory.mktemp("ai"), secrets)
    yield s
    s.stop()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        path = chromium_path()
        b = p.chromium.launch(executable_path=path) if path else p.chromium.launch()
        yield b
        b.close()


class Session:
    """One browser tab plus everything we want to assert on afterwards."""

    def __init__(self, browser, server, viewport=(1280, 900)):
        self.server = server
        self.context = browser.new_context(
            accept_downloads=True, viewport={"width": viewport[0], "height": viewport[1]}
        )
        self.page = self.context.new_page()
        self.console: list[str] = []
        self.requests: list[str] = []
        self.dialogs: list[str] = []
        self.page.on("console", lambda m: self.console.append(m.text) if m.type == "error" else None)
        self.page.on("pageerror", lambda e: self.console.append(f"pageerror: {e}"))
        self.page.on("request", lambda r: self.requests.append(r.url))
        self.page.on("dialog", lambda d: (self.dialogs.append(d.message), d.dismiss()))
        self.page.goto(server.url)
        self.wait_title("Start")

    # navigation and widgets ---------------------------------------------------
    def wait_title(self, title: str) -> None:
        expect(self.page.get_by_role("heading", name=title, exact=True).first).to_be_visible(timeout=30000)

    def go(self, name: str, title: str | None = None) -> None:
        self.page.get_by_role("link", name=name).first.click()
        self.wait_title(title or name)

    def settle(self, quiet_ms: int = 400, timeout_ms: int = 30000) -> None:
        """Wait until the app has finished running its script and stayed idle for `quiet_ms`. A fixed sleep is not
        enough on a slow machine (CI): the next click can land while the previous change is still being applied."""
        self.page.evaluate("window.__cfBusy = performance.now()")  # a run may start just after this call
        self.page.wait_for_function(
            """(quiet) => {
                const app = document.querySelector('[data-testid="stApp"]');
                if (!app || app.getAttribute('data-test-script-state') !== 'notRunning') {
                    window.__cfBusy = performance.now();
                    return false;
                }
                return performance.now() - window.__cfBusy >= quiet;
            }""",
            arg=quiet_ms,
            polling=50,
            timeout=timeout_ms,
        )

    def click(self, name: str) -> None:
        self.page.get_by_role("button", name=name).first.click()

    def choose(self, label: str) -> None:
        self.page.get_by_text(label, exact=True).first.click()

    def load_cv(self, path=CV, *, basic: bool = True) -> None:
        if basic and self.page.get_by_text("Basic (no AI").count():
            self.choose("Basic (no AI, nothing leaves this app)")
        self.page.set_input_files("input[type=file]", str(path))
        self.click("Read this file")
        self.wait_title("Review & edit")

    def paste_job(self, text: str = JD) -> None:
        box = self.page.get_by_role("textbox", name="Job posting (paste the full text)")
        box.fill(text)
        box.blur()
        self.page.wait_for_timeout(600)

    def download(self, button: str):
        with self.page.expect_download(timeout=30000) as info:
            self.page.get_by_role(
                "button", name=re.compile(rf"(^|\s){re.escape(button)}$")
            ).first.click()  # icon + label
        return info.value

    # assertions -----------------------------------------------------------
    def assert_clean(self) -> None:
        errors = [e for e in self.console if not BENIGN_CONSOLE.search(e)]
        assert errors == [], errors
        assert self.dialogs == []
        external = [u for u in self.requests if not re.match(r"^(http://127\.0\.0\.1|data:|blob:|about:)", u)]
        assert external == [], f"third-party requests: {external}"
        assert "Traceback" not in self.server.log_text(), self.server.log_text()[-1500:]
        assert not self.page.locator("[data-testid=stException]").count()

    def close(self) -> None:
        self.context.close()


@pytest.fixture
def session(browser, server):
    s = Session(browser, server)
    yield s
    s.close()


@pytest.fixture
def ai_session(browser, ai_server, ai):
    ai.requests.clear()
    ai.fail = False
    s = Session(browser, ai_server)
    yield s
    s.close()
