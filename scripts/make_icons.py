"""Draw sundial's app icon and write the PNGs and the favicon the manifest and iOS ask for.

A build-time tool, not a runtime dependency — the icons it writes are committed, so the app
never needs Pillow. Re-run only when the mark changes:

    env -u PYTHONPATH backend/.venv/bin/pip install -r scripts/requirements-art.txt
    env -u PYTHONPATH backend/.venv/bin/python scripts/make_icons.py
    env -u PYTHONPATH backend/.venv/bin/python scripts/make_icons.py --check

The colours are read out of `frontend/src/styles.css` rather than written down twice, so the
icon cannot drift away from the ledger it belongs to. The mark itself is unchanged: a dial, an
hour ring, and the wedge a gnomon casts — the one filled shape, and the reason it is a sundial
rather than a clock.

Two things the icon has to survive that a screenshot does not:

  * Android's maskable crop, which may keep only the middle 80% of the square. The maskable
    files draw the same mark inset by `MASK_INSET`, so no part of the dial reaches the crop.
  * Being 16px wide in a tab. The favicon is vector, and follows the reader's colour scheme
    the way the app does, so it is legible on light and dark browser chrome.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

from PIL import Image, ImageDraw
from PIL.Image import Resampling

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "frontend" / "public"
STYLES = ROOT / "frontend" / "src" / "styles.css"

STEP = 4  # supersample factor, for edges that survive being a phone icon
MASK_INSET = 0.78  # maskable safe zone: the mark must fit inside the middle 80%

# the same shape, in the 100-unit space the SVG favicon uses
SVG_UNITS = 100
OUTER = 0.34  # dial radius, as a fraction of the canvas
RING_W = 0.035
TICK_FROM, TICK_TO = 0.375, 0.425  # ticks sit just outside the rim
FOOT = 0.028
WEDGE = (-90, -30)  # the gnomon's shadow, clockwise from twelve


def tokens() -> dict[str, str]:
    """Pull the light-theme colours out of the stylesheet's :root block."""
    css = STYLES.read_text(encoding="utf-8")
    block = re.search(r":root\s*\{(.*?)\}", css, re.S)
    if not block:
        raise SystemExit(f"no :root block found in {STYLES}")
    wanted: dict[str, str] = {}
    for name in ("--bg", "--text", "--solar", "--solar-mark"):
        m = re.search(rf"{name}\s*:\s*(#[0-9a-fA-F]{{6}})", block.group(1))
        if not m:
            raise SystemExit(f"{name} is not a plain hex colour in {STYLES} — icon colours are read from it")
        wanted[name] = m.group(1)
    return wanted


def rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def dial(size: int, ground: tuple[int, int, int], ring: tuple[int, int, int],
         wedge: tuple[int, int, int], inset: float = 1.0) -> Image.Image:
    px = size * STEP
    img = Image.new("RGB", (px, px), ground)
    d = ImageDraw.Draw(img)
    s = px * inset  # the drawing is scaled about the centre, so inset never moves the mark

    centre = px / 2
    outer = s * OUTER
    ring_w = s * RING_W

    box = [centre - outer, centre - outer, centre + outer, centre + outer]
    d.ellipse(box, outline=ring, width=round(ring_w))

    # The wedge is the shadow a real sundial casts: the whole point of the mark, and the only
    # filled shape. It is the fill colour in the palette, never a stroke.
    d.pieslice(
        [box[0] + ring_w, box[1] + ring_w, box[2] - ring_w, box[3] - ring_w],
        start=WEDGE[0],
        end=WEDGE[1],
        fill=wedge,
    )
    d.ellipse(box, outline=ring, width=round(ring_w))

    # Twelve hour ticks, so it reads as a day rather than a clock.
    tick_from, tick_to = s * TICK_FROM, s * TICK_TO
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
            fill=ring,
            width=round(s * 0.018),
        )

    # The gnomon's foot
    foot = s * FOOT
    d.ellipse([centre - foot, centre - foot, centre + foot, centre + foot], fill=ring)

    return img.resize((size, size), Resampling.LANCZOS)


def dial_on_paper(size: int, ink: tuple[int, int, int], paper: tuple[int, int, int],
                  wedge: tuple[int, int, int]) -> Image.Image:
    """A dial cut out of paper rather than sitting on a filled square: legible as a favicon on
    light browser chrome and on dark, where a plain ink square would vanish."""
    px = size * STEP
    img = Image.new("RGB", (px, px), paper)
    d = ImageDraw.Draw(img)
    centre = px / 2
    outer = px * 0.44
    ring_w = px * 0.05

    d.pieslice(
        [centre - outer + ring_w, centre - outer + ring_w, centre + outer - ring_w, centre + outer - ring_w],
        start=WEDGE[0],
        end=WEDGE[1],
        fill=wedge,
    )
    d.ellipse([centre - outer, centre - outer, centre + outer, centre + outer], outline=ink, width=round(ring_w))
    for hour in (0, 3, 6, 9):
        angle = math.radians(hour * 30 - 90)
        ca, sa = math.cos(angle), math.sin(angle)
        d.line(
            [centre + ca * (outer - ring_w), centre + sa * (outer - ring_w),
             centre + ca * (outer - ring_w * 2.4), centre + sa * (outer - ring_w * 2.4)],
            fill=ink,
            width=round(px * 0.035),
        )
    foot = px * 0.045
    d.ellipse([centre - foot, centre - foot, centre + foot, centre + foot], fill=ink)
    return img.resize((size, size), Resampling.LANCZOS)


def favicon_svg(ink: str, paper: str, wedge: str) -> str:
    """The same dial, in vector, following the reader's colour scheme."""
    u = SVG_UNITS
    c = u / 2
    outer = u * OUTER
    ring_w = u * RING_W
    ticks = []
    for hour in range(12):
        angle = math.radians(hour * 30 - 90)
        ca, sa = math.cos(angle), math.sin(angle)
        ticks.append(
            f'<line x1="{c + ca * u * TICK_FROM:.2f}" y1="{c + sa * u * TICK_FROM:.2f}"'
            f' x2="{c + ca * u * TICK_TO:.2f}" y2="{c + sa * u * TICK_TO:.2f}"/>'
        )
    # the wedge, as a path: from the centre, up to twelve, round to one o'clock
    a0, a1 = math.radians(WEDGE[0] - 90), math.radians(WEDGE[1] - 90)
    r = outer - ring_w / 2
    wedge_path = (
        f"M {c} {c} L {c + math.cos(a0) * r:.2f} {c + math.sin(a0) * r:.2f} "
        f"A {r:.2f} {r:.2f} 0 0 1 {c + math.cos(a1) * r:.2f} {c + math.sin(a1) * r:.2f} Z"
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {u} {u}" role="img" aria-label="sundial">
  <!-- The app's own mark, in vector: a dial with the gnomon's shadow filled. Follows the
       reader's colour scheme, like the app does, so it reads on light and dark chrome. -->
  <style>
    .ground {{ fill: {paper}; }}
    .mark {{ stroke: {ink}; }}
    .wedge {{ fill: {wedge}; }}
    @media (prefers-color-scheme: dark) {{
      .ground {{ fill: {ink}; }}
      .mark {{ stroke: {paper}; }}
    }}
  </style>
  <rect class="ground" width="{u}" height="{u}" rx="{u * 0.18:.1f}"/>
  <path class="wedge" d="{wedge_path}"/>
  <g class="mark" fill="none" stroke-width="{ring_w:.2f}">
    <circle cx="{c}" cy="{c}" r="{outer - ring_w / 2:.2f}"/>
    <g stroke-width="{u * 0.018:.2f}">{''.join(ticks)}</g>
  </g>
  <circle class="mark" cx="{c}" cy="{c}" r="{u * FOOT:.2f}" fill="currentColor"/>
</svg>
"""


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    t = tokens()
    ink, paper, wedge = rgb(t["--text"]), rgb(t["--bg"]), rgb(t["--solar"])

    # the app icon: the mark on ink, with the parchment ring, as it reads in the ledger
    for name, size, inset in (
        ("apple-touch-icon.png", 180, 1.0),
        ("icon-192.png", 192, 1.0),
        ("icon-512.png", 512, 1.0),
        # the maskable pair draws the mark inset, so Android's crop cannot take the ticks
        ("icon-maskable-192.png", 192, MASK_INSET),
        ("icon-maskable-512.png", 512, MASK_INSET),
    ):
        path = OUT / name
        dial(size, ink, paper, wedge, inset).save(path, "PNG", optimize=True)
        print(f"  wrote {path.name} ({size}x{size}{', inset for maskable' if inset != 1.0 else ''})")

    fav = OUT / "favicon-32.png"
    dial_on_paper(32, ink, paper, wedge).save(fav, "PNG", optimize=True)
    print(f"  wrote {fav.name} (32x32)")

    svg = OUT / "favicon.svg"
    svg.write_text(favicon_svg(t["--text"], t["--bg"], t["--solar"]), encoding="utf-8")
    print(f"  wrote {svg.name} (vector, follows prefers-color-scheme)")
    print(f"  colours read from styles.css: ground {t['--text']}, ring {t['--bg']}, wedge {t['--solar']}")


def verify() -> int:
    """Check the committed icons: right sizes, and the maskable ones inside Android's crop.

    Android may keep only the middle 80% of a maskable square, as a circle. So every pixel
    that is not the background has to sit inside a circle of radius 0.4 * size — measured,
    not assumed, because a mark that merely looks centred can still lose its ticks.
    """
    t = tokens()
    ground = rgb(t["--text"])
    problems: list[str] = []

    for name, size, maskable in (
        ("apple-touch-icon.png", 180, False),
        ("icon-192.png", 192, False),
        ("icon-512.png", 512, False),
        ("icon-maskable-192.png", 192, True),
        ("icon-maskable-512.png", 512, True),
        ("favicon-32.png", 32, False),
    ):
        path = OUT / name
        if not path.exists():
            problems.append(f"{name} is missing")
            continue
        with Image.open(path) as im:
            if im.size != (size, size):
                problems.append(f"{name} is {im.size[0]}x{im.size[1]}, expected {size}x{size}")
                continue
            if not maskable:
                continue
            # the widest reach of anything that is not the background
            px = im.convert("RGB").load()
            centre = size / 2
            reach = 0.0
            for y in range(size):
                for x in range(size):
                    p = px[x, y]
                    if max(abs(p[i] - ground[i]) for i in range(3)) > 24:
                        reach = max(reach, math.hypot(x + 0.5 - centre, y + 0.5 - centre))
            allowed = size * 0.4  # the safe circle
            if reach > allowed:
                problems.append(
                    f"{name}: the mark reaches {reach / size:.3f} of the width from the centre, "
                    f"outside the maskable safe circle ({allowed / size:.3f})"
                )
            else:
                print(f"  {name}: mark reaches {reach / size:.3f} of the width (safe zone {allowed / size:.2f})")
            if im.getexif():
                problems.append(f"{name} carries EXIF metadata")

    svg = OUT / "favicon.svg"
    if not svg.exists():
        problems.append("favicon.svg is missing")
    else:
        text = svg.read_text(encoding="utf-8")
        for needed, why in (
            ("prefers-color-scheme: dark", "it does not follow the reader's colour scheme"),
            ("viewBox", "it is not a scalable vector"),
        ):
            if needed not in text:
                problems.append(f"favicon.svg: {why} ({needed!r} not found)")
        try:
            import xml.etree.ElementTree as ET

            ET.fromstring(text)
        except Exception as exc:  # noqa: BLE001 — a malformed favicon fails silently in a browser
            problems.append(f"favicon.svg is not well-formed XML: {exc}")

    if problems:
        print("\nicon problems:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("all icons present, sized, and clear of the maskable crop")
    return 0


if __name__ == "__main__":
    import sys

    if "--check" in sys.argv:
        raise SystemExit(verify())
    main()
