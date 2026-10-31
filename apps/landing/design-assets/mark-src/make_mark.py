"""Omiryn mark: an infinity drawn with a broad-nib pen, as one filled SVG path.

Width follows the nib model (thick where the stroke runs across the nib, thin along it),
plus a slow wobble so it reads as drawn by hand, not plotted. Run:
    python3 apps/landing/design-assets/mark-src/make_mark.py > apps/landing/public/static/assets/omiryn-mark.svg
"""
import math

A = 44.0            # half width of the loop
CX, CY = 50.0, 25.0 # center in a 100 x 50 box
NIB = 9.0           # nib width
MIN_W = 3.4         # thinnest point
NIB_ANGLE = math.radians(38)
N = 260


def lem(t):
    d = 1 + math.sin(t) ** 2
    return CX + A * math.cos(t) / d, CY + A * math.sin(t) * math.cos(t) / d * 1.15


def wobble(t):
    return 1 + 0.07 * math.sin(3 * t + 0.8) + 0.04 * math.sin(5 * t - 1.3)


pts = []
for i in range(N + 1):
    t = 2 * math.pi * i / N
    x, y = lem(t)
    x2, y2 = lem(t + 1e-3)
    dx, dy = x2 - x, y2 - y
    L = math.hypot(dx, dy)
    tx, ty = dx / L, dy / L
    ang = math.atan2(ty, tx)
    w = max(MIN_W, NIB * abs(math.sin(ang - NIB_ANGLE))) * wobble(t)
    nx, ny = -ty, tx
    pts.append(((x + nx * w / 2, y + ny * w / 2), (x - nx * w / 2, y - ny * w / 2)))

# One closed ribbon: the left edge forward, the right edge back. Nonzero fill keeps the
# crossing solid and the two eyes open.
outline = [p[0] for p in pts] + [p[1] for p in reversed(pts)]
d = "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in outline) + " Z"

print('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50" fill="currentColor">')
print(f'<path d="{d}"/>')
print("</svg>")
