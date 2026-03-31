#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# env_setup.sh — Common environment sourcing helper.
# Source this file inside each per-package launch script.
#
# Usage:
#   source "$(dirname "$0")/env_setup.sh" <workspace_path>
# ---------------------------------------------------------------------------

set -euo pipefail

WORKSPACE_PATH="${1:-}"

# ── ROS Melodic base ────────────────────────────────────────────────────────
ROS_SETUP="/opt/ros/melodic/setup.bash"
if [[ -f "$ROS_SETUP" ]]; then
    # shellcheck source=/dev/null
    source "$ROS_SETUP"
else
    echo "[ERROR] ROS Melodic setup not found at $ROS_SETUP" >&2
    exit 1
fi

# ── Per-package workspace ────────────────────────────────────────────────────
if [[ -n "$WORKSPACE_PATH" ]]; then
    WS_SETUP="$WORKSPACE_PATH/devel/setup.bash"
    if [[ -f "$WS_SETUP" ]]; then
        # shellcheck source=/dev/null
        source "$WS_SETUP"
    else
        echo "[WARN] Workspace devel/setup.bash not found: $WS_SETUP" >&2
    fi
fi

# ── Verify ROS_MASTER_URI is set (caller must set it) ──────────────────────
if [[ -z "${ROS_MASTER_URI:-}" ]]; then
    echo "[ERROR] ROS_MASTER_URI is not set" >&2
    exit 1
fi

echo "[INFO] Environment ready. ROS_MASTER_URI=${ROS_MASTER_URI}"
