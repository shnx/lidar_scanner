"""
VizWidget — Embedded 3-D visualiser using Open3D running in a
dedicated background thread.  The PyQt5 widget shows either:
  • A live Open3D window (external, managed by this module)
  • A camera image feed rendered into a QLabel fallback

Open3D does not embed natively into Qt on Linux, so we manage an
Open3D Visualizer in a separate thread and render the latest frame
into a QImage that we blit into a QLabel at ~30 FPS.
"""

import threading
import time
import logging
import numpy as np
from typing import Optional, List

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QHBoxLayout,
    QPushButton, QSizePolicy, QFrame
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, pyqtSlot, QSize
from PyQt5.QtGui import QImage, QPixmap, QFont

from core.ros_bridge import NormalizedPointCloud, NormalizedPose, NormalizedImage

logger = logging.getLogger(__name__)

try:
    import open3d as o3d
    _O3D_AVAILABLE = True
except ImportError:
    _O3D_AVAILABLE = False
    logger.warning("open3d not installed — 3D visualization will be limited")


class TrajectoryBuffer:
    """Thread-safe accumulator for camera pose history."""

    def __init__(self, max_poses: int = 5000):
        self._poses: List[np.ndarray] = []
        self._max = max_poses
        self._lock = threading.Lock()

    def add(self, pos: np.ndarray):
        with self._lock:
            self._poses.append(pos.copy())
            if len(self._poses) > self._max:
                self._poses = self._poses[-self._max:]

    def get_line_set(self):
        """Return an o3d.geometry.LineSet of the trajectory, or None."""
        if not _O3D_AVAILABLE:
            return None
        with self._lock:
            pts = list(self._poses)
        if len(pts) < 2:
            return None
        points = np.array(pts, dtype=np.float64)
        lines = [[i, i + 1] for i in range(len(points) - 1)]
        colors = [[0.0, 1.0, 0.4]] * len(lines)
        ls = o3d.geometry.LineSet()
        ls.points = o3d.utility.Vector3dVector(points)
        ls.lines = o3d.utility.Vector2iVector(lines)
        ls.colors = o3d.utility.Vector3dVector(colors)
        return ls

    def clear(self):
        with self._lock:
            self._poses.clear()


class Open3DThread(threading.Thread):
    """
    Manages an Open3D Visualizer in a dedicated thread.
    Receives geometry updates via thread-safe queues and renders
    frames to a numpy array that the Qt widget can display.
    """

    def __init__(self, width: int = 800, height: int = 600,
                 bg_color=(0.05, 0.05, 0.08)):
        super().__init__(daemon=True, name="Open3DThread")
        self._width = width
        self._height = height
        self._bg_color = bg_color
        self._lock = threading.Lock()

        self._pending_pcd: Optional[NormalizedPointCloud] = None
        self._pending_trajectory = None
        self._pcd_dirty = False
        self._traj_dirty = False

        self._frame: Optional[np.ndarray] = None  # HxWx3 uint8
        self._frame_lock = threading.Lock()

        self._running = False
        self._vis = None

        self.point_size: float = 2.0
        self.max_points: int = 3_000_000

    # ------------------------------------------------------------------
    # Data ingestion (called from ROS thread)
    # ------------------------------------------------------------------

    def update_pointcloud(self, pc: NormalizedPointCloud):
        with self._lock:
            self._pending_pcd = pc
            self._pcd_dirty = True

    def update_trajectory(self, lineset):
        with self._lock:
            self._pending_trajectory = lineset
            self._traj_dirty = True

    def get_frame(self) -> Optional[np.ndarray]:
        with self._frame_lock:
            return self._frame.copy() if self._frame is not None else None

    def stop(self):
        self._running = False

    # ------------------------------------------------------------------
    # Thread body
    # ------------------------------------------------------------------

    def run(self):
        if not _O3D_AVAILABLE:
            return

        self._running = True
        vis = o3d.visualization.Visualizer()
        vis.create_window(
            window_name="SLAM Viewer",
            width=self._width,
            height=self._height,
            visible=False
        )
        opt = vis.get_render_option()
        opt.background_color = np.array(self._bg_color)
        opt.point_size = self.point_size
        opt.show_coordinate_frame = True
        self._vis = vis

        pcd_geom = o3d.geometry.PointCloud()
        traj_geom = o3d.geometry.LineSet()
        vis.add_geometry(pcd_geom)
        vis.add_geometry(traj_geom)

        while self._running:
            with self._lock:
                pcd_upd = self._pcd_dirty
                traj_upd = self._traj_dirty
                pending_pcd = self._pending_pcd
                pending_traj = self._pending_trajectory
                self._pcd_dirty = False
                self._traj_dirty = False

            if pcd_upd and pending_pcd is not None:
                self._apply_pointcloud(pcd_geom, pending_pcd, vis)

            if traj_upd and pending_traj is not None:
                traj_geom.points = pending_traj.points
                traj_geom.lines = pending_traj.lines
                traj_geom.colors = pending_traj.colors
                vis.update_geometry(traj_geom)

            vis.poll_events()
            vis.update_renderer()

            img = vis.capture_screen_float_buffer(do_render=False)
            if img:
                arr = (np.asarray(img) * 255).astype(np.uint8)
                with self._frame_lock:
                    self._frame = arr

            time.sleep(0.033)

        vis.destroy_window()

    def _apply_pointcloud(self, geom, pc: NormalizedPointCloud, vis):
        pts = pc.points
        if len(pts) > self.max_points:
            idx = np.random.choice(len(pts), self.max_points, replace=False)
            pts = pts[idx]
            colors = pc.colors[idx] if pc.colors is not None else None
        else:
            colors = pc.colors

        geom.points = o3d.utility.Vector3dVector(pts.astype(np.float64))
        if colors is not None:
            geom.colors = o3d.utility.Vector3dVector(colors.astype(np.float64))
        elif pc.intensities is not None:
            norm = pc.intensities / (pc.intensities.max() + 1e-6)
            cmap = _intensity_to_rgb(norm)
            geom.colors = o3d.utility.Vector3dVector(cmap)
        else:
            geom.paint_uniform_color([0.5, 0.8, 1.0])

        vis.update_geometry(geom)
        vis.reset_view_point(True)


def _intensity_to_rgb(intensities: np.ndarray) -> np.ndarray:
    """Map [0,1] intensity to a jet-like colormap."""
    r = np.clip(1.5 - np.abs(4 * intensities - 3), 0, 1)
    g = np.clip(1.5 - np.abs(4 * intensities - 2), 0, 1)
    b = np.clip(1.5 - np.abs(4 * intensities - 1), 0, 1)
    return np.stack([r, g, b], axis=1).astype(np.float64)


class VizWidget(QWidget):
    """
    PyQt5 widget that embeds the Open3D rendered frame + camera image.

    Layout:
      ┌──────────────────────────────┬───────────┐
      │   3-D viewer (Open3D frame)  │  Camera   │
      │                              │   Feed    │
      └──────────────────────────────┴───────────┘
    """

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._o3d_thread: Optional[Open3DThread] = None
        self._trajectory = TrajectoryBuffer()
        self._last_frame: Optional[np.ndarray] = None

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._build_ui()

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_frame)
        self._refresh_timer.start(settings.get("visualization", {}).get("update_interval_ms", 100))

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        # ── 3-D panel ────────────────────────────────────────────────
        self._viz_frame = QFrame()
        self._viz_frame.setObjectName("vizContainer")
        self._viz_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        vl = QVBoxLayout(self._viz_frame)
        vl.setContentsMargins(0, 0, 0, 0)

        self._viz_label = QLabel()
        self._viz_label.setAlignment(Qt.AlignCenter)
        self._viz_label.setObjectName("vizPlaceholder")
        self._viz_label.setText("3D Map will appear here\nwhen a SLAM session is running")
        self._viz_label.setWordWrap(True)
        vl.addWidget(self._viz_label)

        # ── camera feed ──────────────────────────────────────────────
        self._cam_frame = QFrame()
        self._cam_frame.setObjectName("vizContainer")
        self._cam_frame.setMinimumWidth(180)
        self._cam_frame.setMaximumWidth(400)
        self._cam_frame.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        cl = QVBoxLayout(self._cam_frame)
        cl.setContentsMargins(4, 4, 4, 4)
        cl.setSpacing(4)

        cam_title = QLabel("Camera Feed")
        cam_title.setAlignment(Qt.AlignCenter)
        cam_title.setStyleSheet("font-size: 11px; color: #8b949e;")
        cl.addWidget(cam_title)

        self._cam_label = QLabel()
        self._cam_label.setAlignment(Qt.AlignCenter)
        self._cam_label.setStyleSheet("color: #30363d; font-size: 12px;")
        self._cam_label.setText("No image")
        self._cam_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        cl.addWidget(self._cam_label, 1)

        root.addWidget(self._viz_frame, 3)
        root.addWidget(self._cam_frame, 1)

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def start_session(self, pkg_config: dict):
        """Start the Open3D render thread for the new session."""
        self.stop_session()
        self._trajectory.clear()

        vis_cfg = self._settings.get("visualization", {})
        bg = vis_cfg.get("background_color", [0.05, 0.05, 0.08])
        pt_size = vis_cfg.get("point_size", 2.0)
        max_pts = vis_cfg.get("max_points_display", 3_000_000)

        if _O3D_AVAILABLE:
            w = self._viz_label.width() or 800
            h = self._viz_label.height() or 600
            self._o3d_thread = Open3DThread(width=w, height=h, bg_color=tuple(bg))
            self._o3d_thread.point_size = pt_size
            self._o3d_thread.max_points = max_pts
            self._o3d_thread.start()
            self._viz_label.setText("")
        else:
            self._viz_label.setText("open3d not installed\n3D view unavailable")

    def stop_session(self):
        if self._o3d_thread and self._o3d_thread.is_alive():
            self._o3d_thread.stop()
            self._o3d_thread.join(timeout=3)
        self._o3d_thread = None
        self._viz_label.setText("3D Map will appear here\nwhen a SLAM session is running")
        self._cam_label.setText("No image")

    # ------------------------------------------------------------------
    # Data ingest (called from ROS bridge callbacks via Qt signals)
    # ------------------------------------------------------------------

    @pyqtSlot(object)
    def on_pointcloud(self, pc: NormalizedPointCloud):
        if self._o3d_thread:
            self._o3d_thread.update_pointcloud(pc)

    @pyqtSlot(object)
    def on_pose(self, pose: NormalizedPose):
        self._trajectory.add(pose.position)
        ls = self._trajectory.get_line_set()
        if ls and self._o3d_thread:
            self._o3d_thread.update_trajectory(ls)

    @pyqtSlot(object)
    def on_image(self, img: NormalizedImage):
        h, w, ch = img.data.shape
        q_img = QImage(img.data.tobytes(), w, h, w * ch, QImage.Format_RGB888)
        pix = QPixmap.fromImage(q_img).scaled(
            self._cam_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        self._cam_label.setPixmap(pix)

    # ------------------------------------------------------------------
    # Frame refresh
    # ------------------------------------------------------------------

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._last_frame is not None:
            self._blit_frame(self._last_frame)

    def _blit_frame(self, frame: np.ndarray):
        h, w, _ = frame.shape
        q_img = QImage(frame.tobytes(), w, h, w * 3, QImage.Format_RGB888)
        pix = QPixmap.fromImage(q_img).scaled(
            self._viz_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        self._viz_label.setPixmap(pix)

    def _refresh_frame(self):
        if self._o3d_thread is None:
            return
        frame = self._o3d_thread.get_frame()
        if frame is None:
            return
        self._last_frame = frame
        self._blit_frame(frame)
