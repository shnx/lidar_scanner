#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# launch_livox_calib.sh — Launch livox_camera_calib in isolation.
#
# ROS_MASTER_URI is pre-set by ProcessManager to port 11312.
# ---------------------------------------------------------------------------

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SESSION_DIR=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --session-dir) SESSION_DIR="$2"; shift 2 ;;
        *) shift ;;
    esac
done

WORKSPACE="/opt/ros_workspaces/livox_calib_ws"
source "$SCRIPT_DIR/env_setup.sh" "$WORKSPACE"

if [[ -n "$SESSION_DIR" ]]; then
    mkdir -p "$SESSION_DIR"
fi

# ── Find launch file ──────────────────────────────────────────────────────
LAUNCH_CANDIDATES=(
    "$WORKSPACE/src/livox_camera_calib/launch/calib.launch"
    "$WORKSPACE/src/livox_camera_calib/launch/livox_camera_calib.launch"
)

LAUNCH_FILE=""
for candidate in "${LAUNCH_CANDIDATES[@]}"; do
    if [[ -f "$candidate" ]]; then
        LAUNCH_FILE="$candidate"
        break
    fi
done

if [[ -z "$LAUNCH_FILE" ]]; then
    echo "[ERROR] livox_camera_calib launch file not found in workspace: $WORKSPACE" >&2
    echo "[INFO]  Searched: ${LAUNCH_CANDIDATES[*]}" >&2
    exit 1
fi

echo "[INFO] Launching livox_camera_calib → $LAUNCH_FILE"

# ── Run calibration; on exit, post-process the result YAML ───────────────
exec roslaunch "$LAUNCH_FILE" \
    --screen \
    2>&1
