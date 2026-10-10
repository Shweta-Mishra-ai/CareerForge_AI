"""Portfolio colour themes. Palettes live here (not in CSS) so tests can check the real contrast ratios."""

from __future__ import annotations

from dataclasses import dataclass

from markupsafe import Markup

from careerforge.render.options import contrast_ratio

SANS = Markup("system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif")
SERIF = Markup("Georgia, 'Times New Roman', Times, serif")
MIN_CONTRAST = 4.5  # WCAG AA for normal-size text


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
    color_scheme: str  # "dark" | "light": tells the browser how to draw form controls and scrollbars

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
        ]

    def worst_contrast(self) -> float:
        return min(contrast_ratio(fg, bg) for fg, bg, _ in self.text_pairs())


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
    """Theme with a custom accent. Rejects one that cannot be read on this theme's backgrounds."""
    from dataclasses import replace

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
