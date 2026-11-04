"""Telegram bot avatar from omi-jelly.png, recolored into ember on paper.

The jelly render has no alpha, so the lavender background is found by flood-filling from the
corners (with a tolerance); it becomes paper. The blob is recolored like the agent blobs
(lightness onto an ember ramp); its dark features (eyes, smile) go towards ink so they stay
readable on ember. Writes telegram-bot-avatar-ember-640.png next to the old jpg (kept).

Run from the repo root:
  python3 apps/landing/design-assets/agent-src/make_telegram_avatar.py
"""
import colorsys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).parent
SRC = HERE / "omi-jelly.png"
OUT = HERE / "telegram-bot-avatar-ember-640.png"
PAPER = (243, 238, 228)
INK = (21, 18, 14)
RAMP = [
    (0.00, (140, 26, 8)),
    (0.30, (188, 46, 15)),
    (0.55, (248, 68, 31)),
    (0.78, (255, 140, 106)),
    (0.92, (255, 205, 186)),
    (1.00, (255, 255, 255)),
]
L_LO, L_HI = 0.50, 1.00


def lerp(a, b, k):
    return tuple(round(x + (y - x) * k) for x, y in zip(a, b))


def ramp(t):
    t = max(0.0, min(1.0, t))
    for (p0, c0), (p1, c1) in zip(RAMP, RAMP[1:]):
        if t <= p1:
            return lerp(c0, c1, 0 if p1 == p0 else (t - p0) / (p1 - p0))
    return RAMP[-1][1]


im = Image.open(SRC).convert("RGB")
w, h = im.size

# background mask: flood from the four corners on a copy, tolerance on the lavender
mask_img = im.copy()
for corner in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]:
    ImageDraw.floodfill(mask_img, corner, (0, 255, 0), thresh=46)
bg = Image.new("L", (w, h), 0)
bgpx = bg.load()
mpx = mask_img.load()
for y in range(h):
    for x in range(w):
        if mpx[x, y] == (0, 255, 0):
            bgpx[x, y] = 255
# keep only the blob itself: flood the non-background region from the centre, and anything not
# reached (the floor shadow, stray specks) becomes background too
blob = Image.eval(bg, lambda v: 255 - v)
ImageDraw.floodfill(blob, (w // 2, h // 2), 128)
bpx = blob.load()
for y in range(h):
    for x in range(w):
        bgpx[x, y] = 0 if bpx[x, y] == 128 else 255
# soften the edge a little so the rim blends into paper
bg = bg.filter(ImageFilter.GaussianBlur(1.2))

out = Image.new("RGB", (w, h), PAPER)
opx = out.load()
px = im.load()
bgpx = bg.load()
for y in range(h):
    for x in range(w):
        k = bgpx[x, y] / 255  # 1 = background
        if k >= 0.999:
            continue
        r, g, b = px[x, y]
        hue, light, sat = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        if light < L_LO:
            col = lerp(INK, RAMP[0][1], light / L_LO)  # eyes and smile
        else:
            t = (light - L_LO) / (L_HI - L_LO)
            if sat > 0.2:
                t += (((hue * 360) - 290) / 70) * 0.12
            col = ramp(t)
        opx[x, y] = lerp(col, PAPER, k)

out = out.resize((640, 640), Image.LANCZOS)
out.save(OUT, "PNG", optimize=True)
print(OUT, out.size)
