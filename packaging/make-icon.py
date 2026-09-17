#!/usr/bin/env python3
"""Draw `packaging/icon.icns` from the product's own design tokens.

The icon is generated rather than hand-drawn so it cannot drift from the brief
it is supposed to embody. Every colour here is copied from `docs/DESIGN-BRIEF.md`
and `chitragupta/web/styles.css` — the night-sky ground, the cool-white particles,
and the one warm gold pole-star that is the app's single accent.

The mark is the same rotated square (`.brand-mark` in styles.css) the sidebar
wears, with a constellation inside it and one gold star at its top vertex. That
is the brand hook in a shape: a field of scattered things, the lines drawn
between them, and a single bright point for the one being written down.

Two things make it survive being shrunk to 16px in a Finder list:

* the diamond is an outline with a thick-enough stroke to stay closed, and
* the gold star is the only saturated thing in the frame, so it reads as a dot
  of colour long after the constellation behind it has blurred to texture.

Deterministic on purpose — a fixed seed means rebuilding produces byte-identical
PNGs, so an icon change shows up in review as an intentional diff.

    ./.venv/bin/python packaging/make-icon.py
"""
from __future__ import annotations

import math
import random
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent

# ── Tokens, lifted from the brief ────────────────────────────────────────────
GROUND_TOP = (10, 14, 26)        # #0a0e1a — the sky is not flat; it lifts
GROUND_BOT = (3, 5, 10)          # #03050a — --rail
STAR = (223, 231, 242)           # #dfe7f2 — --star, cool white
NORTH = (245, 200, 119)          # #f5c877 — --north, the ONE accent

# macOS icon geometry (Big Sur and later): on a 1024pt canvas the rounded
# square occupies 824pt, centred, leaving the margin the system expects. Getting
# this wrong is why a custom icon looks subtly too big next to Apple's.
CANVAS = 1024
SQUIRCLE = 824
SUPERSAMPLE = 2                  # draw at 2x, downsample — Pillow has no AA

#: Every size `iconutil` requires, as (pixel size, iconset filename).
ICONSET = [
    (16, "icon_16x16.png"), (32, "icon_16x16@2x.png"),
    (32, "icon_32x32.png"), (64, "icon_32x32@2x.png"),
    (128, "icon_128x128.png"), (256, "icon_128x128@2x.png"),
    (256, "icon_256x256.png"), (512, "icon_256x256@2x.png"),
    (512, "icon_512x512.png"), (1024, "icon_512x512@2x.png"),
]


def _squircle_mask(size: int, radius_ratio: float = 0.2265) -> Image.Image:
    """Apple's rounded square, as a superellipse rather than circular corners.

    `ImageDraw.rounded_rectangle` gives circular corners, which read as visibly
    rounder and softer than the system shape when the icon sits in a dock beside
    Apple's own. A superellipse of exponent ~5 is the standard approximation and
    costs nothing here.
    """
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    n = 5.0
    half = size / 2.0
    # r is Apple's corner radius; the exponent shapes how quickly it turns.
    points = []
    steps = 2048
    for i in range(steps):
        t = 2.0 * math.pi * i / steps
        ct, st = math.cos(t), math.sin(t)
        x = half * math.copysign(abs(ct) ** (2.0 / n), ct)
        y = half * math.copysign(abs(st) ** (2.0 / n), st)
        points.append((half + x, half + y))
    draw.polygon(points, fill=255)
    return mask


def _ground(size: int) -> Image.Image:
    """A vertical gradient, so the sky has a top and a bottom."""
    img = Image.new("RGB", (1, size))
    px = img.load()
    for y in range(size):
        t = y / max(1, size - 1)
        px[0, y] = tuple(                       # type: ignore[assignment]
            round(GROUND_TOP[c] + (GROUND_BOT[c] - GROUND_TOP[c]) * t)
            for c in range(3))
    return img.resize((size, size), Image.Resampling.BILINEAR)


def _glow(size: int, centre: tuple[float, float], radius: float,
          colour: tuple[int, int, int], strength: float) -> Image.Image:
    """A soft radial bloom, drawn as a blurred disc on its own layer."""
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    cx, cy = centre
    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius],
                 fill=(*colour, round(255 * strength)))
    return layer.filter(ImageFilter.GaussianBlur(radius * 0.55))


def render(size: int) -> Image.Image:
    """The artwork, at `size` px square, alpha outside the squircle.

    The detail drops in tiers, the way an icon set is drawn rather than scaled.
    Each threshold below was chosen by rendering the size and looking at it, and
    each exists because the fuller treatment failed there:

    * **>=128** everything: particle field, constellation, needle, pole star.
    * **>=64** drops the particles. They stop being texture and become dirt.
    * **>=32** drops the constellation and needle too, and thickens the outline
      so it stays a closed shape. The star survives as a crisp gold dot.
    * **16** is the silhouette alone — a *filled* diamond, no gold at all. An
      outline that small closes up into a grey ring, and the gold star smears
      into a brown blob that made the whole icon read as a hot-air balloon. The
      diamond by itself is the sidebar's `.brand-mark`, so it is still the
      product's own mark and not a compromise shape.
    """
    s = size * SUPERSAMPLE
    scale = s / CANVAS                       # everything below is in 1024-space
    particles = size >= 128
    constellation = size >= 64
    star = size >= 32                        # below this the gold only muddies
    outline = size >= 32                     # 16px is filled instead

    def u(v: float) -> float:
        return v * scale

    inset = (CANVAS - SQUIRCLE) / 2.0
    box = (u(inset), u(inset), u(inset + SQUIRCLE), u(inset + SQUIRCLE))
    cx = cy = s / 2.0

    # ── the night sky, clipped to the squircle ──────────────────────────────
    art = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ground = _ground(round(u(SQUIRCLE))).convert("RGBA")
    art.paste(ground, (round(box[0]), round(box[1])))

    # The diamond grows as the detail falls away — with nothing else in the
    # frame at 16px it can afford the room, and it needs it to read.
    frac = 0.285 if constellation else (0.30 if outline else 0.34)
    half_d = u(SQUIRCLE * frac)
    north_xy = (cx, cy - half_d)

    # A gold bloom behind the star lifts the sky locally, so the accent looks
    # like a light source rather than a sticker. It shrinks faster than the icon
    # does — at small sizes the bloom would otherwise BE the icon.
    if star:
        art.alpha_composite(
            _glow(s, north_xy, u(210) if particles else u(46), NORTH,
                  0.20 if particles else 0.95))
    if particles:
        art.alpha_composite(_glow(s, (cx, cy + u(140)), u(300), STAR, 0.035))

    draw = ImageDraw.Draw(art)

    # ── particle field ──────────────────────────────────────────────────────
    if particles:
        rng = random.Random(20260916)        # fixed seed → reproducible PNGs
        for _ in range(90):
            px_, py_ = rng.uniform(box[0], box[2]), rng.uniform(box[1], box[3])
            # Keep the field off the mark; texture must not fight the shape.
            if abs(px_ - cx) + abs(py_ - cy) < half_d * 1.22:
                continue
            r = u(rng.uniform(1.6, 4.4))
            a = round(255 * rng.uniform(0.07, 0.30))
            draw.ellipse([px_ - r, py_ - r, px_ + r, py_ + r], fill=(*STAR, a))

    # ── the constellation inside the mark, and the needle up to the star ────
    if constellation:
        # Fixed nodes, as fractions of the diamond's half-diagonal from centre.
        nodes = [(-0.46, -0.10), (-0.12, 0.34), (0.30, 0.08),
                 (0.10, -0.40), (0.50, -0.30), (-0.28, 0.62)]
        pts = [(cx + nx * half_d, cy + ny * half_d) for nx, ny in nodes]
        for a_i, b_i in [(0, 1), (1, 2), (2, 3), (3, 0), (2, 4), (1, 5)]:
            draw.line([pts[a_i], pts[b_i]], fill=(*STAR, 54), width=max(1, round(u(3))))
        # The one edge drawn in gold: the needle, reaching for north.
        draw.line([pts[3], north_xy], fill=(*NORTH, 96), width=max(1, round(u(3.5))))
        for p in pts:
            r = u(6.5)
            draw.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=(*STAR, 190))

    # ── the mark: the sidebar's rotated square ──────────────────────────────
    diamond = [(cx, cy - half_d), (cx + half_d, cy), (cx, cy + half_d), (cx - half_d, cy)]
    if outline:
        # A heavier stroke at 32px: scaled down from 15 it thins to nothing and
        # the corners break open.
        draw.line([*diamond, diamond[0]], fill=(*STAR, 238),
                  width=max(2, round(u(15 if constellation else 30))), joint="curve")
    else:
        draw.polygon(diamond, fill=(*STAR, 236))

    # ── the pole star, last, over everything ────────────────────────────────
    if star:
        r = u(21) if particles else u(34)     # hold its ground once shrunk
        draw.ellipse([north_xy[0] - r, north_xy[1] - r, north_xy[0] + r, north_xy[1] + r],
                     fill=(255, 243, 218, 255))

    # ── clip, and downsample to the requested size ──────────────────────────
    mask = Image.new("L", (s, s), 0)
    mask.paste(_squircle_mask(round(u(SQUIRCLE))), (round(box[0]), round(box[1])))
    art.putalpha(Image.composite(art.getchannel("A"), Image.new("L", (s, s), 0), mask))
    return art.resize((size, size), Image.Resampling.LANCZOS)


def main() -> int:
    if shutil.which("iconutil") is None:
        print("iconutil not found — macOS only.", file=sys.stderr)
        return 1

    iconset = HERE / "icon.iconset"
    shutil.rmtree(iconset, ignore_errors=True)
    iconset.mkdir()

    master = render(1024)
    for px, filename in ICONSET:
        img = master if px == 1024 else render(px)
        img.save(iconset / filename)

    out = HERE / "icon.icns"
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(out)], check=True)
    shutil.rmtree(iconset, ignore_errors=True)
    print(f"✓ {out}  ({out.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
