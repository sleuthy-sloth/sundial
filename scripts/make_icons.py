"""Draw sundial's app icon and write the PNGs the manifest and iOS ask for.

A build-time tool, not a runtime dependency — the PNGs it writes are committed,
so the app never needs Pillow. Re-run only when the mark changes:

    env -u PYTHONPATH backend/.venv/bin/pip install pillow
    env -u PYTHONPATH backend/.venv/bin/python scripts/make_icons.py
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "frontend" / "public"
RING = (253, 250, 245)
FACE = (76, 124, 224)
SHADOW = (255, 206, 152)
STEP = 4  # supersample factor, for edges that survive being a phone icon


def dial(size: int) -> Image.Image:
    px = size * STEP
    img = Image.new("RGB", (px, px), FACE)
    d = ImageDraw.Draw(img)

    centre = px / 2
    outer = px * 0.34
    ring_w = px * 0.035

    d.ellipse(
        [centre - outer, centre - outer, centre + outer, centre + outer],
        outline=RING,
        width=round(ring_w),
    )

    # The wedge is the shadow a real sundial casts: the whole point of the mark.
    d.pieslice(
        [centre - outer + ring_w, centre - outer + ring_w, centre + outer - ring_w, centre + outer - ring_w],
        start=-90,
        end=-30,
        fill=SHADOW,
    )
    d.ellipse(
        [centre - outer, centre - outer, centre + outer, centre + outer],
        outline=RING,
        width=round(ring_w),
    )

    # Twelve hour ticks, so it reads as a day rather than a clock.
    tick_from, tick_to = outer + px * 0.035, outer + px * 0.085
    for hour in range(12):
        angle = math.radians(hour * 30 - 90)
        ca, sa = math.cos(angle), math.sin(angle)
        d.line(
            [
                centre + ca * tick_from,
                centre + sa * tick_from,
                centre + ca * tick_to,
                centre + sa * tick_to,
            ],
            fill=RING,
            width=round(px * 0.018),
        )

    # The gnomon's foot
    foot = px * 0.028
    d.ellipse([centre - foot, centre - foot, centre + foot, centre + foot], fill=RING)

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, size in (
        ("apple-touch-icon.png", 180),
        ("icon-192.png", 192),
        ("icon-512.png", 512),
    ):
        path = OUT / name
        dial(size).save(path, "PNG", optimize=True)
        print(f"  wrote {path.relative_to(OUT.parents[2])} ({size}x{size})")


if __name__ == "__main__":
    main()
