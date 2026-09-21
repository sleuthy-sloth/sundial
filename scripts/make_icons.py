"""Draw sundial's app icon and favicon, and write every size the manifest and iOS ask for.

A build-time tool, not a runtime dependency — everything it writes is committed, so the app never
needs Pillow. Re-run only when the mark changes:

    env -u PYTHONPATH backend/.venv/bin/pip install -r scripts/requirements-art.txt
    env -u PYTHONPATH backend/.venv/bin/python scripts/make_icons.py
    env -u PYTHONPATH backend/.venv/bin/python scripts/make_icons.py --check

The mark is clean geometry, not a traced bitmap. Every number below comes from measuring the
supplied 1024px reference, and is written as a fraction of the dial's outer radius R so the whole
thing scales without carrying a single JPEG artefact:

    ring            outer 1.00R, stroke 0.102R
    ticks           12, thirty degrees apart, radius 0.66R to 0.84R, 0.048R wide, round-capped
    shadow wedge    a 62 degree fan about three o'clock, from behind the gnomon to the ring
    gnomon          a right triangle: vertical edge at +0.182R, hypotenuse back to -0.145R,
                    base at +0.130R, apex at -0.467R
    pedestal        a trapezoid 0.306R wide at the top, 0.402R at the bottom, to +0.326R

The colours are read out of `frontend/src/styles.css` rather than written down twice, so the icon
cannot drift from the ledger it belongs to. Measured against the reference, --text, --bg and
--solar are within a few of its #24251f, #f3eddf and #cf801b, so the tokens preserve the palette
and keep the icon part of the app rather than a picture of it.

TWO LAYOUTS, because a launcher picks the shape, not us:

  * `standard` — the dial at 78% of the canvas, for favicons and anything showing the whole square.
  * `maskable` — the dial at 70%, so the complete ring and every other element sit inside the
    central safe circle, with charcoal still reaching every edge. Android may keep as little as
    the middle 70%, and `--check` measures where the ink actually ends rather than trusting the
    geometry to have worked out.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, cast

from PIL import Image, ImageDraw
from PIL.Image import Resampling

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "frontend" / "public"
STYLES = ROOT / "frontend" / "src" / "styles.css"

UNIT = 100.0  # the SVG viewBox, and the canvas everything else is expressed in
STEP = 4  # supersample factor, so the ring and the tick ends hold their shape at 32px

STANDARD_DIAL = 0.78  # of the canvas width
MASKABLE_DIAL = 0.70  # of the canvas width, clearing Android's 70% safe circle

# the mark, as fractions of the dial's outer radius
RING_STROKE = 0.102
TICK_IN, TICK_OUT, TICK_W = 0.66, 0.84, 0.048
WEDGE_HALF_DEG = 31.0
FIN = ((-0.145, 0.130), (0.182, 0.130), (0.182, -0.467))  # right triangle, leaning right
PLINTH = ((-0.306, 0.130), (0.306, 0.130), (0.402, 0.326), (-0.402, 0.326))
PLINTH_ROUND = 0.017  # the reference's corners are very slightly rounded


def tokens() -> dict[str, str]:
    """Pull the light-theme colours out of the stylesheet's :root block."""
    css = STYLES.read_text(encoding="utf-8")
    block = re.search(r":root\s*\{(.*?)\}", css, re.S)
    if not block:
        raise SystemExit(f"no :root block found in {STYLES}")
    wanted: dict[str, str] = {}
    for name in ("--bg", "--text", "--solar"):
        m = re.search(rf"{name}\s*:\s*(#[0-9a-fA-F]{{6}})", block.group(1))
        if not m:
            raise SystemExit(f"{name} is not a plain hex colour in {STYLES} — the icon reads it")
        wanted[name] = m.group(1)
    return wanted


def rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def radius(dial: float) -> float:
    """The dial's outer radius, in canvas units."""
    return UNIT * dial / 2


def scaled(shape: tuple[tuple[float, float], ...], r: float) -> list[tuple[float, float]]:
    """A shape given in units of R, placed on the canvas."""
    return [(UNIT / 2 + x * r, UNIT / 2 + y * r) for x, y in shape]


def wedge_path(r: float) -> str:
    """The shadow, as a truncated sector: from behind the gnomon out to the ring's inner edge.

    A path rather than a fan of pixels, so it is the same shape at 32px and at 512px. Its inner
    edge is hidden behind the gnomon, which is how the reference builds it too.
    """
    inner, outer = 0.18 * r, r * (1 - RING_STROKE)
    c = UNIT / 2
    a0, a1 = math.radians(-WEDGE_HALF_DEG), math.radians(WEDGE_HALF_DEG)
    p0 = (c + inner * math.cos(a0), c + inner * math.sin(a0))
    p1 = (c + outer * math.cos(a0), c + outer * math.sin(a0))
    p2 = (c + outer * math.cos(a1), c + outer * math.sin(a1))
    p3 = (c + inner * math.cos(a1), c + inner * math.sin(a1))
    arc = lambda r_, a, sweep: f"A {r_:.3f} {r_:.3f} 0 0 {sweep} {c + r_ * math.cos(a):.3f} {c + r_ * math.sin(a):.3f}"
    return (
        f"M {p0[0]:.3f} {p0[1]:.3f} L {p1[0]:.3f} {p1[1]:.3f} {arc(outer, a1, 1)} "
        f"L {p3[0]:.3f} {p3[1]:.3f} {arc(inner, a0, 0)} Z"
    )


def svg(dial: float, ink: str, paper: str, amber: str) -> str:
    """The mark as SVG — the same geometry the PNGs below are drawn from, written once."""
    r = radius(dial)
    ring_r = r * (1 - RING_STROKE / 2)
    tick_w = TICK_W * r
    c = UNIT / 2
    ticks = []
    for hour in range(12):
        a = math.radians(hour * 30 - 90)  # twelve at the top, clockwise like a dial
        ca, sa = math.cos(a), math.sin(a)
        ticks.append(
            f'<line x1="{c + ca * TICK_IN * r:.3f}" y1="{c + sa * TICK_IN * r:.3f}"'
            f' x2="{c + ca * TICK_OUT * r:.3f}" y2="{c + sa * TICK_OUT * r:.3f}"/>'
        )
    fin = " ".join(f"{x:.3f},{y:.3f}" for x, y in scaled(FIN, r))
    plinth = " ".join(f"{x:.3f},{y:.3f}" for x, y in scaled(PLINTH, r))
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {UNIT:g} {UNIT:g}" role="img" aria-label="sundial">
  <!-- A dial, the gnomon that stands on it, and the shadow that gnomon casts. Clean geometry
       only: nothing here is traced. The colours are this app's own ink, parchment and amber. -->
  <rect width="{UNIT:g}" height="{UNIT:g}" fill="{ink}"/>
  <path d="{wedge_path(r)}" fill="{amber}"/>
  <polygon points="{fin}" fill="{paper}"/>
  <polygon points="{plinth}" fill="{paper}" stroke="{paper}"
           stroke-width="{PLINTH_ROUND * r:.3f}" stroke-linejoin="round"/>
  <g stroke="{paper}" stroke-width="{tick_w:.3f}" stroke-linecap="round">
    {''.join(ticks)}
  </g>
  <circle cx="{c:g}" cy="{c:g}" r="{ring_r:.3f}" fill="none" stroke="{paper}"
          stroke-width="{RING_STROKE * r:.3f}"/>
</svg>
"""


def draw(size: int, dial: float, ink: tuple[int, int, int], paper: tuple[int, int, int],
         amber: tuple[int, int, int]) -> Image.Image:
    """Rasterise the same geometry: the PNGs and the SVG cannot disagree because the numbers are
    shared. Drawn at STEP times the size and reduced, so edges stay crisp."""
    px = size * STEP
    k = px / UNIT  # units to pixels, applied in exactly one place
    img = Image.new("RGB", (px, px), ink)
    d = ImageDraw.Draw(img)
    r = radius(dial)
    c = UNIT / 2 * k

    def dot(x: float, y: float) -> tuple[float, float]:
        return (x * k, y * k)

    # the shadow under everything: the gnomon stands on its own wedge, as in the reference
    outer = r * (1 - RING_STROKE) * k
    d.pieslice([c - outer, c - outer, c + outer, c + outer],
               start=-WEDGE_HALF_DEG, end=WEDGE_HALF_DEG, fill=amber)

    d.polygon([dot(x, y) for x, y in scaled(FIN, r)], fill=paper)
    d.polygon([dot(x, y) for x, y in scaled(PLINTH, r)], fill=paper)

    tick_w = max(1.0, TICK_W * r * k)
    for hour in range(12):
        a = math.radians(hour * 30 - 90)
        ca, sa = math.cos(a), math.sin(a)
        x1, y1 = dot(UNIT / 2 + ca * TICK_IN * r, UNIT / 2 + sa * TICK_IN * r)
        x2, y2 = dot(UNIT / 2 + ca * TICK_OUT * r, UNIT / 2 + sa * TICK_OUT * r)
        d.line([x1, y1, x2, y2], fill=paper, width=max(1, round(tick_w)))
        # round caps, which Pillow's line() does not give: the SVG has them, so the PNG should too
        for x, y in ((x1, y1), (x2, y2)):
            d.ellipse([x - tick_w / 2, y - tick_w / 2, x + tick_w / 2, y + tick_w / 2], fill=paper)

    # Pillow grows a wide outline inward from the box it is given, so the box radius IS the
    # ring's outer edge — the opposite of SVG, where the stroke straddles the path and the
    # circle therefore sits half a stroke in. Same geometry, two conventions.
    stroke = RING_STROKE * r * k
    ring_outer = r * k
    d.ellipse([c - ring_outer, c - ring_outer, c + ring_outer, c + ring_outer],
              outline=paper, width=max(1, round(stroke)))
    return img.resize((size, size), Resampling.LANCZOS)


def writes() -> list[tuple[str, int, str]]:
    """Every file it writes: name, size, and which layout."""
    return [
        ("icon-32.png", 32, "standard"),
        ("icon-48.png", 48, "standard"),
        ("icon-180.png", 180, "standard"),
        ("apple-touch-icon.png", 180, "standard"),
        ("icon-192.png", 192, "standard"),
        ("icon-512.png", 512, "standard"),
        ("icon-maskable-192.png", 192, "maskable"),
        ("icon-maskable-512.png", 512, "maskable"),
    ]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    t = tokens()
    ink, paper, amber = rgb(t["--text"]), rgb(t["--bg"]), rgb(t["--solar"])
    for name, size, layout in writes():
        dial = STANDARD_DIAL if layout == "standard" else MASKABLE_DIAL
        draw(size, dial, ink, paper, amber).save(OUT / name, "PNG", optimize=True)
        print(f"  wrote {name} ({size}x{size}, dial at {dial:.0%} of the canvas)")

    (OUT / "favicon.svg").write_text(
        svg(STANDARD_DIAL, t["--text"], t["--bg"], t["--solar"]), encoding="utf-8"
    )
    print(f"  wrote favicon.svg (vector, dial at {STANDARD_DIAL:.0%})")
    print(f"  colours from styles.css: charcoal {t['--text']}, parchment {t['--bg']}, amber {t['--solar']}")


def reach(img: Image.Image, ground: tuple[int, int, int], tol: int = 24) -> float:
    """How far the mark reaches from the centre, as a fraction of the canvas width.

    Measured on the pixels rather than assumed from the geometry: what a launcher's mask cares
    about is where the ink actually ends, antialiasing and all.
    """
    size = img.size[0]
    px = cast(Any, img.convert("RGB").load())  # Pillow's stub calls this optional; it is not
    centre = size / 2
    far = 0.0
    for y in range(size):
        for x in range(size):
            p = px[x, y]
            if max(abs(p[i] - ground[i]) for i in range(3)) > tol:
                far = max(far, math.hypot(x + 0.5 - centre, y + 0.5 - centre))
    return far / size


def verify() -> int:
    """Check what is committed: every size present, each layout sized as promised, the maskable
    mark inside Android's safe circle, and charcoal still reaching all four of its edges."""
    t = tokens()
    ink = rgb(t["--text"])
    problems: list[str] = []

    for name, size, layout in writes():
        path = OUT / name
        if not path.exists():
            problems.append(f"{name} is missing")
            continue
        with Image.open(path) as im:
            if im.size != (size, size):
                problems.append(f"{name} is {im.size[0]}x{im.size[1]}, expected {size}x{size}")
                continue
            if im.getexif():
                problems.append(f"{name} carries EXIF metadata")
            got = reach(im, ink)
            want = (STANDARD_DIAL if layout == "standard" else MASKABLE_DIAL) / 2
            # one pixel is 3% of a 32px icon, so the tolerance has to be the size's own
            # granularity rather than a constant that only works at 512
            if abs(got - want) > max(0.008, 1.5 / size):
                problems.append(
                    f"{name}: the mark reaches {got:.3f} of the width, expected about {want:.3f} "
                    f"for the {layout} layout"
                )
            if layout == "maskable":
                if got > 0.355:
                    problems.append(
                        f"{name}: the mark reaches {got:.3f}, outside Android's 70% safe circle "
                        f"(0.350) — a mask would take the edge of the ring"
                    )
                else:
                    print(f"  {name}: mark reaches {got:.3f} of the width (safe circle 0.350)")
                px = cast(Any, im.convert("RGB").load())
                for x, y in ((0, 0), (size - 1, 0), (0, size - 1), (size - 1, size - 1)):
                    if max(abs(px[x, y][i] - ink[i]) for i in range(3)) > 6:
                        problems.append(f"{name}: the corner at {x},{y} is not solid charcoal")
                        break
            else:
                print(f"  {name}: mark reaches {got:.3f} of the width ({layout})")

    svg_path = OUT / "favicon.svg"
    if not svg_path.exists():
        problems.append("favicon.svg is missing")
    else:
        text = svg_path.read_text(encoding="utf-8")
        for needed, why in (
            ("viewBox", "it is not a scalable vector"),
            ("<circle", "it has no dial ring"),
            ("<polygon", "it has no gnomon or pedestal"),
            ("<path", "it has no shadow wedge"),
        ):
            if needed not in text:
                problems.append(f"favicon.svg: {why} ({needed!r} not found)")
        if text.count("<line") != 12:
            problems.append(f"favicon.svg has {text.count('<line')} ticks, expected 12")
        try:
            import xml.etree.ElementTree as ET

            ET.fromstring(text)
        except Exception as exc:  # noqa: BLE001 — a malformed favicon fails silently in a browser
            problems.append(f"favicon.svg is not well-formed XML: {exc}")
        if not problems:
            print("  favicon.svg: 12 ticks, ring, gnomon, pedestal, wedge, well-formed")

    if problems:
        print("\nicon problems:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("all sizes present, both layouts inside their safe zones, favicon checks out")
    return 0


if __name__ == "__main__":
    import sys

    if "--check" in sys.argv:
        raise SystemExit(verify())
    main()
