"""
ProcessManager — Isolated ROS session lifecycle controller.

Each SLAM package runs under its own ROS_MASTER_URI (distinct port),
so topics and TF frames never collide between sessions.
"""

import os
import signal
import subprocess
import threading
import time
import logging
from pathlib import Path
from typing import Optional, Callable, Dict

logger = logging.getLogger(__name__)


class PackageSession:
    """Holds all subprocess handles for one running SLAM package."""

    def __init__(self, pkg_id: str, rosmaster_port: int):
        self.pkg_id = pkg_id
        self.rosmaster_port = rosmaster_port
        self.rosmaster_proc: Optional[subprocess.Popen] = None
        self.launch_proc: Optional[subprocess.Popen] = None
        self.rosbag_proc: Optional[subprocess.Popen] = None
        self.started_at: float = time.time()

    @property
    def ros_master_uri(self) -> str:
        return f"http://localhost:{self.rosmaster_port}"

    def is_alive(self) -> bool:
        if self.launch_proc is None:
            return False
        return self.launch_proc.poll() is None

    def all_pids(self):
        pids = []
        for p in (self.rosmaster_proc, self.launch_proc, self.rosbag_proc):
            if p and p.pid:
                pids.append(p.pid)
        return pids


class ProcessManager:
    """
    Manages exclusive execution of a single SLAM package at a time.

    Signals emitted (callbacks):
      on_log(level, message)
      on_status_change(pkg_id, status)   status ∈ {idle, starting, running, stopping, crashed, stopped}
      on_output(pkg_id, line)
    """

    STATUS_IDLE = "idle"
    STATUS_STARTING = "starting"
    STATUS_RUNNING = "running"
    STATUS_STOPPING = "stopping"
    STATUS_CRASHED = "crashed"
    STATUS_STOPPED = "stopped"

    def __init__(self, settings: dict, packages: dict):
        self._settings = settings
        self._packages = packages
        self._session: Optional[PackageSession] = None
        self._lock = threading.Lock()

        self.on_log: Optional[Callable] = None
        self.on_status_change: Optional[Callable] = None
        self.on_output: Optional[Callable] = None

        self._output_threads: list = []
        self._current_status: str = self.STATUS_IDLE

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self, pkg_id: str, session_dir: Optional[Path] = None,
              record: bool = False) -> bool:
        """
        Stop any running session, then launch pkg_id in isolation.
        Returns True on success.
        """
        with self._lock:
            if self._session and self._session.is_alive():
                self._log("info", f"Stopping previous session '{self._session.pkg_id}' …")
                self._stop_session(self._session)

            pkg = self._packages.get(pkg_id)
            if not pkg:
                self._log("error", f"Unknown package id: {pkg_id}")
                return False

            self._set_status(pkg_id, self.STATUS_STARTING)
            session = PackageSession(pkg_id, pkg["rosmaster_port"])
            self._session = session

        try:
            ok = self._launch_session(session, pkg, session_dir, record)
            if ok:
                self._set_status(pkg_id, self.STATUS_RUNNING)
                self._start_output_thread(session)
            else:
                self._set_status(pkg_id, self.STATUS_CRASHED)
            return ok
        except Exception as exc:
            self._log("error", f"Exception launching {pkg_id}: {exc}")
            self._set_status(pkg_id, self.STATUS_CRASHED)
            return False

    def stop(self) -> None:
        """Stop the currently running session gracefully."""
        with self._lock:
            session = self._session
        if session:
            pkg_id = session.pkg_id
            self._set_status(pkg_id, self.STATUS_STOPPING)
            self._stop_session(session)
            self._set_status(pkg_id, self.STATUS_STOPPED)
            with self._lock:
                self._session = None

    def current_package(self) -> Optional[str]:
        with self._lock:
            return self._session.pkg_id if self._session else None

    def is_running(self) -> bool:
        with self._lock:
            return bool(self._session and self._session.is_alive())

    def get_status(self) -> str:
        return self._current_status

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_env(self, session: PackageSession, workspace: str) -> dict:
        env = os.environ.copy()
        env["ROS_MASTER_URI"] = session.ros_master_uri
        env["ROS_IP"] = "127.0.0.1"
        env["ROS_HOSTNAME"] = "127.0.0.1"
        env["ROSCONSOLE_FORMAT"] = "[${severity}] [${time}]: ${message}"

        ros_setup = self._settings.get("ros", {}).get(
            "melodic_setup", "/opt/ros/melodic/setup.bash"
        )
        ws_setup = os.path.join(workspace, "devel", "setup.bash")

        source_cmds = []
        if os.path.isfile(ros_setup):
            source_cmds.append(f"source {ros_setup}")
        else:
            self._log("warning", f"ROS setup not found: {ros_setup}")

        if os.path.isfile(ws_setup):
            source_cmds.append(f"source {ws_setup}")
        else:
            self._log("warning", f"Workspace devel/setup.bash not found: {ws_setup}")

        if source_cmds:
            combined = " && ".join(source_cmds) + f" && env"
            result = subprocess.run(
                ["bash", "-c", combined],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if "=" in line:
                        k, _, v = line.partition("=")
                        env[k.strip()] = v.strip()

        env["ROS_MASTER_URI"] = session.ros_master_uri
        return env

    def _launch_rosmaster(self, session: PackageSession, env: dict) -> bool:
        timeout = self._settings.get("app", {}).get("rosmaster_start_timeout", 15)
        cmd = ["roscore", "-p", str(session.rosmaster_port)]
        try:
            proc = subprocess.Popen(
                cmd, env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                preexec_fn=os.setsid,
                text=True
            )
            session.rosmaster_proc = proc
            self._log("info", f"roscore started on port {session.rosmaster_port} (pid={proc.pid})")
        except FileNotFoundError:
            self._log("error", "roscore not found — is ROS Melodic installed?")
            return False

        deadline = time.time() + timeout
        while time.time() < deadline:
            if proc.poll() is not None:
                self._log("error", f"roscore exited unexpectedly (rc={proc.returncode})")
                return False
            try:
                import xmlrpc.client
                master = xmlrpc.client.ServerProxy(session.ros_master_uri)
                master.getSystemState("/slam_launcher")
                self._log("info", "ROS master is ready")
                return True
            except Exception:
                time.sleep(0.5)

        self._log("error", f"ROS master did not start within {timeout}s on port {session.rosmaster_port}")
        return False

    def _launch_session(self, session: PackageSession, pkg: dict,
                        session_dir: Optional[Path], record: bool) -> bool:
        workspace = pkg.get("workspace", "")
        launch_script = pkg.get("launch_script", "")

        script_path = Path(__file__).parent.parent / launch_script
        if not script_path.is_file():
            self._log("error", f"Launch script not found: {script_path}")
            return False

        env = self._build_env(session, workspace)

        if not self._launch_rosmaster(session, env):
            return False

        cmd = ["bash", str(script_path)]
        if session_dir:
            cmd += ["--session-dir", str(session_dir)]

        try:
            proc = subprocess.Popen(
                cmd, env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                preexec_fn=os.setsid,
                text=True, bufsize=1
            )
            session.launch_proc = proc
            self._log("info", f"Launched {pkg['id']} (pid={proc.pid})")
        except Exception as exc:
            self._log("error", f"Failed to start launch script: {exc}")
            return False

        if record and session_dir:
            self._start_rosbag(session, pkg, session_dir, env)

        return True

    def _start_rosbag(self, session: PackageSession, pkg: dict,
                      session_dir: Path, env: dict) -> None:
        topics = list(pkg.get("outputs", {}).values())
        if not topics:
            return

        bag_path = session_dir / "recording.bag"
        cmd = ["rosbag", "record", "-O", str(bag_path), "--lz4"] + topics
        try:
            proc = subprocess.Popen(
                cmd, env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                preexec_fn=os.setsid,
                text=True
            )
            session.rosbag_proc = proc
            self._log("info", f"rosbag recording started → {bag_path}")
        except Exception as exc:
            self._log("warning", f"Could not start rosbag: {exc}")

    def _stop_session(self, session: PackageSession) -> None:
        for proc in (session.rosbag_proc, session.launch_proc, session.rosmaster_proc):
            if proc and proc.poll() is None:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                except ProcessLookupError:
                    pass

        deadline = time.time() + 8
        for proc in (session.rosbag_proc, session.launch_proc, session.rosmaster_proc):
            if proc:
                remaining = max(0, deadline - time.time())
                try:
                    proc.wait(timeout=remaining)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    except ProcessLookupError:
                        pass

        self._log("info", f"Session '{session.pkg_id}' fully stopped")

    def _start_output_thread(self, session: PackageSession) -> None:
        def _reader(proc, pkg_id):
            try:
                for line in proc.stdout:
                    line = line.rstrip()
                    if line and self.on_output:
                        self.on_output(pkg_id, line)
                    if proc.poll() is not None:
                        break
            except Exception:
                pass
            finally:
                if self._current_status == self.STATUS_RUNNING:
                    self._log("warning", f"Process for '{pkg_id}' exited unexpectedly")
                    self._set_status(pkg_id, self.STATUS_CRASHED)

        if session.launch_proc and session.launch_proc.stdout:
            t = threading.Thread(
                target=_reader,
                args=(session.launch_proc, session.pkg_id),
                daemon=True
            )
            t.start()
            self._output_threads.append(t)

    def _set_status(self, pkg_id: str, status: str) -> None:
        self._current_status = status
        if self.on_status_change:
            self.on_status_change(pkg_id, status)

    def _log(self, level: str, msg: str) -> None:
        getattr(logger, level, logger.info)(msg)
        if self.on_log:
            self.on_log(level, msg)
