"""make.fun sticker: a crowned robot agent above the make.fun wordmark.

Pure standard library. Shapes are signed distance fields; coverage comes straight
from the distance (analytic anti-aliasing), outlines and the die-cut border are
the same fields read at larger thresholds. Writes a deterministic RGBA PNG.
"""
import math
import os
import struct
import zlib

W = H = 1024


# ---------------------------------------------------------------- primitives
class Capsule:
    def __init__(self, ax, ay, bx, by, r):
        self.ax, self.ay, self.bx, self.by, self.r = ax, ay, bx, by, r
        self.dx, self.dy = bx - ax, by - ay
        self.ll = self.dx * self.dx + self.dy * self.dy or 1e-9

    def bbox(self):
        r = self.r
        return (min(self.ax, self.bx) - r, min(self.ay, self.by) - r,
                max(self.ax, self.bx) + r, max(self.ay, self.by) + r)

    def sdf(self, px, py):
        qx, qy = px - self.ax, py - self.ay
        t = (qx * self.dx + qy * self.dy) / self.ll
        t = 0.0 if t < 0 else (1.0 if t > 1 else t)
        ex, ey = qx - self.dx * t, qy - self.dy * t
        return math.sqrt(ex * ex + ey * ey) - self.r


class Circle:
    def __init__(self, cx, cy, r):
        self.cx, self.cy, self.r = cx, cy, r

    def bbox(self):
        return (self.cx - self.r, self.cy - self.r, self.cx + self.r, self.cy + self.r)

    def sdf(self, px, py):
        return math.hypot(px - self.cx, py - self.cy) - self.r


class Arc:
    """Stroke of half-width w along a circle of radius rad, from angle a0 sweeping
    ccw by `sweep` (degrees, y-up convention), with round caps."""

    def __init__(self, cx, cy, rad, a0, sweep, w):
        self.cx, self.cy, self.rad, self.w = cx, cy, rad, w
        self.a0 = math.radians(a0)
        self.sw = math.radians(sweep)
        a1 = self.a0 + self.sw
        self.e0 = (cx + rad * math.cos(self.a0), cy - rad * math.sin(self.a0))
        self.e1 = (cx + rad * math.cos(a1), cy - rad * math.sin(a1))

    def bbox(self):
        e = self.rad + self.w
        return (self.cx - e, self.cy - e, self.cx + e, self.cy + e)

    def sdf(self, px, py):
        dx, dy = px - self.cx, self.cy - py
        ang = (math.atan2(dy, dx) - self.a0) % (2 * math.pi)
        if ang <= self.sw:
            return abs(math.hypot(dx, dy) - self.rad) - self.w
        d0 = math.hypot(px - self.e0[0], py - self.e0[1])
        d1 = math.hypot(px - self.e1[0], py - self.e1[1])
        return min(d0, d1) - self.w


class RBox:
    def __init__(self, x0, y0, x1, y1, r):
        self.cx, self.cy = (x0 + x1) / 2, (y0 + y1) / 2
        self.hx, self.hy = (x1 - x0) / 2 - r, (y1 - y0) / 2 - r
        self.r = r
        self.box = (x0, y0, x1, y1)

    def bbox(self):
        return self.box

    def sdf(self, px, py):
        qx = abs(px - self.cx) - self.hx
        qy = abs(py - self.cy) - self.hy
        ox, oy = max(qx, 0.0), max(qy, 0.0)
        return math.sqrt(ox * ox + oy * oy) + min(max(qx, qy), 0.0) - self.r


class Poly:
    """Polygon, optionally rounded by r (offset outward)."""

    def __init__(self, pts, r=0.0):
        self.p = pts
        self.r = r

    def bbox(self):
        xs = [q[0] for q in self.p]
        ys = [q[1] for q in self.p]
        return (min(xs) - self.r, min(ys) - self.r, max(xs) + self.r, max(ys) + self.r)

    def sdf(self, px, py):
        p = self.p
        n = len(p)
        best = 1e18
        inside = False
        j = n - 1
        for i in range(n):
            ax, ay = p[j]
            bx, by = p[i]
            ex, ey = bx - ax, by - ay
            wx, wy = px - ax, py - ay
            ll = ex * ex + ey * ey
            t = (wx * ex + wy * ey) / ll if ll else 0.0
            t = 0.0 if t < 0 else (1.0 if t > 1 else t)
            dx, dy = wx - ex * t, wy - ey * t
            d = dx * dx + dy * dy
            if d < best:
                best = d
            if (ay > py) != (by > py):
                if px < ax + (py - ay) * ex / ey:
                    inside = not inside
            j = i
        d = math.sqrt(best)
        return (-d if inside else d) - self.r


# ---------------------------------------------------------------- raster
class Canvas:
    def __init__(self):
        n = W * H
        # premultiplied RGBA floats, 0..1
        self.r = [0.0] * n
        self.g = [0.0] * n
        self.b = [0.0] * n
        self.a = [0.0] * n


class Field:
    """Union distance field of prims, evaluated only near the shapes (within pad)."""

    def __init__(self, prims, pad):
        bx = [p.bbox() for p in prims]
        x0 = max(0, int(min(b[0] for b in bx) - pad - 2))
        y0 = max(0, int(min(b[1] for b in bx) - pad - 2))
        x1 = min(W, int(max(b[2] for b in bx) + pad + 3))
        y1 = min(H, int(max(b[3] for b in bx) + pad + 3))
        self.x0, self.y0, self.x1, self.y1 = x0, y0, x1, y1
        rw = x1 - x0
        self.rw = rw
        big = 1e9
        d = [big] * (rw * (y1 - y0))
        for prim, b in zip(prims, bx):
            px0 = max(x0, int(b[0] - pad - 2))
            py0 = max(y0, int(b[1] - pad - 2))
            px1 = min(x1, int(b[2] + pad + 3))
            py1 = min(y1, int(b[3] + pad + 3))
            f = prim.sdf
            for y in range(py0, py1):
                row = (y - y0) * rw - x0
                fy = y + 0.5
                for x in range(px0, px1):
                    v = f(x + 0.5, fy)
                    k = row + x
                    if v < d[k]:
                        d[k] = v
        self.d = d

    @classmethod
    def blend(cls, fields, k):
        """Smooth union of whole fields (polynomial smooth-min, radius k): one
        blend per group, so fillets form only where separate parts meet."""
        self = cls.__new__(cls)
        self.x0 = min(f.x0 for f in fields)
        self.y0 = min(f.y0 for f in fields)
        self.x1 = max(f.x1 for f in fields)
        self.y1 = max(f.y1 for f in fields)
        rw = self.rw = self.x1 - self.x0
        big = 1e9
        d = [big] * (rw * (self.y1 - self.y0))
        for f in fields:
            fd, frw = f.d, f.rw
            for y in range(f.y0, f.y1):
                src = (y - f.y0) * frw - f.x0
                dst = (y - self.y0) * rw - self.x0
                for x in range(f.x0, f.x1):
                    v = fd[src + x]
                    o = d[dst + x]
                    h = k - abs(o - v)
                    if h > 0:
                        h /= k
                        d[dst + x] = (o if o < v else v) - h * h * k * 0.25
                    elif v < o:
                        d[dst + x] = v
        self.d = d
        return self

    def contour(self, level):
        """Re-measure distance from the `level` iso-line: (d - level) / |grad d|.
        A smooth union is not a true distance field (|grad| < 1 inside fillets),
        so bands painted on it directly would swell; this keeps them even."""
        d, rw = self.d, self.rw
        h = self.y1 - self.y0
        out = [1e9] * len(d)
        for y in range(1, h - 1):
            r = y * rw
            for x in range(1, rw - 1):
                k = r + x
                v = d[k] - level
                if v > 40 or v < -40:
                    out[k] = v
                    continue
                gx = (d[k + 1] - d[k - 1]) * 0.5
                gy = (d[k + rw] - d[k - rw]) * 0.5
                g = math.sqrt(gx * gx + gy * gy)
                out[k] = v / (g if g > 0.2 else 0.2)
        self.d = out
        return self

    def paint(self, cv, color, grow=0.0):
        cr, cg, cb = (c / 255.0 for c in color)
        d = self.d
        rw = self.rw
        R, G, B, A = cv.r, cv.g, cv.b, cv.a
        for y in range(self.y0, self.y1):
            row = (y - self.y0) * rw
            base = y * W
            for x in range(self.x0, self.x1):
                cov = 0.5 + grow - d[row + x - self.x0]
                if cov <= 0.0:
                    continue
                if cov > 1.0:
                    cov = 1.0
                k = base + x
                inv = 1.0 - cov
                R[k] = cr * cov + R[k] * inv
                G[k] = cg * cov + G[k] * inv
                B[k] = cb * cov + B[k] * inv
                A[k] = cov + A[k] * inv


def write_png(path, cv):
    rows = bytearray()
    R, G, B, A = cv.r, cv.g, cv.b, cv.a
    for y in range(H):
        rows.append(0)
        for k in range(y * W, (y + 1) * W):
            a = A[k]
            if a <= 0.0:
                rows += b"\x00\x00\x00\x00"
                continue
            rows.append(min(255, int(R[k] / a * 255 + 0.5)))
            rows.append(min(255, int(G[k] / a * 255 + 0.5)))
            rows.append(min(255, int(B[k] / a * 255 + 0.5)))
            rows.append(min(255, int(a * 255 + 0.5)))

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(rows), 9))
    png += chunk(b"IEND", b"")
    with open(path, "wb") as fh:
        fh.write(png)


# ---------------------------------------------------------------- lettering
def glyphs(ch, x, base, u, r):
    """Centre-line strokes of a bold geometric lowercase, x-height u, origin at
    (x, base) on the baseline, y down. Returns (prims, advance)."""
    Y = lambda v: base - v * u  # glyph units (y up) -> canvas
    X = lambda v: x + v * u
    P = []
    if ch == "m":
        hw = 0.36
        P += [Capsule(X(0), Y(0), X(0), Y(1 - hw), r)]
        P += [Arc(X(hw), Y(1 - hw), hw * u, 0, 180, r)]
        P += [Arc(X(3 * hw), Y(1 - hw), hw * u, 0, 180, r)]
        P += [Capsule(X(2 * hw), Y(0), X(2 * hw), Y(1 - hw), r)]
        P += [Capsule(X(4 * hw), Y(0), X(4 * hw), Y(1 - hw), r)]
        P += [Capsule(X(0), Y(0), X(0), Y(1), r)]
        wdt = 4 * hw
    elif ch == "a":
        P += [Arc(X(0.5), Y(0.5), 0.5 * u, 0, 360, r)]
        P += [Capsule(X(1), Y(0), X(1), Y(1), r)]
        wdt = 1.0
    elif ch == "k":
        P += [Capsule(X(0), Y(0), X(0), Y(1.5), r)]
        P += [Capsule(X(0.78), Y(1), X(0.05), Y(0.38), r)]
        P += [Capsule(X(0.3), Y(0.58), X(0.82), Y(0), r)]
        wdt = 0.82
    elif ch == "e":
        P += [Arc(X(0.5), Y(0.5), 0.5 * u, 0, 300, r)]
        P += [Capsule(X(0), Y(0.5), X(1), Y(0.5), r)]
        wdt = 1.0
    elif ch == ".":
        P += [Circle(X(0), Y(0), r * 1.2)]
        wdt = 0.0
    elif ch == "f":
        P += [Capsule(X(0.2), Y(0), X(0.2), Y(1.15), r)]
        P += [Arc(X(0.6), Y(1.15), 0.4 * u, 90, 90, r)]
        P += [Capsule(X(0.6), Y(1.55), X(0.8), Y(1.55), r)]
        P += [Capsule(X(-0.05), Y(0.95), X(0.7), Y(0.95), r)]
        wdt = 0.8
    elif ch == "u":
        P += [Capsule(X(0), Y(1), X(0), Y(0.5), r)]
        P += [Arc(X(0.5), Y(0.5), 0.5 * u, 180, 180, r)]
        P += [Capsule(X(1), Y(1), X(1), Y(0), r)]
        wdt = 1.0
    elif ch == "n":
        P += [Capsule(X(0), Y(0), X(0), Y(1), r)]
        P += [Arc(X(0.5), Y(0.5), 0.5 * u, 0, 180, r)]
        P += [Capsule(X(1), Y(0.5), X(1), Y(0), r)]
        wdt = 1.0
    else:
        raise ValueError(ch)
    return P, wdt * u


def text_prims(s, cx, base, u, r, gap):
    widths = [glyphs(c, 0, 0, u, r)[1] for c in s]
    total = sum(widths) + gap * (len(s) - 1)
    x = cx - total / 2
    out = []
    for c, wdt in zip(s, widths):
        p, _ = glyphs(c, x, base, u, r)
        out += p
        x += wdt + gap
    # centre on the real ink extents, not on advance widths
    bb = [p.bbox() for p in out]
    shift = cx - (min(b[0] for b in bb) + max(b[2] for b in bb)) / 2
    for p in out:
        move(p, shift)
    return out


def move(p, dx):
    """Shift a lettering primitive horizontally in place."""
    if isinstance(p, Capsule):
        p.ax += dx
        p.bx += dx
    elif isinstance(p, Arc):
        p.cx += dx
        p.e0 = (p.e0[0] + dx, p.e0[1])
        p.e1 = (p.e1[0] + dx, p.e1[1])
    else:
        p.cx += dx


def star(cx, cy, s):
    """Four-point sparkle of radius s with slightly rounded tips."""
    pts = []
    for i in range(8):
        a = math.pi / 4 * i
        rr = s if i % 2 == 0 else s * 0.3
        pts.append((cx + rr * math.sin(a), cy - rr * math.cos(a)))
    return Poly(pts, 3)


# ---------------------------------------------------------------- the art
INK = (22, 18, 48)
WHITE = (255, 255, 255)
VIOLET = (124, 92, 255)
VIOLET_LIGHT = (184, 168, 255)
SCREEN = (30, 26, 70)
SCREEN_LIGHT = (66, 60, 130)
MINT = (61, 245, 200)
GOLD = (255, 194, 51)
CORAL = (255, 84, 112)


def main():
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(out_dir, exist_ok=True)
    cv = Canvas()

    dy = 58  # vertical placement of the robot
    head = [RBox(262, 250 + dy, 762, 610 + dy, 96)]
    ears = [RBox(218, 360 + dy, 280, 500 + dy, 24), RBox(744, 360 + dy, 806, 500 + dy, 24)]
    crown = [Poly([(360, 250 + dy), (360, 128 + dy), (440, 184 + dy), (512, 84 + dy),
                   (584, 184 + dy), (664, 128 + dy), (664, 250 + dy)], 8)]
    crown_balls = [Circle(360, 124 + dy, 22), Circle(512, 78 + dy, 26), Circle(664, 124 + dy, 22)]
    # the "1" on the crown: this agent is ranked first
    one = [Capsule(520, 150 + dy, 520, 214 + dy, 11), Capsule(520, 150 + dy, 496, 168 + dy, 11)]
    screen = [RBox(316, 300 + dy, 708, 560 + dy, 64)]
    eyes = [Arc(428, 440 + dy, 46, 20, 140, 18), Arc(596, 440 + dy, 46, 20, 140, 18)]
    mouth = [Arc(512, 470 + dy, 40, 200, 140, 14)]
    sparkles = [star(232, 196 + dy, 54), star(800, 230 + dy, 40)]
    shine = [Capsule(338, 279 + dy, 410, 279 + dy, 9), Circle(438, 279 + dy, 9)]
    glare = [Capsule(640, 334 + dy, 668, 362 + dy, 8)]
    U, SR = 74, 11.6
    base = 866
    gap = 2 * SR + 0.2 * U
    word = text_prims("make.fun", 510, base, U, SR, gap)
    shadow = text_prims("make.fun", 514, base + 11, U, SR, gap)
    OUT = 14
    CUT = 38
    SMOOTH = 80.0
    reach = CUT + 8 + SMOOTH  # far enough that the blend has no seams
    # the wordmark sits on a clean rounded nameplate rather than a bumpy
    # offset of every letter; its top overlaps the chin so no pocket forms
    tb = [p.bbox() for p in word + shadow]
    plate = RBox(min(b[0] for b in tb) - 34, min(b[1] for b in tb) - 26,
                 max(b[2] for b in tb) + 34, max(b[3] for b in tb) + 26, 46)
    allf = Field.blend([
        Field(head + ears + crown + crown_balls, reach),
        Field([plate], reach),
        Field(sparkles[:1], reach),
        Field(sparkles[1:], reach),
    ], SMOOTH).contour(CUT)
    allf.paint(cv, INK, 6)
    allf.paint(cv, WHITE, 0)

    for prims, col in ((sparkles, GOLD), (ears, VIOLET), (crown, GOLD), (crown_balls, GOLD), (head, VIOLET)):
        f = Field(prims, OUT + 2)
        f.paint(cv, INK, OUT)
        f.paint(cv, col, 0)
    Field(one, 2).paint(cv, INK)
    Field(shine, 2).paint(cv, VIOLET_LIGHT)
    Field(screen, 2).paint(cv, SCREEN)
    Field(glare, 2).paint(cv, SCREEN_LIGHT)
    Field(eyes, 2).paint(cv, MINT)
    Field(mouth, 2).paint(cv, MINT)
    # ink badge behind the wordmark; the die-cut keeps an even margin round it
    Field([plate], 2).paint(cv, INK)
    Field(shadow, 2).paint(cv, CORAL)
    Field(word, 2).paint(cv, WHITE)

    write_png(os.path.join(out_dir, "entry.png"), cv)


if __name__ == "__main__":
    main()
