"""Provider adapters: one `complete()` call per (provider, model), SDK errors mapped to our hierarchy.

The adapters do NOT retry; retrying/cascading is the AIClient's job so behaviour is identical for every
provider and testable without a network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from groq import (
    APIConnectionError as GroqConnectionError,
)
from groq import (
    APIStatusError as GroqStatusError,
)
from groq import (
    APITimeoutError as GroqTimeoutError,
)
from groq import (
    Groq,
)

from careerforge.ai.errors import (
    AIAuthError,
    AIBadRequest,
    AIModelNotFound,
    AIQuotaExhausted,
    AIRateLimited,
    AIUnavailable,
)


@dataclass(frozen=True)
class Request:
    system: str
    user: str
    temperature: float = 0.1
    max_tokens: int = 4096
    json_mode: bool = True


@dataclass(frozen=True)
class Completion:
    text: str
    provider: str
    model: str
    truncated: bool = False  # the provider stopped because of the token limit


class Provider(Protocol):
    name: str

    def complete(self, model: str, req: Request) -> Completion: ...


def _retry_after(headers: object) -> float | None:
    try:
        value = headers.get("retry-after")  # type: ignore[attr-defined]
        return min(float(value), 120.0) if value is not None else None
    except (AttributeError, TypeError, ValueError):
        return None


def _classify_status(status: int, message: str, retry_after: float | None = None) -> Exception:
    """Map an HTTP status (+ message hints) to our errors. Shared by both providers."""
    low = message.lower()
    if status in (401, 403) or ("api key" in low and ("not valid" in low or "invalid" in low or "expired" in low)):
        return AIAuthError(f"API key rejected ({status})")
    if status == 404 or "decommissioned" in low or ("model" in low and ("not found" in low or "does not exist" in low)):
        return AIModelNotFound(f"Model not available ({status}): {message[:160]}")
    if status == 429:
        # Heuristic on provider wording (unverified against live services): daily/zero quotas cannot recover within
        # a retry window, so skip to the next model instead of backing off. A miss only costs time, never correctness.
        if re.search(r"limit:\s*0\b|per\s*day|perday|\((?:rpd|tpd)\)|daily", low):
            return AIQuotaExhausted("This model's free quota is used up or unavailable on this plan")
        return AIRateLimited("Rate limit or quota reached", retry_after)
    if status in (408, 409, 425) or status >= 500:
        return AIUnavailable(f"Provider error ({status})")
    return AIBadRequest(f"Request refused ({status}): {message[:200]}")


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, *, timeout_s: float = 45.0, base_url: str | None = None):
        options = genai_types.HttpOptions(timeout=int(timeout_s * 1000), **({"base_url": base_url} if base_url else {}))
        self._client = genai.Client(api_key=api_key, http_options=options)

    def complete(self, model: str, req: Request) -> Completion:
        config = genai_types.GenerateContentConfig(
            system_instruction=req.system,
            temperature=req.temperature,
            max_output_tokens=req.max_tokens,
            response_mime_type="application/json" if req.json_mode else None,
        )
        try:
            resp = self._client.models.generate_content(model=model, contents=req.user, config=config)
        except genai_errors.APIError as exc:
            raise _classify_status(int(exc.code or 0), str(exc.message or exc)) from exc
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise AIUnavailable(f"Network problem talking to Gemini: {type(exc).__name__}") from exc

        candidates = resp.candidates or []
        if not candidates:
            reason = getattr(resp.prompt_feedback, "block_reason", None)
            raise AIBadRequest(f"Gemini returned no answer{f' (blocked: {reason})' if reason else ''}")
        cand = candidates[0]
        parts = getattr(cand.content, "parts", None) or []
        text = "".join(p.text for p in parts if getattr(p, "text", None) and not getattr(p, "thought", False))
        finish = getattr(cand.finish_reason, "name", str(cand.finish_reason or ""))
        if finish in ("SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT", "RECITATION") and not text:
            raise AIBadRequest(f"Gemini declined to answer ({finish})")
        return Completion(text, self.name, model, truncated=(finish == "MAX_TOKENS"))

    def list_models(self) -> list[str]:
        """Model ids (without the 'models/' prefix) that can generate content with this key."""
        try:
            names = []
            for m in self._client.models.list():
                actions = getattr(m, "supported_actions", None) or []
                if actions and "generateContent" not in actions:
                    continue  # embedding/other-only models; if the field is absent we assume usable
                names.append(str(m.name or "").removeprefix("models/"))
        except genai_errors.APIError as exc:
            raise _classify_status(int(exc.code or 0), str(exc.message or exc)) from exc
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise AIUnavailable(f"Network problem talking to Gemini: {type(exc).__name__}") from exc
        return [n for n in names if n]


class GroqProvider:
    name = "groq"

    def __init__(self, api_key: str, *, timeout_s: float = 45.0, base_url: str | None = None):
        # max_retries=0: the AIClient owns retry/backoff so it is uniform and observable.
        self._client = Groq(
            api_key=api_key, timeout=timeout_s, max_retries=0, **({"base_url": base_url} if base_url else {})
        )

    def complete(self, model: str, req: Request) -> Completion:
        kwargs = {"response_format": {"type": "json_object"}} if req.json_mode else {}
        try:
            resp = self._client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": req.system}, {"role": "user", "content": req.user}],
                temperature=req.temperature,
                max_tokens=req.max_tokens,
                **kwargs,
            )
        except GroqStatusError as exc:
            message = str(getattr(exc, "message", "") or exc)
            raise _classify_status(exc.status_code, message, _retry_after(exc.response.headers)) from exc
        except (GroqTimeoutError, GroqConnectionError) as exc:
            raise AIUnavailable(f"Network problem talking to Groq: {type(exc).__name__}") from exc

        if not resp.choices:
            raise AIBadRequest("Groq returned no answer")
        choice = resp.choices[0]
        return Completion(choice.message.content or "", self.name, model, truncated=(choice.finish_reason == "length"))

    def list_models(self) -> list[dict]:
        """[{'id', 'active', 'context_window'}] as reported by Groq (fields may be missing)."""
        try:
            data = self._client.models.list().data
        except GroqStatusError as exc:
            message = str(getattr(exc, "message", "") or exc)
            raise _classify_status(exc.status_code, message, _retry_after(exc.response.headers)) from exc
        except (GroqTimeoutError, GroqConnectionError) as exc:
            raise AIUnavailable(f"Network problem talking to Groq: {type(exc).__name__}") from exc
        out = []
        for m in data:
            extra = m.model_extra or {}
            out.append({"id": m.id, "active": extra.get("active", True), "context_window": extra.get("context_window")})
        return out
