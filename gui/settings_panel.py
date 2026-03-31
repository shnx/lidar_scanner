"""
SettingsPanel — User-configurable application settings.
"""

from pathlib import Path
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QCheckBox, QComboBox, QPushButton, QGroupBox,
    QFileDialog, QSpacerItem, QSizePolicy, QFormLayout
)
from PyQt5.QtCore import pyqtSignal, Qt

from . import i18n


class SettingsPanel(QWidget):

    settings_changed = pyqtSignal(dict)

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(16)

        # ── Recording settings ───────────────────────────────────────
        rec_group = QGroupBox()
        rec_layout = QFormLayout(rec_group)
        rec_layout.setSpacing(10)

        self._rec_dir_edit = QLineEdit(
            str(Path(self._settings.get("app", {}).get("recordings_dir", "~/slam_sessions")).expanduser())
        )
        dir_row = QHBoxLayout()
        dir_row.addWidget(self._rec_dir_edit)
        btn_browse = QPushButton("…")
        btn_browse.setFixedWidth(32)
        btn_browse.clicked.connect(self._browse_dir)
        dir_row.addWidget(btn_browse)

        self._chk_auto_record = QCheckBox()
        self._chk_auto_record.setChecked(self._settings.get("app", {}).get("auto_record", True))

        self._lbl_rec_dir = QLabel()
        self._lbl_auto_record = QLabel()
        rec_layout.addRow(self._lbl_rec_dir, dir_row)
        rec_layout.addRow(self._lbl_auto_record, self._chk_auto_record)

        # ── System settings ──────────────────────────────────────────
        sys_group = QGroupBox()
        sys_layout = QFormLayout(sys_group)
        sys_layout.setSpacing(10)

        self._chk_auto_recover = QCheckBox()
        self._chk_auto_recover.setChecked(self._settings.get("app", {}).get("auto_recover", True))

        self._combo_lang = QComboBox()
        self._combo_lang.addItem("English", "en")
        self._combo_lang.addItem("العربية", "ar")
        current_lang = i18n.current_language()
        idx = self._combo_lang.findData(current_lang)
        if idx >= 0:
            self._combo_lang.setCurrentIndex(idx)
        self._combo_lang.currentIndexChanged.connect(self._on_lang_changed)

        self._lbl_auto_recover = QLabel()
        self._lbl_language = QLabel()
        sys_layout.addRow(self._lbl_auto_recover, self._chk_auto_recover)
        sys_layout.addRow(self._lbl_language, self._combo_lang)

        # ── Save button ──────────────────────────────────────────────
        self._btn_save = QPushButton("Save Settings")
        self._btn_save.setObjectName("btnStart")
        self._btn_save.setFixedHeight(36)
        self._btn_save.clicked.connect(self._save)

        root.addWidget(rec_group)
        root.addWidget(sys_group)
        root.addWidget(self._btn_save)
        root.addItem(QSpacerItem(0, 0, QSizePolicy.Minimum, QSizePolicy.Expanding))

        self._rec_group = rec_group
        self._sys_group = sys_group
        self.retranslate()

    def retranslate(self):
        self._rec_group.setTitle(i18n.t("settings_recordings_dir").upper())
        self._sys_group.setTitle(i18n.t("settings_auto_recover").upper())
        self._lbl_rec_dir.setText(i18n.t("settings_recordings_dir"))
        self._lbl_auto_record.setText(i18n.t("settings_auto_record"))
        self._lbl_auto_recover.setText(i18n.t("settings_auto_recover"))
        self._lbl_language.setText(i18n.t("settings_language"))

    def _browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select recordings directory",
                                             self._rec_dir_edit.text())
        if d:
            self._rec_dir_edit.setText(d)

    def _on_lang_changed(self, index: int):
        lang = self._combo_lang.itemData(index)
        if lang:
            i18n.set_language(lang)
            parent = self.window()
            if hasattr(parent, "retranslate"):
                parent.retranslate()

    def _save(self):
        new_settings = {
            "app": {
                "recordings_dir": self._rec_dir_edit.text(),
                "auto_record": self._chk_auto_record.isChecked(),
                "auto_recover": self._chk_auto_recover.isChecked(),
            }
        }
        self.settings_changed.emit(new_settings)
