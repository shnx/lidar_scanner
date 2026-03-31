#!/usr/bin/env python3
"""
generate_icon.py — Standalone icon generator (no X11 display needed).
Creates assets/icon.png and assets/icons/*.png using Pillow.
Run this if install.sh's Qt-based generation fails in headless environments.

Usage:
    python3 assets/generate_icon.py
"""

import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
    _PIL = True
except ImportError:
    _PIL = False

ASSETS_DIR = Path(__file__).parent
ICONS_DIR = ASSETS_DIR / "icons"
ICONS_DIR.mkdir(parents=True, exist_ok=True)


def _hex_to_rgb(h: str):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def _make_main_icon():
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    draw.rounded_rectangle([8, 8, size-8, size-8],
                            radius=40,
                            fill=_hex_to_rgb("#161b22"),
                            outline=_hex_to_rgb("#30363d"),
                            width=2)

    try:
        font_lg = ImageFont.truetype("/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf", 52)
        font_sm = ImageFont.truetype("/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf", 16)
    except (IOError, OSError):
        font_lg = ImageFont.load_default()
        font_sm = ImageFont.load_default()

    draw.text((128, 90), "SLAM", font=font_lg,
              fill=_hex_to_rgb("#58a6ff"), anchor="mm")
    draw.text((128, 145), "LAUNCHER", font=font_sm,
              fill=_hex_to_rgb("#8b949e"), anchor="mm")

    draw.ellipse([110, 182, 146, 218], fill=_hex_to_rgb("#3fb950"))

    path = ASSETS_DIR / "icon.png"
    img.save(path)
    print(f"[✓] {path}")


def _make_pkg_icons():
    packages = {
        "lidar":       "#2ECC71",
        "calibration": "#3498DB",
        "odometry":    "#9B59B6",
        "slam":        "#E74C3C",
    }
    for name, color in packages.items():
        img = Image.new("RGBA", (48, 48), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([4, 4, 44, 44], fill=_hex_to_rgb(color))
        path = ICONS_DIR / f"{name}.png"
        img.save(path)
        print(f"[✓] {path}")


def _make_fallback_png(path: Path, color: str, size: int = 256):
    """Create a solid-color PNG when Pillow is unavailable."""
    r, g, b = _hex_to_rgb(color)
    raw_bytes = bytes([r, g, b, 255] * (size * size))
    import struct, zlib

    def png_chunk(chunk_type: bytes, data: bytes) -> bytes:
        c = chunk_type + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = png_chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))

    raw_rows = b"".join(b"\x00" + raw_bytes[i*size*4:(i+1)*size*4] for i in range(size))
    idat = png_chunk(b"IDAT", zlib.compress(raw_rows))
    iend = png_chunk(b"IEND", b"")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(sig + ihdr + idat + iend)
    print(f"[✓] fallback {path}")


if __name__ == "__main__":
    if _PIL:
        _make_main_icon()
        _make_pkg_icons()
    else:
        print("[!] Pillow not found — generating minimal fallback PNGs")
        _make_fallback_png(ASSETS_DIR / "icon.png", "#161b22")
        for name, color in [("lidar","#2ECC71"),("calibration","#3498DB"),
                             ("odometry","#9B59B6"),("slam","#E74C3C")]:
            _make_fallback_png(ICONS_DIR / f"{name}.png", color, 48)
