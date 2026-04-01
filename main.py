#!/usr/bin/env python3
"""
SLAM Launcher — Entry point.

Usage:
    python3 main.py [--lang en|ar] [--loglevel DEBUG|INFO|WARNING]
"""

import sys
import os
import re
import argparse
import logging
from pathlib import Path

# ── Ensure project root is on sys.path ──────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

# ── Disable Qt's built-in DPI scaling ───────────────────────────────────────
# On embedded X11 systems the GPU/DRM may report wrong DPI/resolution.
# We handle scaling ourselves via gui.scale so Qt must not interfere.
os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "0"
os.environ["QT_SCREEN_SCALE_FACTORS"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "xcb")  # force X11 on embedded

# ── Qt platform safety (headless fallback) ───────────────────────────────────
if "DISPLAY" not in os.environ and "WAYLAND_DISPLAY" not in os.environ:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

import yaml
from PyQt5.QtWidgets import QApplication, QSplashScreen, QLabel
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QFontDatabase, QPixmap

# Disable Qt high-DPI scaling BEFORE QApplication is created
QApplication.setAttribute(Qt.AA_DisableHighDpiScaling, True)
QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, False)

from gui.main_window import MainWindow
from gui import i18n
from gui import scale as ui_scale


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _setup_logging(level: str) -> None:
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)

    fmt = "[%(levelname)s] %(asctime)s %(name)s: %(message)s"
    datefmt = "%H:%M:%S"

    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_dir / "slam_launcher.log", encoding="utf-8"),
    ]
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO),
                        format=fmt, datefmt=datefmt, handlers=handlers)

    logging.getLogger("PyQt5").setLevel(logging.WARNING)
    logging.getLogger("open3d").setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Config loaders
# ---------------------------------------------------------------------------

def _load_yaml(path: Path) -> dict:
    if not path.is_file():
        logging.error(f"Config file not found: {path}")
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _load_config() -> dict:
    cfg_dir = PROJECT_ROOT / "config"
    return {
        "packages":    _load_yaml(cfg_dir / "packages.yaml").get("packages", {}),
        "settings":    _load_yaml(cfg_dir / "settings.yaml"),
        "translations": cfg_dir / "translations.yaml",
    }


# ---------------------------------------------------------------------------
# Stylesheet  (scaled for current screen resolution)
# ---------------------------------------------------------------------------

def _scale_px_values(css: str, scale: float) -> str:
    """Multiply every bare NNpx token in a QSS string by *scale*."""
    if abs(scale - 1.0) < 0.01:
        return css
    def _rep(m) -> str:
        return f"{max(1, round(int(m.group(1)) * scale))}px"
    return re.sub(r'\b(\d+)px\b', _rep, css)


def _load_stylesheet(app: QApplication, scale: float = 1.0) -> None:
    qss_path = PROJECT_ROOT / "gui" / "styles.qss"
    if not qss_path.is_file():
        logging.warning(f"Stylesheet not found: {qss_path}")
        return
    with open(qss_path, "r", encoding="utf-8") as f:
        css = f.read()
    app.setStyleSheet(_scale_px_values(css, scale))


# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------

def _load_fonts(base_pt: int = 10) -> None:
    font_dir = PROJECT_ROOT / "assets" / "fonts"
    if font_dir.is_dir():
        for font_file in font_dir.glob("*.ttf"):
            QFontDatabase.addApplicationFont(str(font_file))
        for font_file in font_dir.glob("*.otf"):
            QFontDatabase.addApplicationFont(str(font_file))


# ---------------------------------------------------------------------------
# Screen geometry & scale
# ---------------------------------------------------------------------------

def _detect_screen(app: QApplication) -> tuple:
    """
    Return (width, height, scale_factor) of the primary available screen.
    Falls back to 1920×1080 if detection fails.
    """
    try:
        screen = app.primaryScreen()
        geo = screen.availableGeometry()
        w, h = geo.width(), geo.height()
        # Sanity-check: if the reported size is suspiciously small,
        # trust physical size from the screen object instead
        phys = screen.geometry()
        if phys.width() > w:
            w, h = phys.width(), phys.height()
    except Exception:
        w, h = 1920, 1080

    if w < 320 or h < 240:          # completely bogus
        w, h = 1920, 1080

    scale = ui_scale.init(w, h)
    return w, h, scale


# ---------------------------------------------------------------------------
# Splash screen
# ---------------------------------------------------------------------------

def _make_splash(app: QApplication, scale: float) -> QSplashScreen:
    splash_size = ui_scale.px(320)
    icon_path = PROJECT_ROOT / "assets" / "icon.png"
    if icon_path.exists():
        pix = QPixmap(str(icon_path)).scaled(
            splash_size, splash_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    else:
        pix = QPixmap(splash_size, max(1, round(splash_size * 0.56)))
        pix.fill(Qt.black)

    splash = QSplashScreen(pix, Qt.WindowStaysOnTopHint)
    splash.showMessage(
        "Loading SLAM Launcher…",
        Qt.AlignBottom | Qt.AlignHCenter,
        Qt.white
    )
    splash.show()
    app.processEvents()
    return splash


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="SLAM Launcher")
    parser.add_argument("--lang", choices=["en", "ar"], default=None,
                        help="Override UI language")
    parser.add_argument("--loglevel", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        help="Logging verbosity")
    args = parser.parse_args()

    _setup_logging(args.loglevel)
    log = logging.getLogger(__name__)
    log.info("SLAM Launcher starting …")

    app = QApplication(sys.argv)
    app.setApplicationName("SLAM Launcher")
    app.setOrganizationName("SLAMLauncher")
    app.setApplicationVersion("1.0.0")

    # ── Screen detection & scale ──────────────────────────────────────
    sw, sh, scale = _detect_screen(app)
    log.info(f"Screen: {sw}×{sh}  |  UI scale: {scale:.3f}")

    # ── Base application font (pt units, DPI-independent) ────────────
    # 10pt at 96 DPI ≈ 13px on 1920×1080; stays readable at all scales
    base_pt = max(8, round(10 * scale))
    app.setFont(QFont("Ubuntu", base_pt))

    # ── Load resources ───────────────────────────────────────────────
    config = _load_config()
    config["screen"] = {"width": sw, "height": sh, "scale": scale}
    _load_fonts()
    _load_stylesheet(app, scale)

    # ── i18n ─────────────────────────────────────────────────────────
    trans_path = config.pop("translations")
    i18n.load(trans_path)
    lang = args.lang or config.get("settings", {}).get("app", {}).get("language", "en")
    i18n.set_language(lang)
    if i18n.is_rtl():
        app.setLayoutDirection(Qt.RightToLeft)

    if not config.get("packages"):
        log.error("No packages configured. Check config/packages.yaml.")
        return 1

    # ── Splash ───────────────────────────────────────────────────────
    splash = _make_splash(app, scale)

    # ── Main window ──────────────────────────────────────────────────
    window = MainWindow(config)

    def _show_window():
        splash.finish(window)
        if ui_scale.is_small_screen():
            window.showMaximized()   # fill all available pixels on small screens
        else:
            window.show()
        window.raise_()

    QTimer.singleShot(1200, _show_window)

    log.info("Event loop started")
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
