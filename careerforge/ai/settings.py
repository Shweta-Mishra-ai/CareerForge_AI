"""AI settings: keys and model lists, from Streamlit secrets and/or environment.

Models are discovered at runtime from each provider's own model list (see careerforge.ai.models), so no name can
go stale. CAREERFORGE_GEMINI_MODELS / CAREERFORGE_GROQ_MODELS (comma separated) PIN specific models and skip
discovery. The FALLBACK_* names below are only a last resort when discovery itself fails, and are unverified guesses.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

FALLBACK_GEMINI_MODELS = ("gemini-2.5-flash", "gemini-2.5-flash-lite")
FALLBACK_GROQ_MODELS = ("llama-3.3-70b-versatile", "llama-3.1-8b-instant")


@dataclass(frozen=True)
class AISettings:
    gemini_api_key: str = ""
    groq_api_key: str = ""
    gemini_models: tuple[str, ...] = ()  # empty = discover automatically; non-empty = pinned by the user
    groq_models: tuple[str, ...] = ()
    timeout_s: float = 45.0
    max_tokens: int = 4096
    max_tokens_cap: int = 16384
    max_source_chars: int = 24000
    gemini_base_url: str | None = None  # tests point these at a local fake server
    groq_base_url: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.gemini_api_key or self.groq_api_key)

    @property
    def secrets(self) -> tuple[str, ...]:
        return tuple(k for k in (self.gemini_api_key, self.groq_api_key) if k)


def _first(name: str, sources: tuple[Mapping[str, object], ...]) -> str:
    for src in sources:
        value = src.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _models(name: str, sources: tuple[Mapping[str, object], ...]) -> tuple[str, ...]:
    raw = _first(name, sources)
    return tuple(m.strip() for m in raw.split(",") if m.strip())


def load_settings(secrets: Mapping[str, object] | None = None, env: Mapping[str, str] | None = None) -> AISettings:
    """Build settings; `secrets` (e.g. a dict copy of st.secrets) wins over `env` (defaults to os.environ)."""
    sources: tuple[Mapping[str, object], ...] = (secrets or {}, env if env is not None else os.environ)
    return AISettings(
        gemini_api_key=_first("GEMINI_API_KEY", sources),
        groq_api_key=_first("GROQ_API_KEY", sources),
        gemini_models=_models("CAREERFORGE_GEMINI_MODELS", sources),
        groq_models=_models("CAREERFORGE_GROQ_MODELS", sources),
    )
