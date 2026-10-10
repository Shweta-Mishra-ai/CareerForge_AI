"""Turn exceptions into sentences a job seeker can act on. Never shows internals, stack traces or API keys."""

from __future__ import annotations

import logging

from careerforge.ai import errors as ai
from careerforge.ai.extract import NotEnoughText
from careerforge.ingest.errors import IngestError
from careerforge.models import ProfileError
from careerforge.readiness import NotReady

log = logging.getLogger("careerforge.ui")


class AIBudgetExceeded(Exception):
    """The shared (site-owner) AI quota for this session is used up."""


def explain(exc: BaseException) -> str:
    """One short message, safe to show. Unexpected errors are logged (redacted) and reported generically."""
    if isinstance(exc, AIBudgetExceeded):
        return str(exc)
    if isinstance(exc, ai.AINotConfigured):
        return "AI is not set up. Add a free Gemini or Groq key in Settings, or use the basic (no-AI) option."
    if isinstance(exc, ai.AIAuthError):
        return "The AI provider rejected the API key. Check it in Settings."
    if isinstance(exc, ai.AIExhausted):
        kinds = [why.split(":", 1)[0] for _, why in exc.attempts]
        if kinds and all(k == "AIUnavailable" for k in kinds):
            return (
                "The AI service could not be reached (network problem, or the provider is blocked from here). "
                "Try again, or use the basic (no-AI) option. Nothing was changed."
            )
        if kinds and all(k == "AIAuthError" for k in kinds):
            return "The AI provider rejected the API key. Check it in Settings."
    if isinstance(exc, (ai.AIQuotaExhausted, ai.AIRateLimited, ai.AIExhausted)):
        return (
            "The free AI models are out of quota or too busy right now. Wait a few minutes and try again, "
            "or use the basic (no-AI) option. Nothing was changed."
        )
    if isinstance(exc, ai.AIUnavailable):
        return "The AI service could not be reached. Try again in a moment. Nothing was changed."
    if isinstance(exc, ai.AIOutputError):
        return "The AI answered with something unusable, even after a retry. Nothing was changed. Please try again."
    if isinstance(exc, ai.AIBadRequest):
        return "The AI provider refused the request (the text may be too long or blocked). Try shorter input."
    if isinstance(exc, ai.AIError):
        return "The AI request failed. Nothing was changed."
    if isinstance(exc, NotEnoughText):
        return (
            "There is too little text to work with. If this is a scanned image, use a text-based PDF or paste the text."
        )
    if isinstance(exc, NotReady):
        return "Fix these before exporting: " + "; ".join(i.message for i in exc.readiness.blockers)
    if isinstance(exc, (IngestError, ProfileError)):
        return str(exc)
    log.exception("unexpected error")  # the logger is the only place details go
    return f"Something unexpected went wrong ({type(exc).__name__}). Nothing was changed; please try again."
