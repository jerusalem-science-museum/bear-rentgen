#!/usr/bin/env bash
# =============================================================================
# Raspberry Pi Project Setup Script
# Run from inside the cloned repo on a fresh Raspberry Pi OS install.
#
# Usage:
#   git clone <your-repo-url>
#   cd <repo-folder>
#   chmod +x setup.sh && ./setup.sh
#
# Notes:
#   - AnyDesk supports Pi 2/3/4/400 only (not Pi 5)
#   - AnyDesk requires a desktop environment (Xorg) for incoming connections
#   - For 1080p VLC on Pi 3B: always use --codec=mmal or --codec=v4l2 to enable
#     hardware decoding, otherwise the CPU will struggle
# =============================================================================

set -euo pipefail

# --- Config ------------------------------------------------------------------
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"  # wherever this script lives
VENV_DIR="$REPO_DIR/.venv"
USER="${SUDO_USER:-$(whoami)}"
HOME_DIR="/home/$USER"
# -----------------------------------------------------------------------------

echo "============================================="
echo " Raspberry Pi Project Setup"
echo " Repo: $REPO_DIR"
echo "============================================="

# --- 0. Sudo + AnyDesk password prompt ----------------------------------------
# Refresh sudo credentials up-front so later sudo calls don't re-prompt.
sudo -v

# If AnyDesk is not yet installed, ask for the unattended-access password now
# so the rest of the script can run unattended.
ANYDESK_PWD=""
if ! command -v anydesk &>/dev/null; then
    echo ""
    read -rsp "Enter password to set for AnyDesk unattended access: " ANYDESK_PWD
    echo ""
    if [ -z "$ANYDESK_PWD" ]; then
        echo "  ⚠️  No password provided — AnyDesk password will NOT be set automatically."
    fi
fi

# --- 1. System packages -------------------------------------------------------
echo ""
echo "[1/4] Installing system packages..."

sudo apt-get update -y
sudo apt-get install -y \
    python3 \
    python3-venv \
    python3-pip \
    tmux \
    unclutter
    # Add any other apt packages your project needs, e.g.:
    # libgpiod2
    # i2c-tools
    # ffmpeg

echo "  ✓ System packages installed"

# --- 2. AnyDesk ---------------------------------------------------------------
echo ""
echo "[2/4] Installing AnyDesk..."

if command -v anydesk &>/dev/null; then
    echo "  AnyDesk already installed, skipping"
else
    sudo apt-get install -y wget gnupg
    sudo mkdir -p /etc/apt/keyrings
    wget -qO - https://keys.anydesk.com/repos/DEB-GPG-KEY | sudo gpg --dearmor -o /etc/apt/keyrings/anydesk.gpg
    echo "deb [signed-by=/etc/apt/keyrings/anydesk.gpg] http://deb.anydesk.com/ all main" | sudo tee /etc/apt/sources.list.d/anydesk-stable.list
    sudo apt-get update -y
    sudo apt-get install -y anydesk

    sudo systemctl enable anydesk
    sudo systemctl start anydesk

    echo "  ✓ AnyDesk installed and service enabled"

    # Set unattended access password if one was provided at the start
    if [ -n "$ANYDESK_PWD" ]; then
        echo "$ANYDESK_PWD" | sudo anydesk --set-password
        echo "  ✓ AnyDesk unattended access password set"
    else
        echo "  ⚠️  No password was provided — set one manually in AnyDesk settings"
    fi
fi

# --- 3. Python venv + dependencies --------------------------------------------
echo ""
echo "[3/4] Setting up Python virtual environment..."

if [ -d "$VENV_DIR" ]; then
    echo "  Venv already exists, skipping creation"
else
    python3 -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/pip" install --upgrade pip

if [ -f "$REPO_DIR/requirements.txt" ]; then
    "$VENV_DIR/bin/pip" install -r "$REPO_DIR/requirements.txt"
    echo "  ✓ Dependencies installed from requirements.txt"
else
    echo "  ⚠️  No requirements.txt found — skipping pip install"
fi

echo "  ✓ Venv ready at $VENV_DIR"

# --- 4. GUI auto-login + autostart app ----------------------------------------
echo ""
echo "[4/4] Configuring GUI auto-login and app autostart..."

# Force X11 (Xorg) instead of Wayland. RPi OS Bookworm defaults to Wayland,
# but AnyDesk requires X11 for incoming connections.
sudo raspi-config nonint do_wayland W1
echo "  ✓ Display server set to X11"

# Boot to desktop GUI with auto-login (B4 = desktop autologin)
# Required so the .desktop autostart entry below actually fires on boot.
sudo raspi-config nonint do_boot_behaviour B4

# remove screen blanking so the screen never goes off.
sudo raspi-config nonint do_blanking 1

# Create autostart directory if it doesn't exist
AUTOSTART_DIR="$HOME_DIR/.config/autostart"
mkdir -p "$AUTOSTART_DIR"

# Drop a .desktop entry to launch run.sh when the desktop session starts
AUTOSTART_FILE="$AUTOSTART_DIR/kiosk.desktop"
cat > "$AUTOSTART_FILE" << EOF
[Desktop Entry]
Type=Application
Name=Kiosk App
Exec=lxterminal -e bash -c '"$REPO_DIR/run.sh"; read'
X-GNOME-Autostart-enabled=true
EOF

echo "  ✓ Autostart entry created at $AUTOSTART_FILE"

# Ensure run.sh is executable
if [ -f "$REPO_DIR/run.sh" ]; then
    chmod +x "$REPO_DIR/run.sh"
    echo "  ✓ run.sh is executable"
else
    echo "  ⚠️  No run.sh found — create one to define how your app starts"
fi

# --- Done ---------------------------------------------------------------------
ANYDESK_ID=$(anydesk --get-id 2>/dev/null || echo "(not available yet)")

echo ""
echo "============================================="
echo " Setup complete!"
echo ""
echo " AnyDesk ID: $ANYDESK_ID"
echo ""
echo " Next steps:"
echo "   1. Write down the AnyDesk ID above!"
echo "   2. Make sure VLC uses hardware decoding in run.sh for smooth 1080p:"
echo "      cvlc --codec=mmal <your_file>"
echo "   3. Reboot to apply autologin + autostart: sudo reboot"
echo "============================================="
