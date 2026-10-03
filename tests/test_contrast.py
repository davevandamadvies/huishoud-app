"""Tekstcontrast van de kleurtokens (ontwerpeis: minimaal 4.5:1)."""

import re
from pathlib import Path

import pytest

CSS = (Path(__file__).resolve().parent.parent / "app/static/css/app.css").read_text()
TOKENS = dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})", CSS))


def _luminance(hex_color: str) -> float:
    channels = [int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = (
        c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels
    )
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(fg: str, bg: str) -> float:
    high, low = sorted((_luminance(fg), _luminance(bg)), reverse=True)
    return (high + 0.05) / (low + 0.05)


@pytest.mark.parametrize(
    ("fg", "bg"),
    [
        ("color-text", "color-bg"),
        ("color-text", "color-surface"),
        ("color-text-muted", "color-bg"),
        ("color-text-muted", "color-surface"),
        ("color-nav", "color-surface"),
        ("color-accent", "color-bg"),
        ("color-accent", "color-surface"),
        ("color-accent", "color-accent-soft"),
        ("color-on-accent", "color-accent"),
        ("color-on-accent", "color-chip-active"),
        ("color-late", "color-bg"),
        ("color-late", "color-surface"),
        ("avatar-1-fg", "avatar-1-bg"),
        ("avatar-2-fg", "avatar-2-bg"),
        ("avatar-3-fg", "avatar-3-bg"),
        ("avatar-4-fg", "avatar-4-bg"),
        ("avatar-5-fg", "avatar-5-bg"),
        ("avatar-6-fg", "avatar-6-bg"),
        ("color-error", "color-error-soft"),
        ("color-error", "color-surface"),
        ("color-accent", "color-success-soft"),
    ],
)
def test_text_contrast(fg: str, bg: str) -> None:
    assert contrast(TOKENS[fg], TOKENS[bg]) >= 4.5


def test_check_border_contrast() -> None:
    assert contrast(TOKENS["color-check-border"], TOKENS["color-surface"]) >= 3


def test_category_palette_has_css_and_contrast() -> None:
    from app.palette import CATEGORY_COLORS

    for key, (_label, hex_color) in CATEGORY_COLORS.items():
        assert f".cat-{key} {{\n  background: {hex_color};" in CSS, key
        # Niet-tekstelement (bolletje): minimaal 3:1 op wit
        assert contrast(hex_color, TOKENS["color-surface"]) >= 3, key
