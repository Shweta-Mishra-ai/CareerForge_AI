"""Helpers for driving the whole Streamlit app headlessly (AppTest)."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from careerforge.models import Profile

ROOT = Path(__file__).resolve().parent.parent
APP = str(ROOT / "app.py")
PAGE = "careerforge/ui/pages/{}.py"


def new_app(profile: Profile | None = None, **session) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=90)
    if profile is not None:
        at.session_state["profile"] = profile
        at.session_state["rev"] = 1
    for key, value in session.items():
        at.session_state[key] = value
    return at


def open_page(at: AppTest, name: str) -> AppTest:
    at.switch_page(PAGE.format(name))
    return at.run()


def button(at: AppTest, label: str):
    """The (first) button whose label contains `label`; form submit buttons included."""
    for b in at.button:
        if label.lower() in b.label.lower():
            return b
    raise AssertionError(f"no button containing {label!r}; have {[b.label for b in at.button]}")


def find(elements, label: str):
    for e in elements:
        if label.lower() in e.label.lower():
            return e
    raise AssertionError(f"no element containing {label!r}; have {[e.label for e in elements]}")


def _walk(block):
    for child in block.children.values():
        if hasattr(child, "children") and child.children:
            yield from _walk(child)
        else:
            yield child


def texts(at: AppTest) -> str:
    """Everything visible as text, lower-cased, in document order (main area first, then the sidebar)."""
    parts = []
    for root in (at.main, at.sidebar):
        for el in _walk(root):
            kind = getattr(el, "type", "")
            if kind in ("markdown", "caption", "title", "header", "subheader", "error", "warning", "info", "success"):
                parts.append(str(el.value))
            elif kind == "metric":
                parts.append(f"{el.label} {el.value}")
            elif kind == "progress":
                parts.append(el.proto.text)
            elif kind in ("expander",):
                parts.append(str(el.label))
    return "\n".join(parts).lower()


def rev(at: AppTest) -> int:
    return at.session_state["rev"]


def profile_of(at: AppTest) -> Profile | None:
    return at.session_state["profile"] if "profile" in at.session_state else None
