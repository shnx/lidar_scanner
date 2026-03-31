"""
NodeWatchdog — Background thread that polls the active session's
process health and triggers auto-recovery when a crash is detected.
"""

import threading
import time
import logging
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class NodeWatchdog:
    """
    Polls ProcessManager.is_running() at a fixed interval.
    If it detects a crash (STATUS_CRASHED), it calls the recovery
    callback up to max_attempts times, with a configurable delay.
    """

    def __init__(self, settings: dict):
        cfg = settings.get("app", {})
        self._interval: float = cfg.get("node_health_check_interval", 2)
        self._max_attempts: int = cfg.get("recovery_max_attempts", 3)
        self._delay: float = cfg.get("recovery_delay_seconds", 5)

        self._enabled: bool = cfg.get("auto_recover", True)
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        self._attempt_count: int = 0
        self._last_crashed_pkg: Optional[str] = None

        self.on_crash_detected: Optional[Callable[[str], None]] = None
        self.on_recovery_attempt: Optional[Callable[[str, int], None]] = None
        self.on_recovery_success: Optional[Callable[[str], None]] = None
        self.on_recovery_failed: Optional[Callable[[str], None]] = None
        self.on_log: Optional[Callable] = None

        self._process_manager = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def attach(self, process_manager) -> None:
        """Attach to a ProcessManager instance and start watching."""
        self._process_manager = process_manager
        self.start()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._thread.start()
        self._log("debug", "Watchdog started")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._log("debug", "Watchdog stopped")

    def reset(self) -> None:
        """Reset attempt counter (call when a new session starts cleanly)."""
        self._attempt_count = 0
        self._last_crashed_pkg = None

    # ------------------------------------------------------------------
    # Watch loop
    # ------------------------------------------------------------------

    def _watch_loop(self) -> None:
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=self._interval)
            if self._stop_event.is_set():
                break
            self._check()

    def _check(self) -> None:
        pm = self._process_manager
        if pm is None:
            return

        status = pm.get_status()
        pkg_id = pm.current_package()

        if status != "crashed" or not pkg_id:
            if status in ("running", "idle", "stopped"):
                self._attempt_count = 0
                self._last_crashed_pkg = None
            return

        if not self._enabled:
            self._log("warning", f"Auto-recovery disabled. Package '{pkg_id}' crashed.")
            return

        if pkg_id != self._last_crashed_pkg:
            self._last_crashed_pkg = pkg_id
            self._attempt_count = 0

        if self._attempt_count >= self._max_attempts:
            self._log("error",
                f"Max recovery attempts ({self._max_attempts}) reached for '{pkg_id}'. "
                "Manual intervention required.")
            if self.on_recovery_failed:
                self.on_recovery_failed(pkg_id)
            return

        self._attempt_count += 1
        self._log("warning",
            f"Crash detected for '{pkg_id}'. "
            f"Recovery attempt {self._attempt_count}/{self._max_attempts} in {self._delay}s …")

        if self.on_crash_detected:
            self.on_crash_detected(pkg_id)

        time.sleep(self._delay)

        if self.on_recovery_attempt:
            self.on_recovery_attempt(pkg_id, self._attempt_count)

        try:
            ok = pm.start(pkg_id)
            if ok:
                self._log("info", f"Recovery of '{pkg_id}' succeeded (attempt {self._attempt_count})")
                if self.on_recovery_success:
                    self.on_recovery_success(pkg_id)
            else:
                self._log("error", f"Recovery attempt {self._attempt_count} for '{pkg_id}' failed")
        except Exception as exc:
            self._log("error", f"Exception during recovery: {exc}")

    def _log(self, level: str, msg: str) -> None:
        getattr(logger, level, logger.info)(msg)
        if self.on_log:
            self.on_log(level, msg)
