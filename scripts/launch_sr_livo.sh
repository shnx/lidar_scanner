#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# launch_sr_livo.sh — Launch SR-LIVO in isolation.
#
# ROS_MASTER_URI is pre-set by ProcessManager to port 11313.
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

WORKSPACE="/opt/ros_workspaces/sr_livo_ws"
source "$SCRIPT_DIR/env_setup.sh" "$WORKSPACE"

if [[ -n "$SESSION_DIR" ]]; then
    mkdir -p "$SESSION_DIR"
    CFG="$WORKSPACE/src/sr_livo/config/sr_livo.yaml"
    [[ -f "$CFG" ]] && cp "$CFG" "$SESSION_DIR/sr_livo_config.yaml"
fi

LAUNCH_CANDIDATES=(
    "$WORKSPACE/src/sr_livo/launch/mapping.launch"
    "$WORKSPACE/src/sr_livo/launch/sr_livo.launch"
    "$WORKSPACE/src/sr_livo/launch/run.launch"
)

LAUNCH_FILE=""
for candidate in "${LAUNCH_CANDIDATES[@]}"; do
    if [[ -f "$candidate" ]]; then
        LAUNCH_FILE="$candidate"
        break
    fi
done

if [[ -z "$LAUNCH_FILE" ]]; then
    echo "[ERROR] SR-LIVO launch file not found in workspace: $WORKSPACE" >&2
    echo "[INFO]  Searched: ${LAUNCH_CANDIDATES[*]}" >&2
    exit 1
fi

echo "[INFO] Launching SR-LIVO → $LAUNCH_FILE"
exec roslaunch "$LAUNCH_FILE" \
    --screen \
    2>&1
