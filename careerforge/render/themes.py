"""Portfolio colour themes. Palettes live here (not in CSS) so tests can check the real contrast ratios."""

from __future__ import annotations

from dataclasses import dataclass

from markupsafe import Markup

from careerforge.render.options import contrast_ratio

SANS = Markup("system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif")
SERIF = Markup("Georgia, 'Times New Roman', Times, serif")
MIN_CONTRAST = 4.5  # WCAG AA for normal-size text


def mix(top: str, base: str, share: float) -> str:
    """`share` of colour `top` laid over `base`, as #rrggbb (what CSS color-mix would give, but computed here so the
    contrast of text on the tinted areas can be tested like every other pair)."""
    out = []
    for i in (1, 3, 5):
        a, b = int(top[i : i + 2], 16), int(base[i : i + 2], 16)
        out.append(round(a * share + b * (1 - share)))
    return "#" + "".join(f"{v:02x}" for v in out)


TINT_SHARE = 0.10  # how much accent colour the tinted bands and chips carry


@dataclass(frozen=True)
class Theme:
    key: str
    label: str
    bg: str
    surface: str
    text: str
    muted: str
    accent: str
    accent_text: str  # text drawn on top of `accent`
    border: str
    font: Markup
    color_scheme: str  # "dark" | "light" | "light dark": tells the browser how to draw form controls and scrollbars
    dark: Theme | None = None  # palette used when the visitor's device prefers dark (the "auto" theme only)

    @property
    def tint(self) -> str:
        """A faint accent wash over the page background: hero bands, chips, avatar rings."""
        return mix(self.accent, self.bg, TINT_SHARE)

    @property
    def shadow(self) -> str:
        strength = "0.35" if self.color_scheme == "dark" else "0.08"
        return f"0 1px 2px rgba(0,0,0,{strength}), 0 10px 28px rgba(0,0,0,{strength})"

    def text_pairs(self) -> list[tuple[str, str, str]]:
        """Every (foreground, background, what) combination the stylesheet draws as text."""
        return [
            (self.text, self.bg, "text on page"),
            (self.text, self.surface, "text on cards"),
            (self.muted, self.bg, "muted text on page"),
            (self.muted, self.surface, "muted text on cards"),
            (self.accent, self.bg, "links on page"),
            (self.accent, self.surface, "links on cards"),
            (self.accent_text, self.accent, "text on accent"),
            (self.text, self.tint, "text on tinted areas"),
            (self.muted, self.tint, "muted text on tinted areas"),
            (self.accent, self.tint, "links on tinted areas"),
        ]

    def worst_contrast(self) -> float:
        worst = min(contrast_ratio(fg, bg) for fg, bg, _ in self.text_pairs())
        return min(worst, self.dark.worst_contrast()) if self.dark else worst


THEMES: dict[str, Theme] = {
    "dark": Theme(
        "dark", "Dark", "#0f172a", "#1e293b", "#e2e8f0", "#a9b6cb", "#7dd3fc", "#0b1220", "#334155", SANS, "dark"
    ),
    "light": Theme(
        "light", "Light", "#ffffff", "#f1f5f9", "#0f172a", "#475569", "#1d4ed8", "#ffffff", "#cbd5e1", SANS, "light"
    ),
    "minimal": Theme(
        key="minimal",
        label="Minimal",
        bg="#fbfaf7",
        surface="#fbfaf7",
        text="#1a1a1a",
        muted="#555555",
        accent="#1a1a1a",
        accent_text="#fbfaf7",
        border="#d9d6cc",
        font=SERIF,
        color_scheme="light",
    ),
}


def with_accent(theme: Theme, accent: str) -> Theme:
    """Theme with a custom accent. Rejects one that cannot be read on this theme's backgrounds. The automatic theme
    has two palettes and, with these backgrounds, no single colour passes on both, so it always refuses."""
    from dataclasses import replace

    if theme.dark is not None:
        try:
            return replace(with_accent(replace(theme, dark=None), accent), dark=with_accent(theme.dark, accent))
        except ValueError as exc:
            raise ValueError(
                "The automatic theme switches between a light and a dark page, and no single colour is readable on "
                "both (checked: 4,096 sample colours, none passed). Choose Light, Dark or Minimal to use your own "
                f"colour. Detail: {exc}"
            ) from exc

    on_accent = "#ffffff" if contrast_ratio("#ffffff", accent) >= contrast_ratio("#000000", accent) else "#000000"
    candidate = replace(theme, accent=accent, accent_text=on_accent)
    for fg, bg, what in candidate.text_pairs():
        if fg == accent or bg == accent:
            if contrast_ratio(fg, bg) < MIN_CONTRAST:
                raise ValueError(
                    f"Accent {accent} is hard to read on the {theme.label} theme ({what}: "
                    f"{contrast_ratio(fg, bg):.1f}:1, needs {MIN_CONTRAST}:1). Choose a different colour"
                )
    return candidate


def _auto() -> Theme:
    from dataclasses import replace

    return replace(
        THEMES["light"], key="auto", label="Automatic (light or dark, like the visitor's device)",
        color_scheme="light dark", dark=THEMES["dark"],
    )  # fmt: skip


THEMES["auto"] = _auto()
