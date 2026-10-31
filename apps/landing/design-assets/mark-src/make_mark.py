"""Omiryn mark: an infinity drawn with a broad-nib pen, two loops in two colors.

Width follows the nib model (thick where the stroke runs across the nib, thin along it),
plus a slow wobble so it reads as drawn by hand, not plotted. The right loop is ember and
passes over the ink loop at the crossing. Run:
    python3 apps/landing/design-assets/mark-src/make_mark.py > apps/landing/public/static/assets/omiryn-mark.svg
"""
import math

A = 44.0            # half width of the loop
CX, CY = 50.0, 25.0 # center in a 100 x 50 box
NIB = 9.0           # nib width
MIN_W = 3.4         # thinnest point
NIB_ANGLE = math.radians(38)
N = 260
INK = "#15120e"
EMBER = "#ff4f2b"


def lem(t):
    d = 1 + math.sin(t) ** 2
    return CX + A * math.cos(t) / d, CY + A * math.sin(t) * math.cos(t) / d * 1.15


def wobble(t):
    return 1 + 0.07 * math.sin(3 * t + 0.8) + 0.04 * math.sin(5 * t - 1.3)


def edges(t, scale=1.0):
    x, y = lem(t)
    x2, y2 = lem(t + 1e-3)
    dx, dy = x2 - x, y2 - y
    L = math.hypot(dx, dy)
    tx, ty = dx / L, dy / L
    w = max(MIN_W, NIB * abs(math.sin(math.atan2(ty, tx) - NIB_ANGLE))) * wobble(t) * scale
    nx, ny = -ty, tx
    return (x + nx * w / 2, y + ny * w / 2), (x - nx * w / 2, y - ny * w / 2)


def ribbon(t0, t1, taper=0.0):
    """One closed ribbon from t0 to t1: the left edge forward, the right edge back.
    With taper, the last `taper` of parameter at each end narrows to a point."""
    def scale(t):
        if not taper:
            return 1.0
        d = min(t - t0, t1 - t)
        u = min(1.0, d / taper)
        return u * u * (3 - 2 * u)
    pts = [edges(t, scale(t)) for t in (t0 + (t1 - t0) * i / N for i in range(N + 1))]
    outline = [p[0] for p in pts] + [p[1] for p in reversed(pts)]
    return "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in outline) + " Z"


# The curve crosses the center at t = pi/2 and 3pi/2. The color changes there. Each loop
# runs a hair past the center, inside the overlap, so the crossing has no notch; the ember
# loop sits on top.
over = 0.1
left = ribbon(math.pi / 2 - over, 3 * math.pi / 2 + over)
right = ribbon(3 * math.pi / 2 - over, 5 * math.pi / 2 + over)

print('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50">')
print(f'<path fill="{INK}" d="{left}"/>')
print(f'<path fill="{EMBER}" d="{right}"/>')
print("</svg>")
