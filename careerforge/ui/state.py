"""Session state. The profile and everything derived from it live here; pages never touch session_state directly.

Privacy: everything is held in the visitor's server-side session memory only. Nothing is written to disk and
nothing is sent anywhere except the AI provider the visitor (or site owner) configured, and only when an AI action
is run.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any, TypeVar

import streamlit as st

from careerforge.ai.client import AIClient, build_client
from careerforge.ai.errors import AINotConfigured
from careerforge.ai.settings import AISettings, load_settings
from careerforge.models import Profile
from careerforge.tracker import Tracker
from careerforge.ui.errors import AIBudgetExceeded

T = TypeVar("T")

PROFILE, REV, JOB, JOB_TITLE, COMPANY = "profile", "rev", "job_text", "job_title", "company"
TRACKER, USER_KEYS, AI_CALLS, MEMO, TAILORED, LAST_INGEST = (
    "tracker",
    "user_keys",
    "ai_calls",
    "_memo",
    "tailored",
    "ingest",
)
DEFAULT_AI_LIMIT = 30
_KEY_NAMES = (
    "GEMINI_API_KEY", "GROQ_API_KEY", "CAREERFORGE_GEMINI_MODELS", "CAREERFORGE_GROQ_MODELS",
    "CAREERFORGE_GEMINI_BASE_URL", "CAREERFORGE_GROQ_BASE_URL", "CAREERFORGE_SESSION_AI_LIMIT",
    "ADZUNA_APP_ID", "ADZUNA_APP_KEY", "GITHUB_TOKEN",
)  # fmt: skip


# ── profile ─────────────────────────────────────────────────────────────────


def profile() -> Profile | None:
    return st.session_state.get(PROFILE)


def rev() -> int:
    """Changes whenever the profile is replaced; widget keys include it so forms never show stale values."""
    return st.session_state.get(REV, 0)


def set_profile(p: Profile | None, *, ingest: object = None) -> None:
    st.session_state[PROFILE] = p
    st.session_state[REV] = rev() + 1
    st.session_state.pop(MEMO, None)
    st.session_state.pop(TAILORED, None)
    if ingest is not None:
        st.session_state[LAST_INGEST] = ingest


def last_ingest() -> Any:
    return st.session_state.get(LAST_INGEST)


def require_profile() -> Profile:
    """The profile, or a friendly prompt to create one (and the page stops)."""
    p = profile()
    if p is None:
        st.info("Start by adding your CV, LinkedIn export or GitHub on the **Start** page.")
        st.page_link("careerforge/ui/pages/start.py", label="Go to Start", icon=":material/play_arrow:")
        st.stop()
    return p


def tailored() -> Profile | None:
    return st.session_state.get(TAILORED)


def set_tailored(p: Profile | None) -> None:
    if p is None:
        st.session_state.pop(TAILORED, None)
    else:
        st.session_state[TAILORED] = p


# ── job posting ─────────────────────────────────────────────────────────────


def job_text() -> str:
    return st.session_state.get(JOB, "")


def set_job(text: str, *, title: str = "", company: str = "") -> None:
    st.session_state[JOB] = text
    if title:
        st.session_state[JOB_TITLE] = title
    if company:
        st.session_state[COMPANY] = company
    st.session_state.pop(MEMO, None)


def job_title() -> str:
    return st.session_state.get(JOB_TITLE, "")


def company() -> str:
    return st.session_state.get(COMPANY, "")


# ── tracker ─────────────────────────────────────────────────────────────────


def tracker() -> Tracker:
    return st.session_state.setdefault(TRACKER, Tracker())


def set_tracker(t: Tracker) -> None:
    st.session_state[TRACKER] = t


# ── memo: cheap deterministic results, recomputed only when inputs change ───


def memo(key: tuple, compute: Callable[[], T]) -> T:
    store: dict[tuple, Any] = st.session_state.setdefault(MEMO, {})
    if key not in store:
        if len(store) > 40:
            store.clear()
        store[key] = compute()
    return store[key]


# ── AI ──────────────────────────────────────────────────────────────────────


def _site_config() -> dict[str, str]:
    """Operator configuration: Streamlit secrets first, then environment variables."""
    out: dict[str, str] = {}
    try:
        secrets = st.secrets
        for name in _KEY_NAMES:
            if name in secrets:
                out[name] = str(secrets[name])
    except Exception:  # noqa: BLE001, S110 - no secrets file at all is a normal situation, not an error
        out = {}
    for name in _KEY_NAMES:
        if name not in out and os.environ.get(name):
            out[name] = os.environ[name]
    return out


def site_secret(name: str) -> str:
    """One operator-configured value (secret or environment variable), or ''."""
    return _site_config().get(name, "")


def user_keys() -> dict[str, str]:
    return st.session_state.setdefault(USER_KEYS, {})


def set_user_keys(gemini: str, groq: str) -> None:
    keys = {k: v.strip() for k, v in (("GEMINI_API_KEY", gemini), ("GROQ_API_KEY", groq)) if v and v.strip()}
    st.session_state[USER_KEYS] = keys
    st.session_state.pop("_client_error", None)


def using_own_keys() -> bool:
    return bool(user_keys())


def ai_settings() -> AISettings:
    """The visitor's own keys win over the site's. The two are never mixed."""
    site = _site_config()
    own = user_keys()
    if own:  # the visitor's keys replace the site's keys entirely; pinned models etc. still come from the site
        site = {k: v for k, v in site.items() if k not in ("GEMINI_API_KEY", "GROQ_API_KEY")}
    merged = {**site, **own}
    return load_settings(merged, env={})


@st.cache_resource(ttl=3600, show_spinner=False, max_entries=8)
def _cached_client(gemini: str, groq: str, gem_models: str, groq_models: str, gem_url: str, groq_url: str) -> AIClient:
    settings = AISettings(
        gemini_api_key=gemini,
        groq_api_key=groq,
        gemini_models=tuple(m for m in gem_models.split(",") if m),
        groq_models=tuple(m for m in groq_models.split(",") if m),
        gemini_base_url=gem_url or None,
        groq_base_url=groq_url or None,
    )
    return build_client(settings)


def ai_configured() -> bool:
    return ai_settings().configured


def ai_client() -> AIClient | None:
    """A ready client, or None when no key is configured. Raises only on genuinely broken configuration."""
    s = ai_settings()
    if not s.configured:
        return None
    return _cached_client(
        s.gemini_api_key,
        s.groq_api_key,
        ",".join(s.gemini_models),
        ",".join(s.groq_models),
        s.gemini_base_url or "",
        s.groq_base_url or "",
    )


def ai_limit() -> int:
    raw = _site_config().get("CAREERFORGE_SESSION_AI_LIMIT", "")
    return int(raw) if raw.isdigit() else DEFAULT_AI_LIMIT


def ai_calls_left() -> int | None:
    """None = unlimited (the visitor uses their own key)."""
    if using_own_keys():
        return None
    return max(0, ai_limit() - st.session_state.get(AI_CALLS, 0))


def charge_ai() -> AIClient:
    """Call before every AI action: returns the client and counts one use against the shared quota."""
    client = ai_client()
    if client is None:
        raise AINotConfigured("No AI provider is configured.")
    left = ai_calls_left()
    if left is not None and left <= 0:
        raise AIBudgetExceeded(
            f"This session has used its {ai_limit()} shared AI actions. Add your own free key in Settings to continue."
        )
    st.session_state[AI_CALLS] = st.session_state.get(AI_CALLS, 0) + 1
    return client
