"""
LauncherPanel — Grid of package cards with Start / Stop controls.
"""

from typing import Optional, Callable, Dict
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QFrame, QSizePolicy, QSpacerItem
)
from PyQt5.QtCore import Qt, pyqtSignal, QSize
from PyQt5.QtGui import QColor, QPalette, QFont

from . import i18n


class PackageCard(QFrame):
    """Single clickable card representing one SLAM package."""

    clicked = pyqtSignal(str)   # emits pkg_id

    def __init__(self, pkg_id: str, pkg_cfg: dict, parent=None):
        super().__init__(parent)
        self._pkg_id = pkg_id
        self._pkg_cfg = pkg_cfg
        self._selected = False

        self.setObjectName("packageCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(100)

        self._build_ui()
        self.set_status("idle")

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)

        # ── header row ──────────────────────────────────────────────
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)

        self._color_dot = QLabel("●")
        self._color_dot.setFixedWidth(16)
        color = self._pkg_cfg.get("color", "#58a6ff")
        self._color_dot.setStyleSheet(f"color: {color}; font-size: 14px;")

        self._lbl_name = QLabel()
        self._lbl_name.setObjectName("pkgName")

        self._lbl_status = QLabel()
        self._lbl_status.setObjectName("pkgStatus")
        self._lbl_status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        header.addWidget(self._color_dot)
        header.addWidget(self._lbl_name, 1)
        header.addWidget(self._lbl_status)

        # ── description ─────────────────────────────────────────────
        self._lbl_desc = QLabel()
        self._lbl_desc.setObjectName("pkgDesc")
        self._lbl_desc.setWordWrap(True)

        layout.addLayout(header)
        layout.addWidget(self._lbl_desc)

        self.retranslate()

    def retranslate(self):
        lang = i18n.current_language()
        self._lbl_name.setText(self._pkg_cfg.get(f"name_{lang}", self._pkg_cfg.get("name_en", self._pkg_id)))
        self._lbl_desc.setText(self._pkg_cfg.get(f"description_{lang}", self._pkg_cfg.get("description_en", "")))

    def set_status(self, status: str):
        status_texts = {
            "idle":     i18n.t("status_idle"),
            "starting": i18n.t("status_running"),
            "running":  i18n.t("status_running"),
            "stopping": i18n.t("status_stopping"),
            "crashed":  i18n.t("status_crashed"),
            "stopped":  i18n.t("status_idle"),
        }
        display = status_texts.get(status, status)
        badge_status = "running" if status in ("starting", "running") else \
                       "crashed" if status in ("crashed",) else \
                       "stopping" if status == "stopping" else "idle"

        self._lbl_status.setText(display)
        self._lbl_status.setProperty("status", badge_status)
        self._lbl_status.style().unpolish(self._lbl_status)
        self._lbl_status.style().polish(self._lbl_status)

    def set_selected(self, selected: bool):
        self._selected = selected
        self.setProperty("selected", "true" if selected else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def is_selected(self) -> bool:
        return self._selected

    def pkg_id(self) -> str:
        return self._pkg_id

    def mousePressEvent(self, event):
        self.clicked.emit(self._pkg_id)
        super().mousePressEvent(event)


class LauncherPanel(QWidget):
    """
    Shows all package cards + the global Start / Stop / Record buttons.

    Signals:
      start_requested(pkg_id, record)
      stop_requested()
    """

    start_requested = pyqtSignal(str, bool)
    stop_requested = pyqtSignal()

    def __init__(self, packages: dict, parent=None):
        super().__init__(parent)
        self._packages = packages
        self._cards: Dict[str, PackageCard] = {}
        self._selected_pkg: Optional[str] = None
        self._recording = False

        self._build_ui()
        self._update_buttons()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # ── section title ────────────────────────────────────────────
        self._lbl_select = QLabel()
        self._lbl_select.setObjectName("sectionTitle")
        self._lbl_select.setStyleSheet("font-size: 12px; color: #8b949e; font-weight: 600;")
        root.addWidget(self._lbl_select)

        # ── package grid ─────────────────────────────────────────────
        grid = QGridLayout()
        grid.setSpacing(10)
        pkg_list = list(self._packages.items())
        for idx, (pkg_id, cfg) in enumerate(pkg_list):
            card = PackageCard(pkg_id, cfg)
            card.clicked.connect(self._on_card_clicked)
            self._cards[pkg_id] = card
            row, col = divmod(idx, 2)
            grid.addWidget(card, row, col)

        root.addLayout(grid)
        root.addItem(QSpacerItem(0, 8, QSizePolicy.Minimum, QSizePolicy.Expanding))

        # ── control bar ──────────────────────────────────────────────
        ctrl = QHBoxLayout()
        ctrl.setSpacing(8)

        self._btn_start = QPushButton()
        self._btn_start.setObjectName("btnStart")
        self._btn_start.setMinimumHeight(40)
        self._btn_start.clicked.connect(self._on_start)

        self._btn_stop = QPushButton()
        self._btn_stop.setObjectName("btnStop")
        self._btn_stop.setMinimumHeight(40)
        self._btn_stop.clicked.connect(self._on_stop)

        self._btn_record = QPushButton()
        self._btn_record.setObjectName("btnRecord")
        self._btn_record.setMinimumHeight(40)
        self._btn_record.setCheckable(True)
        self._btn_record.toggled.connect(self._on_record_toggled)

        ctrl.addWidget(self._btn_start)
        ctrl.addWidget(self._btn_stop)
        ctrl.addWidget(self._btn_record)

        root.addLayout(ctrl)
        self.retranslate()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def retranslate(self):
        self._lbl_select.setText(i18n.t("label_select_package").upper())
        self._btn_start.setText(i18n.t("btn_start"))
        self._btn_stop.setText(i18n.t("btn_stop"))
        self._btn_record.setText(i18n.t("btn_record"))
        for card in self._cards.values():
            card.retranslate()
        self._update_layout_direction()

    def update_package_status(self, pkg_id: str, status: str):
        card = self._cards.get(pkg_id)
        if card:
            card.set_status(status)
        self._update_buttons()

    def set_running_state(self, running: bool, pkg_id: Optional[str] = None):
        self._btn_start.setEnabled(not running and self._selected_pkg is not None)
        self._btn_stop.setEnabled(running)
        if running and pkg_id:
            for cid, card in self._cards.items():
                card.set_selected(cid == pkg_id)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_card_clicked(self, pkg_id: str):
        if self._selected_pkg == pkg_id:
            return
        self._selected_pkg = pkg_id
        for cid, card in self._cards.items():
            card.set_selected(cid == pkg_id)
        self._update_buttons()

    def _on_start(self):
        if self._selected_pkg:
            self.start_requested.emit(self._selected_pkg, self._btn_record.isChecked())

    def _on_stop(self):
        self.stop_requested.emit()

    def _on_record_toggled(self, checked: bool):
        self._recording = checked
        self._btn_record.setProperty("recording", "true" if checked else "false")
        self._btn_record.style().unpolish(self._btn_record)
        self._btn_record.style().polish(self._btn_record)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _update_buttons(self):
        self._btn_start.setEnabled(self._selected_pkg is not None)
        self._btn_stop.setEnabled(False)

    def _update_layout_direction(self):
        direction = Qt.RightToLeft if i18n.is_rtl() else Qt.LeftToRight
        self.setLayoutDirection(direction)
