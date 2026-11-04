"""Raster icons from the mark (omiryn-mark.svg), no external tools.

The mark is two filled polygons (M/L points only), so Pillow can draw them with 8x supersampling.
Writes, next to the old violet icons (kept):
  apps/web/public/assets/omiryn-app-icon-paper.png        512x512, paper square, mark at 62% width
  apps/landing/public/static/assets/omiryn-app-icon-paper.png  (same)
  apps/web/public/assets/favicon-32.png                   32x32, mark at 92% width (readable small)
  apps/landing/public/static/assets/favicon-32.png
  apps/web/public/assets/omiryn-app-icon-192.png          192x192 for the manifest

Run from the repo root:
  python3 apps/landing/design-assets/mark-src/make_icons.py
"""
import re
from pathlib import Path

from PIL import Image, ImageDraw

SVG = Path("apps/landing/public/static/assets/omiryn-mark.svg")
PAPER = (243, 238, 228, 255)
SS = 8  # supersample


def read_paths():
    src = SVG.read_text()
    box = [float(v) for v in re.search(r'viewBox="([^"]+)"', src).group(1).split()]
    paths = []
    for fill, d in re.findall(r'<path fill="(#[0-9a-fA-F]{6})" d="([^"]+)"', src):
        pts = [(float(x), float(y)) for x, y in re.findall(r"[ML]\s*([-\d.]+)\s+([-\d.]+)", d)]
        rgb = tuple(int(fill[i:i + 2], 16) for i in (1, 3, 5))
        paths.append((rgb, pts))
    return box, paths


def render(size, mark_width_ratio, background=PAPER, offset_y=0.0):
    """Square `size`, mark centred, its width = size * ratio."""
    box, paths = read_paths()
    vw, vh = box[2], box[3]
    big = size * SS
    scale = big * mark_width_ratio / vw
    mw, mh = vw * scale, vh * scale
    ox, oy = (big - mw) / 2, (big - mh) / 2 + big * offset_y
    im = Image.new("RGBA", (big, big), background)
    draw = ImageDraw.Draw(im)
    for rgb, pts in paths:
        # The ribbon is the left edge forward then the right edge back, and its two ends overlap
        # at the crossing. Pillow fills polygons even-odd, which would punch a hole there, so draw
        # the ribbon as strips between matching edge points (a union, like the browser's nonzero).
        n = len(pts) // 2
        left = [(ox + x * scale, oy + y * scale) for x, y in pts[:n]]
        right = [(ox + x * scale, oy + y * scale) for x, y in pts[n:][::-1]]
        for i in range(n - 1):
            quad = [left[i], left[i + 1], right[i + 1], right[i]]
            draw.polygon(quad, fill=(*rgb, 255), outline=(*rgb, 255))
    return im.resize((size, size), Image.LANCZOS)


OUT = [
    ("apps/web/public/assets/omiryn-app-icon-paper.png", 512, 0.62),
    ("apps/landing/public/static/assets/omiryn-app-icon-paper.png", 512, 0.62),
    ("apps/web/public/assets/omiryn-app-icon-192.png", 192, 0.62),
    ("apps/web/public/assets/favicon-32.png", 32, 0.92),
    ("apps/landing/public/static/assets/favicon-32.png", 32, 0.92),
]

for path, size, ratio in OUT:
    img = render(size, ratio)
    img.save(path, "PNG", optimize=True)
    print(path, img.size)
