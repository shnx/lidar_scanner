"""
MainWindow — Top-level PyQt5 application window.

Orchestrates:
  • LauncherPanel  (package selection + Start/Stop)
  • VizWidget      (Open3D 3-D view + camera feed)
  • StatusPanel    (metrics bar + logs)
  • Settings tab
  • Language toggle (AR ↔ EN with full RTL layout switch)
"""

import logging
import threading
from pathlib import Path
from typing import Optional

import yaml
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTabWidget, QSplitter,
    QMessageBox, QStatusBar, QFileDialog, QApplication
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, pyqtSlot, QObject, QTimer
from PyQt5.QtGui import QIcon, QFont, QFontDatabase

from . import i18n
from .launcher_panel import LauncherPanel
from .status_panel import StatusPanel
from .viz_widget import VizWidget
from .settings_panel import SettingsPanel
from core.process_manager import ProcessManager
from core.ros_bridge import ROSBridge, NormalizedPointCloud, NormalizedPose, NormalizedImage
from core.recorder import SessionRecorder
from core.watchdog import NodeWatchdog

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Qt signal bridge — routes thread-unsafe callbacks into the Qt event loop
# ---------------------------------------------------------------------------

class SignalBridge(QObject):
    log_signal = pyqtSignal(str, str)                   # level, message
    status_signal = pyqtSignal(str, str)                # pkg_id, status
    output_signal = pyqtSignal(str, str)                # pkg_id, line
    pointcloud_signal = pyqtSignal(object)
    pose_signal = pyqtSignal(object)
    image_signal = pyqtSignal(object)
    fps_signal = pyqtSignal(float)
    points_signal = pyqtSignal(int)
    recovery_signal = pyqtSignal(str, str)              # pkg_id, kind


class MainWindow(QMainWindow):

    def __init__(self, config: dict):
        super().__init__()
        self._config = config
        self._packages = config["packages"]
        self._settings = config["settings"]
        self._current_pkg: Optional[str] = None

        self._bridge = SignalBridge()
        self._process_manager = ProcessManager(self._settings, self._packages)
        self._ros_bridge = ROSBridge()
        self._recorder = SessionRecorder(self._settings)
        self._watchdog = NodeWatchdog(self._settings)

        self._connect_core_signals()

        self._build_ui()
        self._connect_ui_signals()

        self._watchdog.attach(self._process_manager)

        self.setWindowTitle(i18n.t("app_title"))
        self.resize(1400, 860)
        self.setMinimumSize(1100, 700)
        self._load_icon()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        central = QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(12, 12, 12, 12)
        body_layout.setSpacing(8)

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(False)

        # Tab 0: Packages + Visualization
        self._tab_main = QWidget()
        self._build_main_tab()
        self._tabs.addTab(self._tab_main, "")

        # Tab 1: Logs
        self._tab_logs = QWidget()
        logs_layout = QVBoxLayout(self._tab_logs)
        logs_layout.setContentsMargins(8, 8, 8, 8)
        self._status_panel_full = StatusPanel()
        logs_layout.addWidget(self._status_panel_full)
        self._tabs.addTab(self._tab_logs, "")

        # Tab 2: Settings
        self._tab_settings = QWidget()
        settings_layout = QVBoxLayout(self._tab_settings)
        settings_layout.setContentsMargins(8, 8, 8, 8)
        self._settings_panel = SettingsPanel(self._settings)
        self._settings_panel.settings_changed.connect(self._on_settings_changed)
        settings_layout.addWidget(self._settings_panel)
        self._tabs.addTab(self._tab_settings, "")

        body_layout.addWidget(self._tabs, 1)
        root.addWidget(body, 1)

        self._build_statusbar()
        self.retranslate()

    def _build_header(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("headerBar")
        bar.setFixedHeight(60)
        hl = QHBoxLayout(bar)
        hl.setContentsMargins(16, 0, 16, 0)
        hl.setSpacing(12)

        titles = QVBoxLayout()
        titles.setSpacing(0)
        self._lbl_title = QLabel()
        self._lbl_title.setObjectName("appTitle")
        self._lbl_subtitle = QLabel()
        self._lbl_subtitle.setObjectName("appSubtitle")
        titles.addWidget(self._lbl_title)
        titles.addWidget(self._lbl_subtitle)

        hl.addLayout(titles)
        hl.addStretch()

        self._btn_lang = QPushButton()
        self._btn_lang.setObjectName("btnLang")
        self._btn_lang.setFixedSize(80, 30)
        self._btn_lang.clicked.connect(self._toggle_language)
        hl.addWidget(self._btn_lang)

        return bar

    def _build_main_tab(self):
        layout = QHBoxLayout(self._tab_main)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # ── left panel: launcher + mini-logs ────────────────────────
        left_splitter = QSplitter(Qt.Vertical)

        self._launcher_panel = LauncherPanel(self._packages)
        left_splitter.addWidget(self._launcher_panel)

        self._status_panel_mini = StatusPanel()
        self._status_panel_mini.setMaximumHeight(220)
        left_splitter.addWidget(self._status_panel_mini)
        left_splitter.setSizes([520, 200])

        left_wrapper = QWidget()
        lw_layout = QVBoxLayout(left_wrapper)
        lw_layout.setContentsMargins(0, 0, 0, 0)
        lw_layout.addWidget(left_splitter)
        left_wrapper.setFixedWidth(440)

        # ── right panel: visualization ───────────────────────────────
        self._viz_widget = VizWidget(self._settings)

        layout.addWidget(left_wrapper)
        layout.addWidget(self._viz_widget, 1)

    def _build_statusbar(self):
        sb = QStatusBar()
        self.setStatusBar(sb)

        self._sb_pkg = QLabel()
        self._sb_status = QLabel()
        self._sb_session = QLabel()
        self._sb_ros = QLabel("ROS: —")

        for lbl in (self._sb_pkg, self._sb_status, self._sb_session, self._sb_ros):
            lbl.setStyleSheet("padding: 0 8px;")
            sb.addPermanentWidget(lbl)

    def _load_icon(self):
        icon_path = Path(__file__).parent.parent / "assets" / "icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

    # ------------------------------------------------------------------
    # Signal wiring
    # ------------------------------------------------------------------

    def _connect_core_signals(self):
        # ProcessManager → SignalBridge
        self._process_manager.on_log = lambda lvl, msg: self._bridge.log_signal.emit(lvl, msg)
        self._process_manager.on_status_change = lambda pid, st: self._bridge.status_signal.emit(pid, st)
        self._process_manager.on_output = lambda pid, line: self._bridge.output_signal.emit(pid, line)

        # ROSBridge → SignalBridge
        self._ros_bridge.on_log = lambda lvl, msg: self._bridge.log_signal.emit(lvl, msg)
        self._ros_bridge.on_pointcloud = self._on_ros_pointcloud_thread
        self._ros_bridge.on_pose = self._on_ros_pose_thread
        self._ros_bridge.on_image = self._on_ros_image_thread

        # Recorder
        self._recorder.on_log = lambda lvl, msg: self._bridge.log_signal.emit(lvl, msg)

        # Watchdog
        self._watchdog.on_log = lambda lvl, msg: self._bridge.log_signal.emit(lvl, msg)
        self._watchdog.on_crash_detected = lambda pid: self._bridge.recovery_signal.emit(pid, "crash")
        self._watchdog.on_recovery_success = lambda pid: self._bridge.recovery_signal.emit(pid, "recovered")
        self._watchdog.on_recovery_failed = lambda pid: self._bridge.recovery_signal.emit(pid, "failed")

    def _connect_ui_signals(self):
        self._bridge.log_signal.connect(self._on_log)
        self._bridge.status_signal.connect(self._on_status_change)
        self._bridge.output_signal.connect(self._on_process_output)
        self._bridge.pointcloud_signal.connect(self._viz_widget.on_pointcloud)
        self._bridge.pose_signal.connect(self._viz_widget.on_pose)
        self._bridge.image_signal.connect(self._viz_widget.on_image)
        self._bridge.fps_signal.connect(self._status_panel_mini.metrics.update_fps)
        self._bridge.fps_signal.connect(self._status_panel_full.metrics.update_fps)
        self._bridge.points_signal.connect(self._status_panel_mini.metrics.update_points)
        self._bridge.points_signal.connect(self._status_panel_full.metrics.update_points)
        self._bridge.recovery_signal.connect(self._on_recovery_event)

        self._launcher_panel.start_requested.connect(self._on_start_requested)
        self._launcher_panel.stop_requested.connect(self._on_stop_requested)

    # ------------------------------------------------------------------
    # ROS callbacks (non-Qt thread) → post to Qt thread via signals
    # ------------------------------------------------------------------

    def _on_ros_pointcloud_thread(self, pc: NormalizedPointCloud):
        self._recorder.add_pointcloud(pc)
        self._bridge.pointcloud_signal.emit(pc)
        self._bridge.points_signal.emit(len(pc.points))
        self._bridge.fps_signal.emit(self._ros_bridge.fps)

    def _on_ros_pose_thread(self, pose: NormalizedPose):
        self._recorder.add_pose(pose)
        self._bridge.pose_signal.emit(pose)

    def _on_ros_image_thread(self, img: NormalizedImage):
        self._bridge.image_signal.emit(img)

    # ------------------------------------------------------------------
    # Qt slots
    # ------------------------------------------------------------------

    @pyqtSlot(str, str)
    def _on_log(self, level: str, msg: str):
        self._status_panel_mini.append_log(level, msg)
        self._status_panel_full.append_log(level, msg)

    @pyqtSlot(str, str)
    def _on_status_change(self, pkg_id: str, status: str):
        self._launcher_panel.update_package_status(pkg_id, status)
        running = status in ("running", "starting")
        self._launcher_panel.set_running_state(running, pkg_id if running else None)

        self._sb_pkg.setText(f"Pkg: {pkg_id}")
        self._sb_status.setText(f"Status: {i18n.t(f'status_{status}', status=status)}")

        if status == "running":
            self._status_panel_mini.metrics.session_started()
            self._status_panel_full.metrics.session_started()
            self._status_panel_mini.metrics.update_tracking("initializing")
            self._status_panel_full.metrics.update_tracking("initializing")
        elif status in ("stopped", "crashed", "idle"):
            self._status_panel_mini.metrics.session_stopped()
            self._status_panel_full.metrics.session_stopped()

    @pyqtSlot(str, str)
    def _on_process_output(self, pkg_id: str, line: str):
        self._on_log("info", line)
        self._detect_tracking_state(line)

    def _detect_tracking_state(self, line: str):
        """Parse common SLAM log patterns to infer tracking state."""
        ll = line.lower()
        if any(k in ll for k in ("tracking lost", "lost tracking", "relocalizing")):
            for sp in (self._status_panel_mini, self._status_panel_full):
                sp.metrics.update_tracking("lost")
        elif any(k in ll for k in ("tracking ok", "successfully tracked", "keyframe")):
            for sp in (self._status_panel_mini, self._status_panel_full):
                sp.metrics.update_tracking("ok")
        elif any(k in ll for k in ("initializ", "system init")):
            for sp in (self._status_panel_mini, self._status_panel_full):
                sp.metrics.update_tracking("initializing")

    @pyqtSlot(str, str)
    def _on_recovery_event(self, pkg_id: str, kind: str):
        if kind == "crash":
            self._on_log("error", i18n.t("err_node_crashed", node=pkg_id))
        elif kind == "recovered":
            self._on_log("success", i18n.t("info_recovery_success", node=pkg_id))
        elif kind == "failed":
            QMessageBox.critical(
                self,
                "Recovery Failed",
                f"Auto-recovery failed for '{pkg_id}' after maximum attempts.\n"
                "Please check the logs and restart manually."
            )

    @pyqtSlot(str, bool)
    def _on_start_requested(self, pkg_id: str, record: bool):
        if self._process_manager.is_running():
            pkg_name = self._packages.get(pkg_id, {}).get(
                f"name_{i18n.current_language()}", pkg_id)
            reply = QMessageBox.question(
                self,
                i18n.t("confirm_switch_title"),
                i18n.t("confirm_switch_msg", package=pkg_name),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

        self._start_session(pkg_id, record)

    @pyqtSlot()
    def _on_stop_requested(self):
        if not self._process_manager.is_running():
            return
        reply = QMessageBox.question(
            self,
            i18n.t("confirm_stop_title"),
            i18n.t("confirm_stop_msg"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self._stop_session()

    @pyqtSlot(dict)
    def _on_settings_changed(self, new_settings: dict):
        self._settings.update(new_settings)

    # ------------------------------------------------------------------
    # Session orchestration
    # ------------------------------------------------------------------

    def _start_session(self, pkg_id: str, record: bool):
        pkg_cfg = self._packages.get(pkg_id)
        if not pkg_cfg:
            return

        self._on_log("info", f"Starting {pkg_cfg.get('name_en', pkg_id)} …")

        session_dir = None
        if record:
            session_dir = self._recorder.begin_session(pkg_id, pkg_cfg)
            self._sb_session.setText(f"Session: {session_dir.name}")
            self._on_log("info", i18n.t("info_recording_started"))

        self._viz_widget.start_session(pkg_cfg)
        self._watchdog.reset()

        def _launch():
            ok = self._process_manager.start(pkg_id, session_dir=session_dir, record=record)
            if ok:
                rosmaster_uri = f"http://localhost:{pkg_cfg['rosmaster_port']}"
                self._ros_bridge.connect(rosmaster_uri, pkg_cfg)

        thread = threading.Thread(target=_launch, daemon=True)
        thread.start()
        self._current_pkg = pkg_id

    def _stop_session(self):
        self._on_log("info", "Stopping session …")
        self._ros_bridge.disconnect()

        session_dir = self._recorder.end_session()
        if session_dir:
            self._on_log("success", i18n.t("info_session_saved", path=str(session_dir)))
            self._on_log("info", i18n.t("info_recording_stopped"))

        self._viz_widget.stop_session()

        def _stop():
            self._process_manager.stop()

        thread = threading.Thread(target=_stop, daemon=True)
        thread.start()

    # ------------------------------------------------------------------
    # Language toggle
    # ------------------------------------------------------------------

    def _toggle_language(self):
        new_lang = "ar" if i18n.current_language() == "en" else "en"
        i18n.set_language(new_lang)
        direction = Qt.RightToLeft if new_lang == "ar" else Qt.LeftToRight
        QApplication.instance().setLayoutDirection(direction)
        self.retranslate()

    def retranslate(self):
        self._lbl_title.setText(i18n.t("app_title"))
        self._lbl_subtitle.setText(i18n.t("app_subtitle"))
        self._btn_lang.setText(i18n.t("lang_toggle"))
        self._tabs.setTabText(0, i18n.t("tab_packages"))
        self._tabs.setTabText(1, i18n.t("tab_logs"))
        self._tabs.setTabText(2, i18n.t("tab_settings"))
        self.setWindowTitle(i18n.t("app_title"))

        self._launcher_panel.retranslate()
        self._status_panel_mini.retranslate()
        self._status_panel_full.retranslate()
        if hasattr(self, "_settings_panel"):
            self._settings_panel.retranslate()

    # ------------------------------------------------------------------
    # Close handler
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        if self._process_manager.is_running():
            reply = QMessageBox.question(
                self,
                i18n.t("confirm_stop_title"),
                i18n.t("confirm_stop_msg"),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                event.ignore()
                return

        self._ros_bridge.disconnect()
        self._recorder.end_session()
        self._viz_widget.stop_session()
        self._watchdog.stop()
        self._process_manager.stop()
        event.accept()
