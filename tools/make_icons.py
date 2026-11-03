"""Render the WatchBridge launcher icon at the Sailfish sizes (no dependencies).

    python3 tools/make_icons.py
"""

import math
import os
import struct
import zlib

SIZES = (86, 108, 128, 172)
SS = 4  # supersampling per axis


def png(path, size, pixels):
    raw = b"".join(b"\x00" + bytes(row) for row in pixels)

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)) \
        + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def mix(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(len(a)))


def seg_dist(px, py, ax, ay, bx, by):
    vx, vy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / (vx * vx + vy * vy)))
    return math.hypot(px - ax - vx * t, py - ay - vy * t)


def rrect(px, py, cx, cy, hw, hh, r):
    qx, qy = abs(px - cx) - hw + r, abs(py - cy) - hh + r
    return math.hypot(max(qx, 0), max(qy, 0)) + min(max(qx, qy), 0) - r


TEAL = (0x1F, 0xD1, 0xB2)
BLUE = (0x2F, 0x6B, 0xF2)
STRAP = (0x2A, 0x2E, 0x36)
FACE = (0x14, 0x17, 0x1C)
WHITE = (0xFF, 0xFF, 0xFF)


def shade(x, y):
    """Colour (r, g, b, a) at normalised coords, centre (0, 0), radius 1 = icon edge."""
    layers = []
    r = math.hypot(x, y)
    # straps
    if rrect(x, y, 0, 0, 0.42, 0.98, 0.16) < 0:
        shine = 0.06 * (1 - abs(x) / 0.42)
        layers.append(mix(STRAP, WHITE, shine) + (1.0,))
    # bezel with diagonal gradient
    if r < 0.80:
        t = (x + y + 1.6) / 3.2
        layers.append(mix(TEAL, BLUE, max(0, min(1, t))) + (1.0,))
    # face
    if r < 0.64:
        layers.append(FACE + (1.0,))
        # notification arc (top-right, like a battery/notification ring)
        ang = math.atan2(x, -y)
        if 0.50 < r < 0.56 and -0.2 < ang < 1.9:
            layers.append(TEAL + (1.0,))
        # hour ticks
        for i in range(12):
            a = i * math.pi / 6
            d = seg_dist(x, y, math.sin(a) * 0.40, -math.cos(a) * 0.40, math.sin(a) * 0.46, -math.cos(a) * 0.46)
            if d < (0.025 if i % 3 == 0 else 0.012):
                layers.append(WHITE + (0.9 if i % 3 == 0 else 0.45,))
        # hands at 10:10
        if seg_dist(x, y, 0, 0, math.sin(-1.05) * 0.26, -math.cos(-1.05) * 0.26) < 0.04:
            layers.append(WHITE + (1.0,))
        if seg_dist(x, y, 0, 0, math.sin(1.05) * 0.38, -math.cos(1.05) * 0.38) < 0.03:
            layers.append(WHITE + (1.0,))
        if r < 0.05:
            layers.append(TEAL + (1.0,))
    # crown
    if rrect(x, y, 0.82, 0, 0.05, 0.09, 0.03) < 0 and r >= 0.78:
        layers.append((0x9A, 0xA4, 0xB2, 1.0))
    if not layers:
        return (0, 0, 0, 0.0)
    out = (0, 0, 0, 0.0)
    for c in layers:  # simple "over" compositing, back to front
        a = c[3] + out[3] * (1 - c[3])
        if a == 0:
            continue
        out = tuple((c[i] * c[3] + out[i] * out[3] * (1 - c[3])) / a for i in range(3)) + (a,)
    return out


def render(size):
    rows = []
    for py in range(size):
        row = []
        for px in range(size):
            acc = [0.0, 0.0, 0.0, 0.0]
            for sy in range(SS):
                for sx in range(SS):
                    x = ((px + (sx + 0.5) / SS) / size) * 2 - 1
                    y = ((py + (sy + 0.5) / SS) / size) * 2 - 1
                    r, g, b, a = shade(x * 1.02, y * 1.02)
                    acc[0] += r * a
                    acc[1] += g * a
                    acc[2] += b * a
                    acc[3] += a
            n = SS * SS
            a = acc[3] / n
            if a > 0:
                row += [int(round(acc[0] / acc[3])), int(round(acc[1] / acc[3])), int(round(acc[2] / acc[3])),
                        int(round(a * 255))]
            else:
                row += [0, 0, 0, 0]
        rows.append(row)
    return rows


if __name__ == "__main__":
    root = os.path.join(os.path.dirname(__file__), "..", "icons")
    for s in SIZES:
        png(os.path.join(root, "%dx%d" % (s, s), "harbour-watchbridge.png"), s, render(s))
        print("wrote %dx%d" % (s, s))
