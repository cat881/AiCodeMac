#!/usr/bin/env python3
"""Generate AppIcon.iconset PNGs for AiCode (stdlib only, no dependencies)."""
import math
import os
import struct
import sys
import zlib

VARIANTS = [
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
]

C1 = (0.36, 0.40, 0.98)
C2 = (0.58, 0.27, 0.95)


def _seg_dist(px, py, ax, ay, bx, by):
    vx = bx - ax
    vy = by - ay
    wx = px - ax
    wy = py - ay
    denom = vx * vx + vy * vy
    t = 0.0 if denom == 0 else (wx * vx + wy * vy) / denom
    t = 0.0 if t < 0 else (1.0 if t > 1 else t)
    dx = wx - t * vx
    dy = wy - t * vy
    return math.sqrt(dx * dx + dy * dy)


def render(size):
    s = float(size)
    pad = 0.055 * s
    radius = 0.225 * s
    hw = s / 2 - pad
    inner = hw - radius
    cx = cy = s / 2

    segs = (
        (0.300 * s, 0.340 * s, 0.505 * s, 0.500 * s, 0.076 * s, 1.00),
        (0.505 * s, 0.500 * s, 0.300 * s, 0.660 * s, 0.076 * s, 1.00),
        (0.575 * s, 0.665 * s, 0.735 * s, 0.665 * s, 0.060 * s, 0.72),
    )

    out = bytearray(size * size * 4)
    i = 0
    hypot = math.hypot
    for y in range(size):
        py = y + 0.5
        for x in range(size):
            px = x + 0.5
            qx = abs(px - cx) - inner
            qy = abs(py - cy) - inner
            mx = qx if qx > 0 else 0.0
            my = qy if qy > 0 else 0.0
            d = hypot(mx, my) + (min(max(qx, qy), 0.0)) - radius
            a = 0.5 - d
            if a <= 0:
                i += 4
                continue
            if a > 1:
                a = 1.0

            t = (px * 0.45 + (s - py) * 0.55) / s
            if t < 0:
                t = 0.0
            elif t > 1:
                t = 1.0
            r = C1[0] + (C2[0] - C1[0]) * t
            g = C1[1] + (C2[1] - C1[1]) * t
            b = C1[2] + (C2[2] - C1[2]) * t

            for ax, ay, bx, by, thick, alpha in segs:
                dd = _seg_dist(px, py, ax, ay, bx, by) - thick / 2
                cov = 0.5 - dd
                if cov <= 0:
                    continue
                if cov > 1:
                    cov = 1.0
                cov *= alpha
                r += (1.0 - r) * cov
                g += (1.0 - g) * cov
                b += (1.0 - b) * cov

            out[i] = int(r * 255 + 0.5)
            out[i + 1] = int(g * 255 + 0.5)
            out[i + 2] = int(b * 255 + 0.5)
            out[i + 3] = int(a * 255 + 0.5)
            i += 4
    return out


def write_png(path, size, rgba):
    raw = bytearray()
    stride = size * 4
    for y in range(size):
        raw.append(0)
        raw += rgba[y * stride:(y + 1) * stride]

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) +
           chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "AppIcon.iconset"
    os.makedirs(out, exist_ok=True)
    done = {}
    for name, size in VARIANTS:
        if size not in done:
            done[size] = render(size)
        write_png(os.path.join(out, name), size, done[size])
        print("  %s (%dpx)" % (name, size))


if __name__ == "__main__":
    main()
