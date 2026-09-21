"""The eight colours a calendar can be, and how a foreign colour lands on one.

This is shared by both transports and belongs to neither. A calendar arrives from iCloud or
from Google carrying whatever colour somebody picked there, and sundial has eight — because
those eight are a *validated app colour*, drawn in styles.css as `.c-<name>` with a
dark-theme pair and a contrast-checked edge, not a style choice a sync gets to invent. A
ninth colour made up on the spot would have neither.

The matching is hue first, then lightness, which took four attempts:

    Distance in RGB put Apple's red (#FF3B30) on amber.
    So did redmean.
    So did plain Euclidean distance in Lab — defensible arithmetic, wrong to look at.

Rose is a dark *desaturated* brick, so in every one of those spaces its numbers sit nearer a
brown-gold than a vivid red does. Red's hue is 32 degrees and rose's is 25; amber's is 80.
Hue is the thing the person picking a colour meant.

test_caldav.py asserts PALETTE_RGB still matches the stylesheet, because the mapping is only
honest while the two agree.
"""

from __future__ import annotations

import math
from typing import Optional

# The eight palette names with the edge colour each is drawn in, light theme, from
# styles.css (.c-<name>).
PALETTE_RGB: dict[str, tuple[int, int, int]] = {
    "slate": (0x4E, 0x65, 0x77),
    "sky": (0x3F, 0x6B, 0x8A),
    "violet": (0x6A, 0x5A, 0x86),
    "amber": (0x96, 0x70, 0x2A),
    "emerald": (0x4A, 0x73, 0x58),
    "rose": (0x8D, 0x5A, 0x5A),
    "teal": (0x3F, 0x73, 0x73),
    "indigo": (0x4F, 0x56, 0x87),
}


def _hex_to_rgb(value: str) -> Optional[tuple[int, int, int]]:
    text = value.strip().lstrip("#")
    if len(text) == 8:  # iCloud sends #RRGGBBAA; Google sends #RRGGBB
        text = text[:6]
    if len(text) != 6:
        return None
    try:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except ValueError:
        return None


def _lab(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    """sRGB to CIE Lab under a D65 white point. Twenty lines, no dependency."""

    def to_linear(channel: int) -> float:
        c = channel / 255
        return ((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92

    r, g, b = (to_linear(v) for v in rgb)
    x = (r * 0.4124 + g * 0.3576 + b * 0.1805) / 0.95047
    y = r * 0.2126 + g * 0.7152 + b * 0.0722
    z = (r * 0.0193 + g * 0.1192 + b * 0.9505) / 1.08883
    f = lambda t: t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116  # noqa: E731
    fx, fy, fz = f(x), f(y), f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def _colour_distance(rgb: tuple[int, int, int], other: tuple[int, int, int]) -> float:
    """Hue first, then lightness — because that is how a colour is named."""
    light, a1, b1 = _lab(rgb)
    other_light, a2, b2 = _lab(other)
    chroma, other_chroma = math.hypot(a1, b1), math.hypot(a2, b2)
    if min(chroma, other_chroma) < 6:
        # Almost grey: there is no hue to compare, so everything is far away and the
        # least colourful entry wins — which is what grey should do.
        return 100 + abs(light - other_light) + abs(chroma - other_chroma)
    turn = abs(math.atan2(b1, a1) - math.atan2(b2, a2))
    hue = math.degrees(min(turn, 2 * math.pi - turn))
    return hue + 0.25 * abs(light - other_light)


def nearest_colour(value: Optional[str]) -> str:
    """The palette name closest to a calendar's own colour."""
    rgb = _hex_to_rgb(value) if value else None
    if rgb is None:
        return "slate"
    return min(PALETTE_RGB, key=lambda name: _colour_distance(rgb, PALETTE_RGB[name]))
