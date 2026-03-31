"""
SessionRecorder — Saves all session artefacts into a structured folder:

  ~/slam_sessions/<pkg_id>_<YYYYMMDD_HHMMSS>/
      recording.bag
      trajectory.txt
      pointcloud.pcd
      config.yaml
"""

import os
import shutil
import time
import logging
import threading
import numpy as np
import yaml
from pathlib import Path
from datetime import datetime
from typing import Optional, List

from .ros_bridge import NormalizedPointCloud, NormalizedPose

logger = logging.getLogger(__name__)


class SessionRecorder:
    """
    Accumulates pose and point-cloud data during a SLAM run and
    persists them to disk when stop() is called (or on demand).
    """

    def __init__(self, settings: dict):
        self._settings = settings
        self._base_dir = Path(
            settings.get("app", {}).get("recordings_dir", "~/slam_sessions")
        ).expanduser()
        self._session_dir: Optional[Path] = None
        self._pkg_id: Optional[str] = None
        self._pkg_config: dict = {}

        self._poses: List[NormalizedPose] = []
        self._point_clouds: List[NormalizedPointCloud] = []
        self._lock = threading.Lock()
        self.on_log: Optional[callable] = None

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def begin_session(self, pkg_id: str, pkg_config: dict) -> Path:
        """Create the session directory and return its path."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._session_dir = self._base_dir / f"{pkg_id}_{ts}"
        self._session_dir.mkdir(parents=True, exist_ok=True)
        self._pkg_id = pkg_id
        self._pkg_config = pkg_config

        with self._lock:
            self._poses.clear()
            self._point_clouds.clear()

        self._save_config()
        self._log("info", f"Session directory: {self._session_dir}")
        return self._session_dir

    def end_session(self) -> Optional[Path]:
        """Flush all accumulated data to disk. Returns session dir."""
        if not self._session_dir:
            return None
        self._flush_trajectory()
        self._flush_pointcloud()
        self._log("info", f"Session saved → {self._session_dir}")
        return self._session_dir

    def session_dir(self) -> Optional[Path]:
        return self._session_dir

    # ------------------------------------------------------------------
    # Data ingestion (called from ROS callbacks)
    # ------------------------------------------------------------------

    def add_pose(self, pose: NormalizedPose) -> None:
        with self._lock:
            self._poses.append(pose)

    def add_pointcloud(self, pc: NormalizedPointCloud) -> None:
        """Keep only the latest point cloud (memory guard)."""
        with self._lock:
            self._point_clouds.clear()
            self._point_clouds.append(pc)

    # ------------------------------------------------------------------
    # Disk persistence
    # ------------------------------------------------------------------

    def _save_config(self) -> None:
        cfg_path = self._session_dir / "config.yaml"
        data = {
            "package": self._pkg_id,
            "started_at": datetime.now().isoformat(),
            "package_config": self._pkg_config,
            "settings": self._settings,
        }
        with open(cfg_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

    def _flush_trajectory(self) -> None:
        with self._lock:
            poses = list(self._poses)

        if not poses:
            return

        traj_path = self._session_dir / "trajectory.txt"
        fmt = self._settings.get("recording", {}).get("trajectory_format", "tum")

        with open(traj_path, "w") as f:
            if fmt == "tum":
                f.write("# timestamp tx ty tz qx qy qz qw\n")
                for p in poses:
                    f.write(
                        f"{p.stamp:.6f} "
                        f"{p.position[0]:.6f} {p.position[1]:.6f} {p.position[2]:.6f} "
                        f"{p.orientation[0]:.6f} {p.orientation[1]:.6f} "
                        f"{p.orientation[2]:.6f} {p.orientation[3]:.6f}\n"
                    )
            else:
                f.write("# tx ty tz qx qy qz qw\n")
                for p in poses:
                    f.write(
                        f"{p.position[0]:.6f} {p.position[1]:.6f} {p.position[2]:.6f} "
                        f"{p.orientation[0]:.6f} {p.orientation[1]:.6f} "
                        f"{p.orientation[2]:.6f} {p.orientation[3]:.6f}\n"
                    )

        self._log("info", f"Trajectory saved: {len(poses)} poses → {traj_path}")

    def _flush_pointcloud(self) -> None:
        with self._lock:
            clouds = list(self._point_clouds)

        if not clouds:
            return

        pc = clouds[-1]
        pcd_path = self._session_dir / "pointcloud.pcd"
        binary = self._settings.get("recording", {}).get("pcd_binary", True)

        try:
            _write_pcd(pc, pcd_path, binary=binary)
            self._log("info", f"Point cloud saved: {len(pc.points)} pts → {pcd_path}")
        except Exception as exc:
            self._log("error", f"Failed to save point cloud: {exc}")

    def _log(self, level: str, msg: str) -> None:
        getattr(logger, level, logger.info)(msg)
        if self.on_log:
            self.on_log(level, msg)


# ---------------------------------------------------------------------------
# PCD writer (no open3d dependency for the recorder — pure numpy)
# ---------------------------------------------------------------------------

def _write_pcd(pc: NormalizedPointCloud, path: Path, binary: bool = True) -> None:
    points = pc.points
    N = len(points)
    has_color = pc.colors is not None

    if has_color:
        fields = "x y z rgb"
        sizes = "4 4 4 4"
        types = "F F F F"
        counts = "1 1 1 1"
        width_fields = 4
    else:
        fields = "x y z"
        sizes = "4 4 4"
        types = "F F F"
        counts = "1 1 1"
        width_fields = 3

    header_lines = [
        "# .PCD v0.7 - Point Cloud Data file",
        f"VERSION 0.7",
        f"FIELDS {fields}",
        f"SIZE {sizes}",
        f"TYPE {types}",
        f"COUNT {counts}",
        f"WIDTH {N}",
        f"HEIGHT 1",
        "VIEWPOINT 0 0 0 1 0 0 0",
        f"POINTS {N}",
        "DATA " + ("binary" if binary else "ascii"),
    ]
    header = "\n".join(header_lines) + "\n"

    with open(path, "wb") as f:
        f.write(header.encode("ascii"))
        if binary:
            if has_color:
                rgb = pc.colors * 255.0
                rgb_packed = (
                    rgb[:, 0].astype(np.uint32) << 16
                    | rgb[:, 1].astype(np.uint32) << 8
                    | rgb[:, 2].astype(np.uint32)
                ).view(np.float32)
                data = np.column_stack([points.astype(np.float32), rgb_packed])
            else:
                data = points.astype(np.float32)
            f.write(data.tobytes())
        else:
            for i in range(N):
                row = f"{points[i,0]:.6f} {points[i,1]:.6f} {points[i,2]:.6f}"
                if has_color:
                    r = int(pc.colors[i, 0] * 255)
                    g = int(pc.colors[i, 1] * 255)
                    b = int(pc.colors[i, 2] * 255)
                    rgb_int = (r << 16) | (g << 8) | b
                    row += f" {rgb_int}"
                f.write((row + "\n").encode("ascii"))
