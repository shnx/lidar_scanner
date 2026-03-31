"""
ROSBridge — Subscribes to SLAM output topics and normalises them into
a common internal format that the GUI/visualiser can consume without
caring which package is running.

Uses rospy running inside a subprocess-spawned ROS environment so the
bridge is always pointing at the correct ROS_MASTER_URI for the active
session.
"""

import threading
import time
import logging
import struct
import numpy as np
from typing import Optional, Callable, List, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Common data containers
# ---------------------------------------------------------------------------

@dataclass
class NormalizedPointCloud:
    """Unified PointCloud2 → numpy representation."""
    points: np.ndarray          # (N, 3)  float32  XYZ
    colors: Optional[np.ndarray] = None   # (N, 3) float32 RGB 0-1
    intensities: Optional[np.ndarray] = None  # (N,) float32
    stamp: float = 0.0
    frame_id: str = ""


@dataclass
class NormalizedPose:
    """Unified Odometry / PoseStamped → position + quaternion."""
    position: np.ndarray = field(default_factory=lambda: np.zeros(3))
    orientation: np.ndarray = field(default_factory=lambda: np.array([0, 0, 0, 1]))  # xyzw
    stamp: float = 0.0
    frame_id: str = ""


@dataclass
class NormalizedImage:
    """Unified sensor_msgs/Image → numpy HxWx3 uint8."""
    data: np.ndarray = field(default_factory=lambda: np.zeros((1, 1, 3), dtype=np.uint8))
    stamp: float = 0.0
    encoding: str = "rgb8"


# ---------------------------------------------------------------------------
# ROSBridge
# ---------------------------------------------------------------------------

class ROSBridge:
    """
    Manages rospy subscriptions for the active SLAM session.

    All callbacks are thread-safe and posted to registered listeners via
    the on_* callable slots.

    Usage:
        bridge = ROSBridge()
        bridge.on_pointcloud = lambda pc: ...
        bridge.on_pose = lambda p: ...
        bridge.on_image = lambda img: ...
        bridge.connect(ros_master_uri, pkg_config)
        ...
        bridge.disconnect()
    """

    def __init__(self):
        self._connected = False
        self._lock = threading.Lock()
        self._ros_thread: Optional[threading.Thread] = None

        self.on_pointcloud: Optional[Callable[[NormalizedPointCloud], None]] = None
        self.on_pose: Optional[Callable[[NormalizedPose], None]] = None
        self.on_image: Optional[Callable[[NormalizedImage], None]] = None
        self.on_log: Optional[Callable] = None

        self._fps_counter = FPSCounter()
        self.fps: float = 0.0

        self._subs = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def connect(self, ros_master_uri: str, pkg_config: dict) -> None:
        """Start rospy node and subscribe to topics defined in pkg_config."""
        self.disconnect()
        self._ros_thread = threading.Thread(
            target=self._ros_spin,
            args=(ros_master_uri, pkg_config),
            daemon=True
        )
        self._ros_thread.start()

    def disconnect(self) -> None:
        """Unsubscribe and shut down rospy node."""
        with self._lock:
            if not self._connected:
                return
        self._shutdown_rospy()

    def is_connected(self) -> bool:
        with self._lock:
            return self._connected

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _ros_spin(self, ros_master_uri: str, pkg_config: dict) -> None:
        import os
        os.environ["ROS_MASTER_URI"] = ros_master_uri
        os.environ["ROS_IP"] = "127.0.0.1"

        try:
            import rospy
            import sensor_msgs.msg as sensor_msgs
            import nav_msgs.msg as nav_msgs
            import geometry_msgs.msg as geometry_msgs
        except ImportError as exc:
            self._log("error", f"rospy import failed: {exc}. Is ROS Melodic sourced?")
            return

        try:
            rospy.init_node("slam_launcher_bridge", anonymous=True, disable_signals=True)
        except rospy.ROSException as exc:
            self._log("error", f"rospy.init_node failed: {exc}")
            return

        outputs = pkg_config.get("outputs", {})

        subs = []
        if "pointcloud" in outputs:
            subs.append(rospy.Subscriber(
                outputs["pointcloud"],
                sensor_msgs.PointCloud2,
                self._cb_pointcloud,
                queue_size=2
            ))

        if "odometry" in outputs:
            subs.append(rospy.Subscriber(
                outputs["odometry"],
                nav_msgs.Odometry,
                self._cb_odometry,
                queue_size=10
            ))
        elif "pose" in outputs:
            subs.append(rospy.Subscriber(
                outputs["pose"],
                geometry_msgs.PoseStamped,
                self._cb_pose_stamped,
                queue_size=10
            ))

        if "image" in outputs:
            subs.append(rospy.Subscriber(
                outputs["image"],
                sensor_msgs.Image,
                self._cb_image,
                queue_size=2
            ))

        self._subs = subs
        with self._lock:
            self._connected = True
        self._log("info", f"ROSBridge connected ({len(subs)} subscriptions)")

        try:
            rospy.spin()
        except Exception:
            pass
        finally:
            with self._lock:
                self._connected = False

    def _shutdown_rospy(self) -> None:
        try:
            import rospy
            if not rospy.is_shutdown():
                rospy.signal_shutdown("slam_launcher disconnect")
        except Exception:
            pass
        with self._lock:
            self._connected = False

    # ------------------------------------------------------------------
    # ROS Callbacks
    # ------------------------------------------------------------------

    def _cb_pointcloud(self, msg) -> None:
        try:
            pc = _decode_pointcloud2(msg)
            self.fps = self._fps_counter.tick()
            if self.on_pointcloud:
                self.on_pointcloud(pc)
        except Exception as exc:
            self._log("warning", f"PointCloud decode error: {exc}")

    def _cb_odometry(self, msg) -> None:
        try:
            p = msg.pose.pose.position
            o = msg.pose.pose.orientation
            pose = NormalizedPose(
                position=np.array([p.x, p.y, p.z], dtype=np.float64),
                orientation=np.array([o.x, o.y, o.z, o.w], dtype=np.float64),
                stamp=msg.header.stamp.to_sec(),
                frame_id=msg.header.frame_id
            )
            if self.on_pose:
                self.on_pose(pose)
        except Exception as exc:
            self._log("warning", f"Odometry decode error: {exc}")

    def _cb_pose_stamped(self, msg) -> None:
        try:
            p = msg.pose.position
            o = msg.pose.orientation
            pose = NormalizedPose(
                position=np.array([p.x, p.y, p.z], dtype=np.float64),
                orientation=np.array([o.x, o.y, o.z, o.w], dtype=np.float64),
                stamp=msg.header.stamp.to_sec(),
                frame_id=msg.header.frame_id
            )
            if self.on_pose:
                self.on_pose(pose)
        except Exception as exc:
            self._log("warning", f"PoseStamped decode error: {exc}")

    def _cb_image(self, msg) -> None:
        try:
            img = _decode_image(msg)
            if self.on_image:
                self.on_image(img)
        except Exception as exc:
            self._log("warning", f"Image decode error: {exc}")

    def _log(self, level: str, msg: str) -> None:
        getattr(logger, level, logger.info)(msg)
        if self.on_log:
            self.on_log(level, msg)


# ---------------------------------------------------------------------------
# Decoders
# ---------------------------------------------------------------------------

def _decode_pointcloud2(msg) -> NormalizedPointCloud:
    """Convert sensor_msgs/PointCloud2 to NormalizedPointCloud."""
    import sensor_msgs.point_cloud2 as pc2_util

    fields = {f.name: f for f in msg.fields}
    has_rgb = "rgb" in fields or "rgba" in fields
    has_intensity = "intensity" in fields

    gen = list(pc2_util.read_points(msg, skip_nans=True))
    if not gen:
        return NormalizedPointCloud(
            points=np.zeros((0, 3), dtype=np.float32),
            stamp=msg.header.stamp.to_sec(),
            frame_id=msg.header.frame_id
        )

    arr = np.array(gen, dtype=np.float32)
    xyz = arr[:, :3]

    colors = None
    if has_rgb:
        rgb_raw = arr[:, 3].view(np.uint32)
        r = ((rgb_raw >> 16) & 0xFF).astype(np.float32) / 255.0
        g = ((rgb_raw >> 8) & 0xFF).astype(np.float32) / 255.0
        b = (rgb_raw & 0xFF).astype(np.float32) / 255.0
        colors = np.stack([r, g, b], axis=1)

    intensities = None
    if has_intensity:
        idx = list(fields.keys()).index("intensity")
        intensities = arr[:, idx]

    return NormalizedPointCloud(
        points=xyz,
        colors=colors,
        intensities=intensities,
        stamp=msg.header.stamp.to_sec(),
        frame_id=msg.header.frame_id
    )


def _decode_image(msg) -> NormalizedImage:
    """Convert sensor_msgs/Image to NormalizedImage."""
    encoding = msg.encoding
    width, height = msg.width, msg.height
    raw = np.frombuffer(msg.data, dtype=np.uint8)

    if encoding in ("rgb8", "bgr8", "mono8"):
        channels = 1 if encoding == "mono8" else 3
        img = raw.reshape((height, width, channels))
        if encoding == "bgr8":
            img = img[:, :, ::-1]
        elif encoding == "mono8":
            img = np.stack([img[:, :, 0]] * 3, axis=2)
    else:
        img = raw.reshape((height, width, -1))[:, :, :3]

    return NormalizedImage(
        data=img.astype(np.uint8),
        stamp=msg.header.stamp.to_sec(),
        encoding="rgb8"
    )


# ---------------------------------------------------------------------------
# FPS Counter
# ---------------------------------------------------------------------------

class FPSCounter:
    def __init__(self, window: int = 30):
        self._times: List[float] = []
        self._window = window

    def tick(self) -> float:
        now = time.monotonic()
        self._times.append(now)
        cutoff = now - 2.0
        self._times = [t for t in self._times if t > cutoff]
        if len(self._times) < 2:
            return 0.0
        span = self._times[-1] - self._times[0]
        return (len(self._times) - 1) / span if span > 0 else 0.0
