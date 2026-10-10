"""Pick models by asking each provider what this API key can use, instead of hard-coding names that get retired.

Ranking is ours (pure functions, tested); the *list* comes from the provider at runtime and is cached briefly.
Whether a listed model is on the FREE plan is not exposed by either list API, so that is discovered empirically: a
model without free quota fails fast (AIQuotaExhausted / AIModelNotFound) and the cascade moves to the next one.
Run `python -m careerforge.ai.doctor` to see exactly which models answer for your keys.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from careerforge.ai.errors import AIError

TOP_N = 3  # routes kept per provider: bounds worst-case cascade time
CACHE_TTL_S = 3600.0

# ── Gemini ──────────────────────────────────────────────────────────────────

_GEMINI_EXCLUDE = re.compile(
    r"image|imagen|veo|tts|audio|live|native|embed|aqa|robotics|computer|learnlm|gemma|vision-only|translate", re.I
)
_GEMINI_NAME = re.compile(
    r"^gemini-(?:(?P<ver>\d+(?:\.\d+)?)-(?P<fam>flash-lite|flash|pro)|(?P<alias>flash-lite|flash|pro)-latest)(?:-(?P<suffix>.+))?$"
)
_FAMILY_RANK = {"flash": 0, "flash-lite": 1, "pro": 2}


def rank_gemini(names: Iterable[str]) -> list[str]:
    """Best-first Gemini text models: stable flash > stable flash-lite > stable pro > '-latest' aliases > pinned dated
    versions > previews/experimental. Within a group, newer versions first."""
    ranked: list[tuple[tuple[int, int, float, str], str]] = []
    for raw in names:
        name = raw.removeprefix("models/")
        if _GEMINI_EXCLUDE.search(name):
            continue
        m = _GEMINI_NAME.match(name)
        if not m:
            continue
        family = m["fam"] or m["alias"]
        suffix = (m["suffix"] or "").lower()
        if m["alias"]:
            tier = 1 if not suffix else 3
        elif not suffix:
            tier = 0
        elif re.fullmatch(r"\d{3,}", suffix):
            tier = 2
        else:
            tier = 3  # preview / exp / thinking / dated previews: may change or be tightly rate-limited
        version = float(m["ver"]) if m["ver"] else 0.0
        ranked.append(((tier, _FAMILY_RANK[family], -version, name), name))
    ranked.sort()
    return list(dict.fromkeys(n for _, n in ranked))


# ── Groq ────────────────────────────────────────────────────────────────────

_GROQ_EXCLUDE = re.compile(r"whisper|guard|tts|orpheus|embed|compound|safeguard|playai|distil|moderation|speech", re.I)
_GROQ_PREFERENCE = ("llama-3.3-70b", "gpt-oss-120b", "llama-4", "qwen", "gpt-oss-20b", "llama-3.1-8b", "kimi")


def rank_groq(models: Iterable[dict]) -> list[str]:
    """Best-first Groq chat models. Prefers families known to follow JSON instructions, then larger context."""
    keep: list[tuple[tuple[int, int], str]] = []
    for m in models:
        mid = str(m.get("id") or "")
        if not mid or _GROQ_EXCLUDE.search(mid) or m.get("active") is False:
            continue
        ctx = m.get("context_window")
        if isinstance(ctx, int) and ctx < 16000:
            continue
        pref = next((i for i, f in enumerate(_GROQ_PREFERENCE) if f in mid.lower()), len(_GROQ_PREFERENCE))
        keep.append(((pref, -(ctx if isinstance(ctx, int) else 0)), mid))
    keep.sort()
    return list(dict.fromkeys(mid for _, mid in keep))


# ── discovery ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Discovery:
    gemini: tuple[str, ...] = ()
    groq: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)


_cache: dict[tuple, tuple[float, tuple[str, ...]]] = {}


def clear_cache() -> None:
    _cache.clear()


def _cached(key: tuple, fetch: Callable[[], tuple[str, ...]], now: Callable[[], float]) -> tuple[str, ...]:
    hit = _cache.get(key)
    if hit and now() - hit[0] < CACHE_TTL_S:
        return hit[1]
    value = fetch()
    _cache[key] = (now(), value)
    return value


def discover(
    gemini_provider: object | None = None,
    groq_provider: object | None = None,
    *,
    top_n: int = TOP_N,
    cache_key: tuple = (),
    now: Callable[[], float] = time.monotonic,
) -> Discovery:
    """Ask the providers which models are usable. Failures are reported in `notes`, never raised."""
    notes: list[str] = []
    gem: tuple[str, ...] = ()
    grq: tuple[str, ...] = ()
    if gemini_provider is not None:
        try:
            gem = _cached(
                ("gemini", *cache_key), lambda: tuple(rank_gemini(gemini_provider.list_models())[:top_n]), now
            )
            if not gem:
                notes.append("Gemini listed no usable text models for this key")
        except AIError as exc:
            notes.append(f"Could not list Gemini models ({type(exc).__name__})")
    if groq_provider is not None:
        try:
            grq = _cached(("groq", *cache_key), lambda: tuple(rank_groq(groq_provider.list_models())[:top_n]), now)
            if not grq:
                notes.append("Groq listed no usable chat models for this key")
        except AIError as exc:
            notes.append(f"Could not list Groq models ({type(exc).__name__})")
    return Discovery(gem, grq, tuple(notes))
