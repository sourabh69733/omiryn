"""Recolor the agent blobs from violet/pink into the ember palette.

Keeps the render (gloss, swirls, alpha) and only remaps colour: the original lightness picks a
point on an ember ramp, and the original hue (violet to pink) nudges it deeper or peachier so the
swirls stay visible. Writes agent-<state>-ember-{128,256}.webp next to the old files, which stay.

Run from the repo root:
  python3 apps/landing/design-assets/agent-src/recolor_ember.py
"""
import colorsys
from pathlib import Path

from PIL import Image

SRC = Path(__file__).parent
OUT = Path("apps/web/public/assets/agent")
STATES = ["idle", "thinking", "listening", "happy"]

# lightness stops on the ember ramp (position 0..1 -> rgb)
RAMP = [
    (0.00, (140, 26, 8)),
    (0.30, (214, 58, 23)),
    (0.55, (255, 79, 43)),
    (0.78, (255, 140, 106)),
    (0.92, (255, 205, 186)),
    (1.00, (255, 255, 255)),
]
L_LO, L_HI = 0.50, 1.00  # the source blobs live in this lightness range


def ramp(t):
    t = max(0.0, min(1.0, t))
    for (p0, c0), (p1, c1) in zip(RAMP, RAMP[1:]):
        if t <= p1:
            k = 0 if p1 == p0 else (t - p0) / (p1 - p0)
            return tuple(round(a + (b - a) * k) for a, b in zip(c0, c1))
    return RAMP[-1][1]


def recolor(im):
    im = im.convert("RGBA")
    px = im.load()
    w, h = im.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            hue, light, sat = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
            t = (light - L_LO) / (L_HI - L_LO)
            # violet (~260) sits deeper, pink (~330) sits peachier; greys stay put
            if sat > 0.2:
                hue_deg = hue * 360
                t += ((hue_deg - 290) / 70) * 0.12
            px[x, y] = (*ramp(t), a)
    return im


for state in STATES:
    src = Image.open(SRC / f"agent-{state}.png")
    big = recolor(src)
    for size in (256, 128):
        small = big.resize((size, size), Image.LANCZOS)
        out = OUT / f"agent-{state}-ember-{size}.webp"
        small.save(out, "WEBP", quality=90, method=6)
        print(out, small.size)
