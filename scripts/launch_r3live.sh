#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# launch_r3live.sh — Launch R3LIVE in its isolated ROS environment.
#
# Called by ProcessManager with:
#   ROS_MASTER_URI already set to http://localhost:11311
#   Optional: --session-dir <path>
# ---------------------------------------------------------------------------

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Parse args ──────────────────────────────────────────────────────────────
SESSION_DIR=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --session-dir) SESSION_DIR="$2"; shift 2 ;;
        *) shift ;;
    esac
done

# ── Source environment ───────────────────────────────────────────────────────
WORKSPACE="/opt/ros_workspaces/r3live_ws"
source "$SCRIPT_DIR/env_setup.sh" "$WORKSPACE"

# ── Copy config snapshot if session dir provided ─────────────────────────────
if [[ -n "$SESSION_DIR" ]]; then
    mkdir -p "$SESSION_DIR"
    LAUNCH_CFG="$WORKSPACE/src/r3live/r3live/config/r3live_config.yaml"
    [[ -f "$LAUNCH_CFG" ]] && cp "$LAUNCH_CFG" "$SESSION_DIR/r3live_config.yaml"
fi

# ── Select launch file ────────────────────────────────────────────────────────
# Prefer a bag-playback launch if a bag is present in session dir,
# otherwise use the live sensor launch.
if [[ -f "$WORKSPACE/src/r3live/r3live/launch/r3live_LiDAR_camera_IMU.launch" ]]; then
    LAUNCH_FILE="$WORKSPACE/src/r3live/r3live/launch/r3live_LiDAR_camera_IMU.launch"
else
    echo "[ERROR] R3LIVE launch file not found in workspace: $WORKSPACE" >&2
    echo "[INFO]  Expected: r3live/launch/r3live_LiDAR_camera_IMU.launch" >&2
    exit 1
fi

echo "[INFO] Launching R3LIVE → $LAUNCH_FILE"
exec roslaunch "$LAUNCH_FILE" \
    --screen \
    2>&1
