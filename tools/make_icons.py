"""Generate the PWA icon set without any image library.

Run:  python tools/make_icons.py

Produces (under ../web/public/icons):
    icon-192.png, icon-512.png, icon-512-maskable.png, apple-touch-icon.png

The artwork is drawn with plain arithmetic into an RGBA buffer and encoded as
PNG by hand (zlib + struct), so the repo has no Pillow/cairo dependency and the
icons are reproducible on any machine with CPython.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "web" / "public" / "icons"

BRAND_TOP = (51, 102, 255)      # #3366ff
BRAND_BOTTOM = (26, 55, 180)    # #1a37b4
WHITE = (255, 255, 255)


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _rounded_alpha(x: float, y: float, left: float, top: float, right: float, bottom: float, radius: float) -> float:
    """Coverage of a rounded rectangle at point (x, y) — 1 inside, 0 outside."""
    cx = min(max(x, left + radius), right - radius)
    cy = min(max(y, top + radius), bottom - radius)
    dx = x - cx
    dy = y - cy
    # inside the straight edges → covered
    if left <= x <= right and top <= y <= bottom and (abs(dx) < 1e-9 or abs(dy) < 1e-9):
        return 1.0
    dist = (dx * dx + dy * dy) ** 0.5
    if dist <= radius - 0.5:
        return 1.0
    if dist >= radius + 0.5:
        return 0.0
    return radius + 0.5 - dist


def render(size: int, maskable: bool = False) -> bytes:
    """Return raw RGBA pixels for one icon."""
    pixels = bytearray()

    pad = size * 0.18 if maskable else 0.0  # maskable icons need a safe zone
    tile = size - pad * 2
    radius = tile * 0.22

    # calendar glyph geometry
    body_left = pad + tile * 0.18
    body_right = pad + tile * 0.82
    body_top = pad + tile * 0.28
    body_bottom = pad + tile * 0.80
    header_bottom = body_top + tile * 0.12
    ring_r = tile * 0.030

    for y in range(size):
        for x in range(size):
            px = x + 0.5
            py = y + 0.5

            cover = _rounded_alpha(px, py, pad, pad, size - pad, size - pad, radius)
            if cover <= 0:
                pixels += bytes((0, 0, 0, 0))
                continue

            t = (py - pad) / tile if tile else 0
            base = (
                int(_lerp(BRAND_TOP[0], BRAND_BOTTOM[0], t)),
                int(_lerp(BRAND_TOP[1], BRAND_BOTTOM[1], t)),
                int(_lerp(BRAND_TOP[2], BRAND_BOTTOM[2], t)),
            )

            colour = base

            # calendar body (white), header bar in brand colour
            body = _rounded_alpha(px, py, body_left, body_top, body_right, body_bottom, tile * 0.06)
            if body > 0:
                if py <= header_bottom:
                    colour = base  # header stays brand coloured
                else:
                    colour = WHITE

            # two binding rings straddling the top edge of the body
            for ring_x in (body_left + tile * 0.22, body_right - tile * 0.22):
                dist = ((px - ring_x) ** 2 + (py - (body_top - tile * 0.02)) ** 2) ** 0.5
                if dist <= ring_r:
                    colour = WHITE

            # event dots (brand coloured) inside the body, square pitch
            for row in range(3):
                for col in range(4):
                    dot_x = body_left + tile * (0.13 + 0.16 * col)
                    dot_y = header_bottom + tile * (0.085 + 0.155 * row)
                    if (px - dot_x) ** 2 + (py - dot_y) ** 2 <= (tile * 0.026) ** 2:
                        colour = base

            pixels += bytes((colour[0], colour[1], colour[2], int(round(255 * cover))))

    return bytes(pixels)


def encode_png(width: int, height: int, rgba: bytes) -> bytes:
    """Minimal PNG encoder (8-bit RGBA, no interlace)."""
    raw = bytearray()
    stride = width * 4
    for row in range(height):
        raw.append(0)  # filter type 0
        raw += rgba[row * stride : (row + 1) * stride]

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def write(path: Path, size: int, maskable: bool = False) -> None:
    path.write_bytes(encode_png(size, size, render(size, maskable=maskable)))
    print(f"wrote {path} ({path.stat().st_size} bytes)")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write(OUT_DIR / "icon-192.png", 192)
    write(OUT_DIR / "icon-512.png", 512)
    write(OUT_DIR / "icon-512-maskable.png", 512, maskable=True)
    write(OUT_DIR / "apple-touch-icon.png", 180)


if __name__ == "__main__":
    main()
