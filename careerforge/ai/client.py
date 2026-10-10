"""AIClient: ordered cascade of (provider, model) routes with bounded retries and validated output.

* Retryable failures (429, 5xx, timeouts) back off exponentially with jitter, honouring Retry-After, within an
  overall deadline so the UI can never hang for minutes.
* A rejected key disables that whole provider for the call; a retired model just moves to the next model.
* `structured()` validates output with a caller-supplied parser and makes at most one repair attempt. If the
  answer was cut off by the token limit it retries with a bigger budget (up to the configured cap).
* Failure is LOUD: AIExhausted / AIOutputError. There are no silent fallbacks to fake data.
"""

from __future__ import annotations

import random
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import TypeVar

from careerforge.ai.errors import (
    AIAuthError,
    AIBadRequest,
    AIError,
    AIExhausted,
    AIModelNotFound,
    AINotConfigured,
    AIOutputError,
    redact,
)
from careerforge.ai.jsonutil import JSONExtractError, JSONTruncatedError, extract_json
from careerforge.ai.providers import Completion, GeminiProvider, GroqProvider, Provider, Request
from careerforge.ai.settings import AISettings

T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    attempts_per_route: int = 3
    base_delay: float = 1.0
    max_delay: float = 8.0
    jitter: float = 0.25
    deadline_s: float = 60.0


@dataclass
class Clock:
    """Injected so tests run instantly and deterministically."""

    sleep: Callable[[float], None] = time.sleep
    monotonic: Callable[[], float] = time.monotonic
    uniform: Callable[[float, float], float] = random.uniform


@dataclass(frozen=True)
class Route:
    provider: Provider
    model: str

    def __str__(self) -> str:
        return f"{self.provider.name}/{self.model}"


@dataclass
class AIClient:
    routes: list[Route]
    policy: RetryPolicy = field(default_factory=RetryPolicy)
    clock: Clock = field(default_factory=Clock)
    secrets: tuple[str, ...] = ()
    max_tokens_cap: int = 16384

    def _msg(self, exc: Exception) -> str:
        return redact(f"{type(exc).__name__}: {exc}", self.secrets)

    def complete(self, req: Request) -> Completion:
        if not self.routes:
            raise AINotConfigured("No AI provider is configured. Add GEMINI_API_KEY and/or GROQ_API_KEY.")
        start = self.clock.monotonic()
        attempts: list[tuple[str, str]] = []
        kinds: list[type[Exception]] = []
        dead: set[str] = set()

        def record(route: Route, exc: Exception) -> None:
            attempts.append((str(route), self._msg(exc)))
            kinds.append(type(exc))

        def out_of_time() -> bool:
            return self.clock.monotonic() - start >= self.policy.deadline_s

        for route in self.routes:
            if route.provider.name in dead:
                continue
            for attempt in range(1, self.policy.attempts_per_route + 1):
                if out_of_time():
                    attempts.append((str(route), "deadline exceeded"))
                    kinds.append(TimeoutError)
                    raise self._exhausted(attempts, kinds)
                try:
                    return route.provider.complete(route.model, req)
                except AIAuthError as exc:
                    dead.add(route.provider.name)
                    record(route, exc)
                    break
                except (AIModelNotFound, AIBadRequest) as exc:
                    record(route, exc)
                    break
                except AIError as exc:  # retryable
                    record(route, exc)
                    if attempt == self.policy.attempts_per_route:
                        break
                    delay = self._delay(attempt, getattr(exc, "retry_after", None))
                    if self.clock.monotonic() - start + delay >= self.policy.deadline_s:
                        break
                    self.clock.sleep(delay)
        raise self._exhausted(attempts, kinds)

    def _delay(self, attempt: int, retry_after: float | None) -> float:
        if retry_after is not None:  # the provider told us how long to wait (capped so the UI cannot stall)
            return min(retry_after, self.policy.max_delay)
        base = min(self.policy.max_delay, self.policy.base_delay * 2 ** (attempt - 1))
        return base * (1 + self.clock.uniform(-self.policy.jitter, self.policy.jitter))

    def _exhausted(self, attempts: list[tuple[str, str]], kinds: list[type[Exception]]) -> AIExhausted:
        tail = "; ".join(f"{route}: {why}" for route, why in attempts[-4:])
        only_auth = bool(kinds) and all(k is AIAuthError for k in kinds)
        head = "The AI provider rejected the API key" if only_auth else "All AI providers failed"
        return AIExhausted(f"{head} ({tail})" if tail else head, attempts)

    def structured(self, req: Request, parse: Callable[[str], T], *, max_repairs: int = 1) -> tuple[T, Completion]:
        """Call, then parse+validate with `parse` (raise ValueError to reject). One repair attempt by default."""
        current = req
        last_error: Exception | None = None
        for _ in range(max_repairs + 1):
            completion = self.complete(current)
            try:
                return parse(completion.text), completion
            except ValueError as exc:
                last_error = exc
                # The provider's finish-reason is the reliable truncation signal; an unclosed JSON brace is
                # only a hint (it could just be garbage), so it adds token budget but never replaces feedback.
                cut_by_provider = completion.truncated
                maybe_cut = cut_by_provider or isinstance(exc, JSONTruncatedError)
                can_grow = current.max_tokens < self.max_tokens_cap
                tokens = (
                    min(self.max_tokens_cap, current.max_tokens * 2) if maybe_cut and can_grow else current.max_tokens
                )
                if cut_by_provider and can_grow:
                    user = req.user  # same prompt, bigger budget
                elif cut_by_provider:
                    user = f"{req.user}\n\nYour previous reply was cut off by the length limit. Make it shorter."
                else:
                    reason = re.sub(r"\s+", " ", str(exc))[:300]
                    user = (
                        f"{req.user}\n\nYour previous reply was rejected: {reason}. "
                        "Reply again with ONLY the corrected JSON object."
                    )
                current = replace(req, max_tokens=tokens, user=user)
        raise AIOutputError(f"The AI returned unusable output: {redact(str(last_error), self.secrets)[:300]}")


def parse_json_object(text: str) -> dict:
    """Default parser for structured(): the reply must contain a JSON object."""
    value = extract_json(text)
    if not isinstance(value, dict):
        raise JSONExtractError("Expected a JSON object")
    return value


def build_client(settings: AISettings, *, policy: RetryPolicy | None = None, clock: Clock | None = None) -> AIClient:
    """Routes: Gemini models first, then Groq models. Raises AINotConfigured when there is no key at all."""
    if not settings.configured:
        raise AINotConfigured("No AI provider is configured. Add GEMINI_API_KEY and/or GROQ_API_KEY.")
    routes: list[Route] = []
    if settings.gemini_api_key:
        gemini = GeminiProvider(
            settings.gemini_api_key, timeout_s=settings.timeout_s, base_url=settings.gemini_base_url
        )
        routes += [Route(gemini, m) for m in settings.gemini_models]
    if settings.groq_api_key:
        groq = GroqProvider(settings.groq_api_key, timeout_s=settings.timeout_s, base_url=settings.groq_base_url)
        routes += [Route(groq, m) for m in settings.groq_models]
    return AIClient(routes, policy or RetryPolicy(), clock or Clock(), settings.secrets, settings.max_tokens_cap)
