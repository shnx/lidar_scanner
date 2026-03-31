"""
StatusPanel — Real-time metrics bar + scrolling log view.
"""

import time
from typing import Optional
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPlainTextEdit, QFrame, QSizePolicy, QPushButton
)
from PyQt5.QtCore import Qt, QTimer, pyqtSlot
from PyQt5.QtGui import QTextCursor, QColor

from . import i18n

# ANSI-to-HTML colour map for log levels
_LEVEL_STYLES = {
    "debug":   "color: #8b949e;",
    "info":    "color: #c9d1d9;",
    "warning": "color: #d29922; font-weight: 600;",
    "error":   "color: #f85149; font-weight: 600;",
    "success": "color: #3fb950; font-weight: 600;",
}


class MetricWidget(QWidget):
    """Single metric display: label on top, large value below."""

    def __init__(self, label: str = "", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignCenter)

        self._lbl_label = QLabel(label)
        self._lbl_label.setObjectName("metricLabel")
        self._lbl_label.setAlignment(Qt.AlignCenter)

        self._lbl_value = QLabel("—")
        self._lbl_value.setObjectName("metricValue")
        self._lbl_value.setAlignment(Qt.AlignCenter)

        layout.addWidget(self._lbl_label)
        layout.addWidget(self._lbl_value)

    def set_label(self, text: str):
        self._lbl_label.setText(text)

    def set_value(self, text: str, state: str = "normal"):
        self._lbl_value.setText(text)
        self._lbl_value.setProperty("warning", "true" if state == "warning" else "false")
        self._lbl_value.setProperty("error", "true" if state == "error" else "false")
        self._lbl_value.style().unpolish(self._lbl_value)
        self._lbl_value.style().polish(self._lbl_value)


class MetricsBar(QFrame):
    """Horizontal bar showing FPS, tracking state, points count, session time."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("metricsBar")
        self.setFixedHeight(72)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(0)

        self._fps = MetricWidget()
        self._tracking = MetricWidget()
        self._points = MetricWidget()
        self._session = MetricWidget()

        for w in (self._fps, self._tracking, self._points, self._session):
            layout.addWidget(w)
            sep = QFrame()
            sep.setFrameShape(QFrame.VLine)
            sep.setStyleSheet("color: #30363d;")
            layout.addWidget(sep)
        layout.takeAt(layout.count() - 1)

        self._start_time: Optional[float] = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick_session)
        self.retranslate()
        self.reset()

    def retranslate(self):
        self._fps.set_label(i18n.t("label_fps"))
        self._tracking.set_label(i18n.t("label_tracking"))
        self._points.set_label(i18n.t("label_points"))
        self._session.set_label(i18n.t("label_session"))

    def reset(self):
        self._fps.set_value("—")
        self._tracking.set_value("—")
        self._points.set_value("—")
        self._session.set_value("00:00")
        self._start_time = None
        self._timer.stop()

    def session_started(self):
        self._start_time = time.monotonic()
        self._timer.start(1000)

    def session_stopped(self):
        self._timer.stop()

    def update_fps(self, fps: float):
        if fps < 1.0:
            self._fps.set_value(f"{fps:.1f}", "warning")
        else:
            self._fps.set_value(f"{fps:.1f}")

    def update_tracking(self, state: str):
        mapping = {
            "ok":           (i18n.t("tracking_ok"),           "normal"),
            "lost":         (i18n.t("tracking_lost"),         "error"),
            "initializing": (i18n.t("tracking_initializing"), "warning"),
        }
        text, level = mapping.get(state.lower(), (state, "normal"))
        self._tracking.set_value(text, level)

    def update_points(self, count: int):
        if count >= 1_000_000:
            self._points.set_value(f"{count/1e6:.1f}M")
        elif count >= 1000:
            self._points.set_value(f"{count/1e3:.0f}K")
        else:
            self._points.set_value(str(count))

    def _tick_session(self):
        if self._start_time is None:
            return
        elapsed = int(time.monotonic() - self._start_time)
        h, rem = divmod(elapsed, 3600)
        m, s = divmod(rem, 60)
        if h > 0:
            self._session.set_value(f"{h:02d}:{m:02d}:{s:02d}")
        else:
            self._session.set_value(f"{m:02d}:{s:02d}")


class StatusPanel(QWidget):
    """
    Combined metrics bar + scrolling log panel.

    Thread-safe: append_log() may be called from any thread.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._max_lines = 2000
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # ── metrics ─────────────────────────────────────────────────
        self.metrics = MetricsBar()
        layout.addWidget(self.metrics)

        # ── log header ──────────────────────────────────────────────
        hdr = QHBoxLayout()
        self._lbl_logs = QLabel()
        self._lbl_logs.setStyleSheet("font-size: 12px; color: #8b949e; font-weight: 600;")
        hdr.addWidget(self._lbl_logs)
        hdr.addStretch()

        self._btn_clear = QPushButton("✕")
        self._btn_clear.setFixedSize(24, 24)
        self._btn_clear.setStyleSheet(
            "QPushButton { background: transparent; color: #8b949e; border: none; font-size: 14px; }"
            "QPushButton:hover { color: #f85149; }"
        )
        self._btn_clear.setToolTip("Clear logs")
        self._btn_clear.clicked.connect(self.clear_logs)
        hdr.addWidget(self._btn_clear)
        layout.addLayout(hdr)

        # ── log panel ───────────────────────────────────────────────
        self._log = QPlainTextEdit()
        self._log.setObjectName("logPanel")
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(self._max_lines)
        layout.addWidget(self._log, 1)

        self.retranslate()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def retranslate(self):
        self._lbl_logs.setText(i18n.t("label_logs").upper())
        self.metrics.retranslate()

    @pyqtSlot(str, str)
    def append_log(self, level: str, message: str):
        """Thread-safe log append. level ∈ {debug, info, warning, error, success}"""
        style = _LEVEL_STYLES.get(level.lower(), _LEVEL_STYLES["info"])
        ts = time.strftime("%H:%M:%S")
        prefix_map = {
            "debug":   "[DBG]",
            "info":    "[INF]",
            "warning": "[WRN]",
            "error":   "[ERR]",
            "success": "[OK ]",
        }
        prefix = prefix_map.get(level.lower(), "[   ]")
        html = (
            f'<span style="color: #8b949e;">{ts}</span> '
            f'<span style="{style}">{prefix} {_escape_html(message)}</span>'
        )
        self._log.appendHtml(html)
        self._log.moveCursor(QTextCursor.End)

    def clear_logs(self):
        self._log.clear()


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
    )
