#!/usr/bin/env python3
"""
SLAM Launcher — Entry point.

Usage:
    python3 main.py [--lang en|ar] [--loglevel DEBUG|INFO|WARNING]
"""

import sys
import os
import argparse
import logging
from pathlib import Path

# ── Ensure project root is on sys.path ──────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

# ── Qt platform safety (headless / Wayland fallback) ────────────────────────
if "DISPLAY" not in os.environ and "WAYLAND_DISPLAY" not in os.environ:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import yaml
from PyQt5.QtWidgets import QApplication, QSplashScreen, QLabel
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QFontDatabase, QPixmap

from gui.main_window import MainWindow
from gui import i18n


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
# Stylesheet
# ---------------------------------------------------------------------------

def _load_stylesheet(app: QApplication) -> None:
    qss_path = PROJECT_ROOT / "gui" / "styles.qss"
    if qss_path.is_file():
        with open(qss_path, "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())
    else:
        logging.warning(f"Stylesheet not found: {qss_path}")


# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------

def _load_fonts() -> None:
    font_dir = PROJECT_ROOT / "assets" / "fonts"
    if font_dir.is_dir():
        for font_file in font_dir.glob("*.ttf"):
            QFontDatabase.addApplicationFont(str(font_file))
        for font_file in font_dir.glob("*.otf"):
            QFontDatabase.addApplicationFont(str(font_file))


# ---------------------------------------------------------------------------
# Splash screen
# ---------------------------------------------------------------------------

def _make_splash(app: QApplication) -> QSplashScreen:
    icon_path = PROJECT_ROOT / "assets" / "icon.png"
    if icon_path.exists():
        pix = QPixmap(str(icon_path)).scaled(320, 320, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    else:
        pix = QPixmap(320, 180)
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

    # ── Load resources ───────────────────────────────────────────────
    config = _load_config()
    _load_fonts()
    _load_stylesheet(app)

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
    splash = _make_splash(app)

    # ── Main window ──────────────────────────────────────────────────
    window = MainWindow(config)

    def _show_window():
        splash.finish(window)
        window.show()
        window.raise_()

    QTimer.singleShot(1200, _show_window)

    log.info("Event loop started")
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
