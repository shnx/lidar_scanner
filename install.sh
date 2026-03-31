#!/usr/bin/env bash
# =============================================================================
# install.sh — SLAM Launcher one-shot installer
#
# Installs Python dependencies, makes scripts executable, generates the
# application icon, and creates a desktop shortcut.
#
# Usage:
#   chmod +x install.sh && ./install.sh
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$SCRIPT_DIR"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

log_info()    { echo -e "${GREEN}[✓]${NC} $*"; }
log_warn()    { echo -e "${YELLOW}[!]${NC} $*"; }
log_error()   { echo -e "${RED}[✗]${NC} $*"; }
log_section() { echo -e "\n${BOLD}${BLUE}══ $* ══${NC}"; }

# ── Prerequisite checks ───────────────────────────────────────────────────────
log_section "Checking prerequisites"

if ! command -v python3 &>/dev/null; then
    log_error "python3 not found. Install with: sudo apt install python3"
    exit 1
fi
PYTHON=$(command -v python3)
PY_VER=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
log_info "Python $PY_VER found at $PYTHON"

if ! command -v pip3 &>/dev/null; then
    log_warn "pip3 not found. Installing..."
    sudo apt-get install -y python3-pip
fi

if [[ ! -f /opt/ros/melodic/setup.bash ]]; then
    log_warn "ROS Melodic not found at /opt/ros/melodic/setup.bash"
    log_warn "Install ROS first: http://wiki.ros.org/melodic/Installation/Ubuntu"
fi

# ── System packages ───────────────────────────────────────────────────────────
log_section "Installing system packages"

SYSTEM_PKGS=(
    python3-pyqt5
    python3-pyqt5.qtsvg
    libopengl0
    libglib2.0-0
    libgl1-mesa-glx
    libglu1-mesa
    libxcb-icccm4
    libxcb-image0
    libxcb-keysyms1
    libxcb-randr0
    libxcb-render-util0
    libxcb-xinerama0
    python3-numpy
    python3-yaml
)

MISSING_PKGS=()
for pkg in "${SYSTEM_PKGS[@]}"; do
    if ! dpkg -s "$pkg" &>/dev/null; then
        MISSING_PKGS+=("$pkg")
    fi
done

if [[ ${#MISSING_PKGS[@]} -gt 0 ]]; then
    log_info "Installing: ${MISSING_PKGS[*]}"
    sudo apt-get install -y "${MISSING_PKGS[@]}"
else
    log_info "All system packages already installed"
fi

# ── Python packages ───────────────────────────────────────────────────────────
log_section "Installing Python packages"

pip3 install --user -r "$APP_DIR/requirements.txt" \
    --no-warn-script-location \
    2>&1 | grep -v "^Requirement already" || true

log_info "Python packages installed"

# ── Make scripts executable ───────────────────────────────────────────────────
log_section "Configuring scripts"

chmod +x "$APP_DIR/scripts/"*.sh
chmod +x "$APP_DIR/main.py"
log_info "Scripts are executable"

# ── Generate application icon ─────────────────────────────────────────────────
log_section "Generating application icon"

mkdir -p "$APP_DIR/assets/icons"

export APP_DIR="$APP_DIR"
"$PYTHON" - <<'PYEOF'
import sys, os, pathlib
app_dir = pathlib.Path(os.environ.get("APP_DIR", "."))
try:
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtGui import QPixmap, QPainter, QColor, QFont, QLinearGradient, QBrush
    from PyQt5.QtCore import Qt, QRect
    import sys
    app = QApplication.instance() or QApplication(sys.argv[:1])
    pix = QPixmap(256, 256)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    grad = QLinearGradient(0, 0, 256, 256)
    grad.setColorAt(0, QColor("#0d1117"))
    grad.setColorAt(1, QColor("#161b22"))
    p.setBrush(QBrush(grad))
    p.setPen(QColor("#30363d"))
    p.drawRoundedRect(8, 8, 240, 240, 40, 40)
    font = QFont("Ubuntu", 42, QFont.Bold)
    p.setFont(font)
    p.setPen(QColor("#58a6ff"))
    p.drawText(QRect(0, 60, 256, 80), Qt.AlignHCenter, "SLAM")
    font2 = QFont("Ubuntu", 14)
    p.setFont(font2)
    p.setPen(QColor("#8b949e"))
    p.drawText(QRect(0, 140, 256, 30), Qt.AlignHCenter, "LAUNCHER")
    p.setBrush(QColor("#3fb950"))
    p.setPen(Qt.NoPen)
    p.drawEllipse(110, 185, 36, 36)
    p.end()
    assets = app_dir / "assets"
    assets.mkdir(exist_ok=True)
    (assets / "icons").mkdir(exist_ok=True)
    pix.save(str(assets / "icon.png"))
    for name, color in [("lidar","#2ECC71"),("calibration","#3498DB"),
                         ("odometry","#9B59B6"),("slam","#E74C3C")]:
        sp = QPixmap(48, 48)
        sp.fill(Qt.transparent)
        sp2 = QPainter(sp)
        sp2.setRenderHint(QPainter.Antialiasing)
        sp2.setBrush(QColor(color))
        sp2.setPen(Qt.NoPen)
        sp2.drawEllipse(4, 4, 40, 40)
        sp2.end()
        sp.save(str(assets / "icons" / f"{name}.png"))
    print("Icons OK")
except Exception as e:
    print(f"Icon gen error: {e}")
PYEOF

# ── Desktop entry ─────────────────────────────────────────────────────────────
log_section "Creating desktop shortcut"

DESKTOP_FILE="$HOME/.local/share/applications/slam_launcher.desktop"
ICON_PATH="$APP_DIR/assets/icon.png"

mkdir -p "$HOME/.local/share/applications"

cat > "$DESKTOP_FILE" <<DESKTOP
[Desktop Entry]
Version=1.0
Type=Application
Name=SLAM Launcher
Name[ar]=منصة SLAM
Comment=Unified SLAM Orchestration Platform
Comment[ar]=منصة تشغيل وإدارة خوارزميات SLAM
Exec=bash -c "cd '$APP_DIR' && python3 '$APP_DIR/main.py'"
Icon=$ICON_PATH
Terminal=false
Categories=Science;Robotics;
Keywords=SLAM;ROS;LiDAR;Robotics;Mapping;
StartupWMClass=slam_launcher
DESKTOP

chmod +x "$DESKTOP_FILE"

# Also place one on the Desktop if it exists
if [[ -d "$HOME/Desktop" ]]; then
    cp "$DESKTOP_FILE" "$HOME/Desktop/slam_launcher.desktop"
    chmod +x "$HOME/Desktop/slam_launcher.desktop"
    log_info "Desktop shortcut created: ~/Desktop/slam_launcher.desktop"
fi

log_info "Application menu shortcut created"

# ── Create workspace directories (stubs) ─────────────────────────────────────
log_section "Preparing workspace stubs"

WORKSPACES=(
    /opt/ros_workspaces/r3live_ws
    /opt/ros_workspaces/livox_calib_ws
    /opt/ros_workspaces/sr_livo_ws
    /opt/ros_workspaces/orbslam_ws
)

for ws in "${WORKSPACES[@]}"; do
    if [[ ! -d "$ws" ]]; then
        log_warn "Workspace not found: $ws"
        log_warn "  → Build and install the package, then re-run this installer"
    else
        log_info "Workspace found: $ws"
    fi
done

# ── Create sessions directory ─────────────────────────────────────────────────
SESSIONS_DIR="$HOME/slam_sessions"
mkdir -p "$SESSIONS_DIR"
log_info "Sessions directory: $SESSIONS_DIR"

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}════════════════════════════════════════${NC}"
echo -e "${BOLD}${GREEN}  SLAM Launcher installed successfully!${NC}"
echo -e "${BOLD}${GREEN}════════════════════════════════════════${NC}"
echo ""
echo -e "  Launch:  ${BOLD}python3 $APP_DIR/main.py${NC}"
echo -e "  Desktop: Search for 'SLAM Launcher' in your app menu"
echo ""
