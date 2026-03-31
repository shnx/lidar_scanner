"""
scale.py — Global UI scale factor for DPI-agnostic, resolution-independent layouts.

The factor is computed once at startup from the detected screen geometry
relative to a 1920×1080 reference, then clamped to a safe range so the UI
stays readable even when the GPU/DRM reports an incorrect resolution (e.g.
falling back to 1024×600 on an embedded X11 system).

Usage:
    # In main.py:
    from gui import scale as ui_scale
    ui_scale.init(factor)

    # Anywhere in the GUI:
    from gui.scale import px
    widget.setMinimumHeight(px(100))
"""

from __future__ import annotations
from typing import Optional

# ── Internal state ────────────────────────────────────────────────────────────
_factor: float = 1.0
_screen_w: int = 1920
_screen_h: int = 1080

# Reference resolution against which all design values are specified
_REF_W: int = 1920
_REF_H: int = 1080

# Safe clamping range
_MIN_FACTOR: float = 0.65   # below this, fonts become unreadable
_MAX_FACTOR: float = 2.00   # above this, widgets overflow even on 4K


# ── Public API ────────────────────────────────────────────────────────────────

def init(screen_w: int, screen_h: int) -> float:
    """
    Compute and store the scale factor from detected screen geometry.
    Returns the clamped factor.
    """
    global _factor, _screen_w, _screen_h
    _screen_w = screen_w
    _screen_h = screen_h

    raw = min(screen_w / _REF_W, screen_h / _REF_H)
    _factor = max(_MIN_FACTOR, min(_MAX_FACTOR, raw))
    return _factor


def factor() -> float:
    """Return the current scale factor."""
    return _factor


def screen_size() -> tuple[int, int]:
    """Return the detected screen (width, height)."""
    return _screen_w, _screen_h


def px(n: int) -> int:
    """
    Convert a reference-resolution pixel value to the current screen scale.
    Always returns at least 1.
    """
    return max(1, round(n * _factor))


def pxf(n: float) -> int:
    """Floating-point variant of px()."""
    return max(1, round(n * _factor))


def is_small_screen() -> bool:
    """True when the reported screen width is ≤ 1280 (compact/fallback mode)."""
    return _screen_w <= 1280
