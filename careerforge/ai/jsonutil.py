"""Extract a JSON value from LLM text without the old 'first { to last }' guess.

A small scanner finds the first balanced object/array while respecting strings and escapes, so prose after the
JSON, code fences, and braces inside strings all work. Truncated output is reported as truncated - never
auto-'repaired' into data the model did not write.
"""

from __future__ import annotations

import json
import re
from typing import Any


class JSONExtractError(ValueError):
    """No usable JSON in the text."""


class JSONTruncatedError(JSONExtractError):
    """JSON started but the text ended before it closed (usually a token limit)."""


_FENCE = re.compile(r"```(?:json|JSON)?\s*\n?(.*?)```", re.S)
_CLOSERS = {"{": "}", "[": "]"}


def _balanced_slice(text: str, start: int) -> str:
    stack: list[str] = []
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in _CLOSERS:
            stack.append(_CLOSERS[ch])
        elif ch in "}]":
            if not stack or stack.pop() != ch:
                raise JSONExtractError("Mismatched brackets in JSON")
            if not stack:
                return text[start : i + 1]
    raise JSONTruncatedError("JSON ends before it is closed (output was probably cut off)")


def _strip_trailing_commas(raw: str) -> str:
    out: list[str] = []
    in_str = esc = False
    i = 0
    while i < len(raw):
        ch = raw[i]
        if in_str:
            out.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
            out.append(ch)
        elif ch == "," and re.match(r",\s*[}\]]", raw[i:]):
            pass  # drop the dangling comma
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def extract_json(text: str | None) -> Any:
    """Return the first JSON object/array in `text`. Raises JSONExtractError / JSONTruncatedError."""
    body = (text or "").lstrip("﻿").strip()
    if not body:
        raise JSONExtractError("Empty response")
    if fenced := _FENCE.search(body):
        body = fenced.group(1).strip() or body
    starts = [i for i in (body.find("{"), body.find("[")) if i != -1]
    if not starts:
        raise JSONExtractError("No JSON found in the response")
    candidate = _balanced_slice(body, min(starts))
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        try:
            return json.loads(_strip_trailing_commas(candidate))
        except json.JSONDecodeError as exc:
            raise JSONExtractError(f"Invalid JSON: {exc.msg} at position {exc.pos}") from exc
