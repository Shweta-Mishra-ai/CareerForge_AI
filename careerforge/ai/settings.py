"""AI settings: keys and model lists, from Streamlit secrets and/or environment.

Model names are NOT hard-coded into logic. The defaults below are best guesses that may be retired by the
providers; override them with CAREERFORGE_GEMINI_MODELS / CAREERFORGE_GROQ_MODELS (comma separated). A model
that is no longer served is skipped automatically (AIModelNotFound) and the next one is tried.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

DEFAULT_GEMINI_MODELS = ("gemini-2.5-flash", "gemini-2.5-flash-lite")
DEFAULT_GROQ_MODELS = ("llama-3.3-70b-versatile", "llama-3.1-8b-instant")


@dataclass(frozen=True)
class AISettings:
    gemini_api_key: str = ""
    groq_api_key: str = ""
    gemini_models: tuple[str, ...] = DEFAULT_GEMINI_MODELS
    groq_models: tuple[str, ...] = DEFAULT_GROQ_MODELS
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


def _models(name: str, sources: tuple[Mapping[str, object], ...], default: tuple[str, ...]) -> tuple[str, ...]:
    raw = _first(name, sources)
    items = tuple(m.strip() for m in raw.split(",") if m.strip())
    return items or default


def load_settings(secrets: Mapping[str, object] | None = None, env: Mapping[str, str] | None = None) -> AISettings:
    """Build settings; `secrets` (e.g. a dict copy of st.secrets) wins over `env` (defaults to os.environ)."""
    sources: tuple[Mapping[str, object], ...] = (secrets or {}, env if env is not None else os.environ)
    return AISettings(
        gemini_api_key=_first("GEMINI_API_KEY", sources),
        groq_api_key=_first("GROQ_API_KEY", sources),
        gemini_models=_models("CAREERFORGE_GEMINI_MODELS", sources, DEFAULT_GEMINI_MODELS),
        groq_models=_models("CAREERFORGE_GROQ_MODELS", sources, DEFAULT_GROQ_MODELS),
    )
