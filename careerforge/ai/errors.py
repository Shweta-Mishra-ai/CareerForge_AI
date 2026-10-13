"""AI error hierarchy. Messages are safe to show to users (API keys are redacted)."""

from __future__ import annotations

import re


class AIError(Exception):
    """Base class for every AI failure."""


class AINotConfigured(AIError):
    """No API key is configured for any provider."""


class AIAuthError(AIError):
    """Key rejected/forbidden. Retrying the provider is pointless."""


class AIModelNotFound(AIError):
    """Model name unknown/retired for this provider. Skip to the next model."""


class AIBadRequest(AIError):
    """Provider refused the request (invalid params, safety block, context too long)."""


class AIQuotaExhausted(AIError):
    """This model's quota is used up (daily limit) or is zero on the current plan. Retrying cannot help; try another."""


class AIRateLimited(AIError):
    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class AIUnavailable(AIError):
    """Timeouts, connection errors, 5xx."""


class AIOutputError(AIError):
    """The model answered, but not with usable output, even after a repair attempt."""


class AIExhausted(AIError):
    """Every route failed. `attempts` is a list of (route, error-summary) for diagnostics."""

    def __init__(self, message: str, attempts: list[tuple[str, str]] | None = None):
        super().__init__(message)
        self.attempts = attempts or []


_KEY_LIKE = re.compile(r"(AIza[0-9A-Za-z_\-]{20,}|gsk_[0-9A-Za-z]{20,}|sk-[0-9A-Za-z_\-]{20,}|Bearer\s+\S+)")


def redact(text: str, secrets: tuple[str, ...] = ()) -> str:
    """Remove configured keys and anything key-shaped from a message before it is logged or shown."""
    for s in secrets:
        if s and len(s) >= 6:
            text = text.replace(s, "[redacted]")
    return _KEY_LIKE.sub("[redacted]", text)
