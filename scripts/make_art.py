"""Turn the source artwork in art/source/ into the files the app and the README ship.

A build-time tool, not a runtime dependency — the derivatives are committed, so the app
never needs Pillow. Re-run only when the source art changes:

    env -u PYTHONPATH backend/.venv/bin/pip install -r scripts/requirements-art.txt
    env -u PYTHONPATH backend/.venv/bin/python scripts/make_art.py           # write them
    env -u PYTHONPATH backend/.venv/bin/python scripts/make_art.py --check   # verify the budgets

The check runs in CI. It is the same ladder the writer uses, applied to what is committed,
so a derivative that drifts out of its budget fails the build instead of shipping.

Budgets come from the art brief: 800px wide and 60KB each for the empty states, 1200x630
and 200KB for the social card, 2560x320 for the README banner. Quality is not fixed — the
ladder takes the highest quality that still fits, because flat line art with paper grain
costs more to encode than a photograph does.

Light and dark are measured as a pair: same pixel dimensions or the page shifts when the
theme changes, and same budget or one theme ships a heavier file for no reason.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import re

from PIL import Image, ImageChops, ImageFilter
from PIL.Image import Resampling

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "art" / "source"
STYLES = ROOT / "frontend" / "src" / "styles.css"
RUNTIME = ROOT / "frontend" / "src" / "assets"
BRAND = ROOT / "frontend" / "public" / "brand"

EMPTY_W = 800
EMPTY_BUDGET = 60 * 1024
OG_SIZE = (1200, 630)
OG_BUDGET = 200 * 1024
BANNER_SIZE = (2560, 320)
BANNER_BUDGET = 150 * 1024

# source pairs -> the runtime names the app imports
PAIRS = {
    "empty-timeline": "sundial",
    "empty-inbox": "inbox-tray",
    "day-complete": "day-complete",
}
QUALITY_LADDER = (88, 84, 80, 76, 72, 68, 64)


# Which surface each picture is actually placed on. The tray lives in the inbox rail, which is a
# panel (--surface) and measurably lighter than the page; the dial sits on the timeline canvas and
# the low sun at the foot of the plan, both of which are the page ground (--bg). Getting this
# wrong is not subtle: the artwork shows as a rectangle of the wrong beige.
SURFACES = {
    "empty-timeline": "--bg",
    "empty-inbox": "--surface",
    "day-complete": "--bg",
}

# The one pair whose background is not plain: the dial sits on the hour rules, so its ground is
# keyed out rather than colour-matched. The tray is on the rail and the low sun at the foot of
# the plan, both flat, and they keep the artist's own paper texture.
TRANSPARENT = {"empty-timeline"}


def theme_grounds() -> dict[str, dict[str, tuple[int, int, int]]]:
    """The theme colours each picture has to match, read from the stylesheet."""
    css = STYLES.read_text(encoding="utf-8")
    out: dict[str, dict[str, tuple[int, int, int]]] = {}
    for theme, pattern in (
        ("light", r":root\s*\{(.*?)\}"),
        ("dark", r"\[data-theme='dark'\]\s*\{(.*?)\}"),
    ):
        block = re.search(pattern, css, re.S)
        if not block:
            sys.exit(f"could not find the {theme} theme block in {STYLES}")
        colours: dict[str, tuple[int, int, int]] = {}
        for token in ("--bg", "--surface"):
            m = re.search(rf"{token}\s*:\s*#([0-9a-fA-F]{{6}})", block.group(1))
            if not m:
                sys.exit(f"no plain hex {token} in the {theme} theme block")
            hexed = m.group(1)
            colours[token] = tuple(int(hexed[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[assignment]
        out[theme] = colours
    return out


def corners(img: Image.Image) -> tuple[int, int, int]:
    """The flat colour the picture was drawn on: the mean of its four corners, where nothing
    is ever drawn."""
    img = img.convert("RGB")
    w, h = img.size
    box = max(4, min(w, h) // 32)
    strips = [
        img.crop((0, 0, box, box)),
        img.crop((w - box, 0, w, box)),
        img.crop((0, h - box, box, h)),
        img.crop((w - box, h - box, w, h)),
    ]
    total = [0.0, 0.0, 0.0]
    for s in strips:
        for i, v in enumerate(s.resize((1, 1), Resampling.BOX).getpixel((0, 0))):
            total[i] += v / len(strips)
    return tuple(round(v) for v in total)  # type: ignore[return-value]


def reground(img: Image.Image, target: tuple[int, int, int], tolerance: int = 40) -> Image.Image:
    """Move the artwork's own ground colour onto the page's, leaving the drawing alone.

    The supplied illustrations are drawn on their own ground — the dark ones on a warm charcoal
    about 15/255 lighter than this app's dark ground — so dropping them straight onto the canvas
    would show a rectangle. A flat shift of the whole picture would falsify the amber; a shift
    of the ground only is what a designer would do with levels.

    The weight comes from the picture itself: a pixel identical to the original ground moves all
    the way, a pixel 40/255 away or more does not move at all, and the ramp between them is
    blurred so an edge cannot show. Paper grain is preserved, because a grain pixel is a few
    units from the ground and moves with it.
    """
    source = corners(img)
    delta = [target[i] - source[i] for i in range(3)]
    if not any(delta):
        return img

    luts = []
    for d in delta:
        luts.append([max(0, min(255, v + d)) for v in range(256)])
    shifted = img.point(luts[0] + luts[1] + luts[2])

    ground_img = Image.new("RGB", img.size, source)
    diff = ImageChops.difference(img, ground_img).convert("L")
    mask = diff.point([max(0, min(255, round(255 * (1 - v / tolerance)))) for v in range(256)])
    mask = mask.filter(ImageFilter.GaussianBlur(1.2))
    return Image.composite(shifted, img, mask)


def key_ground(img: Image.Image, ground: tuple[int, int, int], noise: int = 22, tolerance: int = 48) -> Image.Image:
    """Make the artwork's own ground transparent, so whatever is behind it shows through.

    Only the empty timeline needs this. Its picture sits on the hour rules, and an opaque — even
    perfectly colour-matched — rectangle cuts them off on both sides, which reads as a hole
    punched in the ruler. With the ground keyed out the rules run underneath the drawing.

    The weight is the same distance-from-the-ground idea the reground uses, with a floor: paper
    grain is within a couple of units of the ground, so it becomes fully transparent instead of
    a haze of near-zero alpha, which is both invisible and expensive to encode.
    """
    diff = ImageChops.difference(img, Image.new("RGB", img.size, ground)).convert("L")
    lut = [
        0 if v <= noise else min(255, round(255 * (v - noise) / (tolerance - noise)))
        for v in range(256)
    ]
    alpha = diff.point(lut).filter(ImageFilter.GaussianBlur(0.6))
    out = img.convert("RGBA")
    out.putalpha(alpha)
    return out


def open_source(name: str) -> Image.Image:
    path = SOURCE / f"{name}.jpg"
    if not path.exists():
        sys.exit(f"missing source art: {path}")
    # .convert drops the JPEG's metadata along with its mode
    return Image.open(path).convert("RGB")


def fit_to_width(img: Image.Image, width: int) -> Image.Image:
    height = round(width * img.height / img.width)
    return img.resize((width, height), Resampling.LANCZOS)


def fit_ratio(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Crop to the target ratio, then resize. Never stretches: the longer side is trimmed."""
    want = size[0] / size[1]
    have = img.width / img.height
    if have > want:
        keep = round(img.height * want)
        left = (img.width - keep) // 2
        img = img.crop((left, 0, left + keep, img.height))
    elif have < want:
        keep = round(img.width / want)
        top = (img.height - keep) // 2
        img = img.crop((0, top, img.width, top + keep))
    return img.resize(size, Resampling.LANCZOS)


def fit_webp(img: Image.Image, budget: int) -> tuple[bytes, int]:
    """Highest quality on the ladder that fits. The last rung is returned even if it misses,
    so the caller can report a budget failure rather than silently shipping a bigger file."""
    best = b""
    quality = QUALITY_LADDER[-1]
    import io

    for quality in QUALITY_LADDER:
        buf = io.BytesIO()
        img.save(buf, "WEBP", quality=quality, method=6)
        best = buf.getvalue()
        if len(best) <= budget:
            break
    return best, quality


def kb(n: int) -> str:
    return f"{n / 1024:.1f} KB"


def build(check: bool) -> int:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    BRAND.mkdir(parents=True, exist_ok=True)
    problems: list[str] = []
    rows: list[tuple[str, str, str, str, str]] = []

    for target, source in PAIRS.items():
        light = open_source(f"{source}-light")
        dark = open_source(f"{source}-dark")
        if light.size != dark.size:
            problems.append(
                f"{target}: light and dark differ ({light.size[0]}x{light.size[1]} vs "
                f"{dark.size[0]}x{dark.size[1]}) — they must match or the page shifts"
            )
        size = None
        grounds = theme_grounds()
        surface = SURFACES[target]
        for theme, img in (("light", light), ("dark", dark)):
            ground = grounds[theme][surface]
            if target in TRANSPARENT:
                resized = key_ground(img, ground).resize(
                    (EMPTY_W, round(EMPTY_W * img.height / img.width)), Resampling.LANCZOS
                )
            else:
                resized = fit_to_width(reground(img, ground), EMPTY_W)
            size = resized.size
            out = RUNTIME / f"{target}-{theme}.webp"
            data, quality = fit_webp(resized, EMPTY_BUDGET)
            if check:
                if not out.exists():
                    problems.append(f"{target}-{theme}.webp is missing — run without --check")
                    continue
                data = out.read_bytes()
                with Image.open(out) as got:
                    if got.size != resized.size:
                        problems.append(
                            f"{target}-{theme}.webp is {got.size[0]}x{got.size[1]}, "
                            f"expected {resized.size[0]}x{resized.size[1]}"
                        )
            else:
                out.write_bytes(data)
            if len(data) > EMPTY_BUDGET:
                problems.append(
                    f"{target}-{theme}.webp is {kb(len(data))}, over the {kb(EMPTY_BUDGET)} budget"
                )
            if check:
                with Image.open(out) as got:
                    rgba = got.convert("RGBA")
                    if got.getexif():
                        problems.append(f"{target}-{theme}.webp carries EXIF metadata")
                    if target in TRANSPARENT:
                        # keyed: the corner must be see-through, and the drawing must survive
                        alpha = rgba.getchannel("A")
                        if rgba.getpixel((2, 2))[3] > 8:
                            problems.append(
                                f"{target}-{theme}.webp is meant to be keyed transparent but its "
                                f"corner alpha is {rgba.getpixel((2, 2))[3]}"
                            )
                        if alpha.getextrema()[1] < 250:
                            problems.append(
                                f"{target}-{theme}.webp keyed away the drawing: the most opaque "
                                f"pixel is only {alpha.getextrema()[1]}/255"
                            )
                    else:
                        # opaque: the ground has to be the surface it is placed on, or the
                        # artwork shows as a rectangle of the wrong beige
                        want = grounds[theme][surface]
                        off = max(abs(a - b) for a, b in zip(corners(rgba), want))
                        if off > 3:
                            problems.append(
                                f"{target}-{theme}.webp sits {off}/255 off the {theme} {surface} it "
                                f"is placed on — the picture would show as a rectangle"
                            )
            rows.append(
                (
                    f"{source}-{theme}.jpg",
                    f"frontend/src/assets/{target}-{theme}.webp",
                    f"{size[0]}x{size[1]}",
                    kb((SOURCE / f'{source}-{theme}.jpg').stat().st_size),
                    f"{kb(len(data))} q{quality}",
                )
            )

    # social card: the revised planner, cropped to the 1.91:1 crawlers want
    og = fit_ratio(open_source("planner-og-source"), OG_SIZE)
    og_out = BRAND / "sundial-og.jpg"
    data = b""
    if check:
        if not og_out.exists():
            problems.append("sundial-og.jpg is missing — run without --check")
        else:
            data = og_out.read_bytes()
            with Image.open(og_out) as got:
                if got.size != OG_SIZE:
                    problems.append(f"sundial-og.jpg is {got.size}, expected {OG_SIZE}")
    else:
        import io

        buf = io.BytesIO()
        og.save(buf, "JPEG", quality=86, optimize=True, progressive=True)
        data = buf.getvalue()
        og_out.write_bytes(data)
    if len(data) > OG_BUDGET:
        problems.append(f"sundial-og.jpg is {kb(len(data))}, over the {kb(OG_BUDGET)} budget")
    rows.append(
        (
            "planner-og-source.jpg",
            "frontend/public/brand/sundial-og.jpg",
            f"{OG_SIZE[0]}x{OG_SIZE[1]}",
            kb((SOURCE / "planner-og-source.jpg").stat().st_size),
            kb(len(data)),
        )
    )

    # README banner: scaled to width, then padded to the exact ratio with its own ground
    # colour. Padding, not cropping: the sun is in the left margin and the moon in the right.
    banner_src = open_source("ruler-banner-source")
    ground = banner_src.getpixel((2, 2))
    canvas = Image.new("RGB", BANNER_SIZE, ground)
    # 96% of the width, centred: the sun and the moon keep a real margin rather than the
    # moon grazing the right edge, and the ruler's ends stop short of the canvas edge.
    scaled = fit_to_width(banner_src, round(BANNER_SIZE[0] * 0.96))
    canvas.paste(scaled, ((BANNER_SIZE[0] - scaled.width) // 2, (BANNER_SIZE[1] - scaled.height) // 2))
    bar_out = BRAND / "sundial-readme-banner.webp"
    data = b""
    if check:
        if not bar_out.exists():
            problems.append("sundial-readme-banner.webp is missing — run without --check")
        else:
            data = bar_out.read_bytes()
            with Image.open(bar_out) as got:
                if got.size != BANNER_SIZE:
                    problems.append(f"sundial-readme-banner.webp is {got.size}, expected {BANNER_SIZE}")
    else:
        data, _ = fit_webp(canvas, BANNER_BUDGET)
        bar_out.write_bytes(data)
    if len(data) > BANNER_BUDGET:
        problems.append(f"sundial-readme-banner.webp is {kb(len(data))}, over {kb(BANNER_BUDGET)}")
    rows.append(
        (
            "ruler-banner-source.jpg",
            "frontend/public/brand/sundial-readme-banner.webp",
            f"{BANNER_SIZE[0]}x{BANNER_SIZE[1]}",
            kb((SOURCE / "ruler-banner-source.jpg").stat().st_size),
            kb(len(data)),
        )
    )

    verb = "checked" if check else "wrote"
    print(f"{verb} {len(rows)} derivatives\n")
    print(f"{'source':28} {'-> production':46} {'size':>10} {'from':>9} {'to':>12}")
    for a, b, size, was, now in rows:
        print(f"{a:28} {b:46} {size:>10} {was:>9} {now:>12}")

    if problems:
        print("\nbudget or dimension problems:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\nall within budget, dimensions matched, no metadata")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="verify the committed files, write nothing")
    raise SystemExit(build(ap.parse_args().check))
