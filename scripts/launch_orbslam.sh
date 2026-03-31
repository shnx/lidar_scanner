#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# launch_orbslam.sh — Launch ORB-SLAM3 (ROS wrapper) in isolation.
#
# ROS_MASTER_URI is pre-set by ProcessManager to port 11314.
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

WORKSPACE="/opt/ros_workspaces/orbslam_ws"
source "$SCRIPT_DIR/env_setup.sh" "$WORKSPACE"

if [[ -n "$SESSION_DIR" ]]; then
    mkdir -p "$SESSION_DIR"
    for CFG in \
        "$WORKSPACE/src/ORB_SLAM3/Vocabulary/ORBvoc.txt" \
        "$WORKSPACE/src/ORB_SLAM3/Examples/RGB-D/TUM1.yaml"; do
        [[ -f "$CFG" ]] && cp "$CFG" "$SESSION_DIR/"
    done
fi

LAUNCH_CANDIDATES=(
    "$WORKSPACE/src/ORB_SLAM3/Examples/ROS/ORB_SLAM3/launch/rgbd.launch"
    "$WORKSPACE/src/orb_slam3_ros/launch/rgbd.launch"
    "$WORKSPACE/src/orb_slam3_ros_wrapper/launch/slam_rgbd.launch"
)

LAUNCH_FILE=""
for candidate in "${LAUNCH_CANDIDATES[@]}"; do
    if [[ -f "$candidate" ]]; then
        LAUNCH_FILE="$candidate"
        break
    fi
done

if [[ -z "$LAUNCH_FILE" ]]; then
    echo "[ERROR] ORB-SLAM3 ROS launch file not found in workspace: $WORKSPACE" >&2
    echo "[INFO]  Searched: ${LAUNCH_CANDIDATES[*]}" >&2
    exit 1
fi

echo "[INFO] Launching ORB-SLAM3 → $LAUNCH_FILE"
exec roslaunch "$LAUNCH_FILE" \
    --screen \
    2>&1
