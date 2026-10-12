"""`python -m careerforge.ai.doctor` - which AI models actually work with MY keys right now?

Lists what each provider says is available, ranks it, sends one tiny JSON request to the top candidates, and prints
the result plus ready-to-paste settings. This is the one reliable way to learn which models are currently usable
(and on your plan), because neither provider exposes "free tier" in its model list.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from careerforge.ai.client import AIClient, parse_json_object
from careerforge.ai.errors import AIError, redact
from careerforge.ai.models import rank_gemini, rank_groq
from careerforge.ai.providers import GeminiProvider, GroqProvider, Provider, Request
from careerforge.ai.settings import AISettings, load_settings

PROBE = Request(system="Reply with one JSON object.", user='Return {"ok": true}', max_tokens=64, temperature=0.0)


def _probe(provider: Provider, model: str, secrets: tuple[str, ...]) -> tuple[bool, str, float]:
    start = time.monotonic()
    try:
        value = parse_json_object(provider.complete(model, PROBE).text)
        ok = value.get("ok") is True
        return ok, "answered" if ok else "answered, but not with the expected JSON", time.monotonic() - start
    except (AIError, ValueError) as exc:
        return False, redact(f"{type(exc).__name__}: {exc}", secrets), time.monotonic() - start


@dataclass(frozen=True)
class RouteCheck:
    route: str
    ok: bool
    detail: str
    seconds: float


def check_routes(client: AIClient) -> list[RouteCheck]:
    """Send one tiny request to every route of a client, so the user sees which model names answer right now."""
    out = []
    for route in client.routes:
        ok, detail, secs = _probe(route.provider, route.model, client.secrets)
        out.append(RouteCheck(str(route), ok, detail, secs))
    return out


def _targets(settings: AISettings) -> list[tuple[str, Provider, Callable[[Provider], list[str]]]]:
    """(label, provider, 'list + rank' function) for each configured provider."""
    out: list[tuple[str, Provider, Callable[[Provider], list[str]]]] = []
    if settings.gemini_api_key:
        gemini = GeminiProvider(
            settings.gemini_api_key, timeout_s=settings.timeout_s, base_url=settings.gemini_base_url
        )
        out.append(("Gemini", gemini, lambda p: rank_gemini(p.list_models())))
    if settings.groq_api_key:
        groq = GroqProvider(settings.groq_api_key, timeout_s=settings.timeout_s, base_url=settings.groq_base_url)
        out.append(("Groq", groq, lambda p: rank_groq(p.list_models())))
    return out


def run(settings: AISettings, *, top: int = 3, out: TextIO = sys.stdout) -> int:
    """Returns 0 if at least one model works, 1 if none do, 2 if no key is configured."""

    def say(text: str = "") -> None:
        print(text, file=out)

    if not settings.configured:
        say("No API key found. Set GEMINI_API_KEY and/or GROQ_API_KEY (environment or .streamlit/secrets.toml).")
        return 2
    working: dict[str, list[str]] = {"gemini": [], "groq": []}
    for label, provider, list_and_rank in _targets(settings):
        say(f"== {label} ==")
        try:
            ranked = list_and_rank(provider)
        except AIError as exc:
            say(f"  Could not list models: {redact(str(exc), settings.secrets)}")
            continue
        say(f"  {len(ranked)} usable text models found; best first: {', '.join(ranked[:8]) or '(none)'}")
        for model in ranked[:top]:
            ok, detail, secs = _probe(provider, model, settings.secrets)
            say(f"  {'OK  ' if ok else 'FAIL'} {model:<40} {secs:4.1f}s  {detail}")
            if ok:
                working[label.lower()].append(model)
    say()
    if not any(working.values()):
        say("No model answered. Check the key, the account's region/plan, and the errors above.")
        return 1
    say("Working models (best first). To pin them instead of auto-discovery:")
    if working["gemini"]:
        say(f"  CAREERFORGE_GEMINI_MODELS={','.join(working['gemini'])}")
    if working["groq"]:
        say(f"  CAREERFORGE_GROQ_MODELS={','.join(working['groq'])}")
    say("Without these variables the app discovers and ranks models automatically at start-up.")
    return 0


def _secrets_from_file(path: Path) -> dict[str, object]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check which AI models work with your API keys.")
    parser.add_argument("--secrets", type=Path, default=Path(".streamlit/secrets.toml"))
    parser.add_argument("--top", type=int, default=5, help="how many top-ranked models per provider to test")
    args = parser.parse_args(argv)
    return run(load_settings(_secrets_from_file(args.secrets), os.environ), top=args.top)


if __name__ == "__main__":
    raise SystemExit(main())
