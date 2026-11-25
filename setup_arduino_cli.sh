#!/usr/bin/env bash
# =============================================================================
# Installs what the Pi needs to compile and upload reader/reader.ino to the
# Reader (Pro Micro, 5 V / 16 MHz) over USB. Safe to run again.
#
# Usage, from the cloned repo:
#   ./setup_arduino_cli.sh
#
# Then, to flash from the repo folder (quit the app first with Escape, it holds
# the serial port), in a new terminal:
#   ac reader
# where `ac` is the alias this script adds to ~/.bashrc for
#   arduino-cli compile --upload -v -b SparkFun:avr:promicro:cpu=16MHzatmega32U4 -p /dev/ttyACM0
# =============================================================================

set -euo pipefail

USER="${SUDO_USER:-$(whoami)}"

sudo -v

# --- 1. arduino-cli -----------------------------------------------------------
# Official command-line Arduino; picks the right build for the Pi (ARMv7/ARM64).
echo "[1/4] Installing arduino-cli..."
if command -v arduino-cli &>/dev/null; then
    echo "  arduino-cli already installed, skipping"
else
    sudo apt-get update -y
    sudo apt-get install -y curl
    curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh \
        | sudo BINDIR=/usr/local/bin sh
fi
arduino-cli version

# --- 2. Pro Micro board package + MFRC522 and Keyboard libraries --------------
# These install into the user's ~/.arduino15 and ~/Arduino, so not with sudo.
# arduino:avr brings the compiler and avrdude; SparkFun:avr adds the Pro Micro
# board (built on top of arduino:avr), including the "1200 baud reset" that
# puts it into its bootloader for upload.
SPARKFUN_URL=https://raw.githubusercontent.com/sparkfun/Arduino_Boards/main/IDE_Board_Manager/package_sparkfun_index.json
echo "[2/4] Installing Pro Micro board package, MFRC522 and Keyboard libraries..."
arduino-cli core update-index --additional-urls "$SPARKFUN_URL"
arduino-cli core install arduino:avr
arduino-cli core install SparkFun:avr --additional-urls "$SPARKFUN_URL"
arduino-cli lib install "MFRC522"
arduino-cli lib install "Keyboard"
echo "  ✓ Toolchain ready"

# --- 3. Serial port permission -------------------------------------------------
echo "[3/4] Allowing $USER to open serial ports..."
sudo usermod -aG dialout "$USER"
echo "  ✓ $USER is in dialout (log out and back in if it was just added)"

# --- 4. `ac` alias ---------------------------------------------------------------
# `ac <sketch folder>` compiles and uploads to the Pro Micro on /dev/ttyACM0.
echo "[4/4] Adding 'ac' alias to ~/.bashrc..."
USER_HOME="$(getent passwd "$USER" | cut -d: -f6)"
AC_ALIAS="alias ac='arduino-cli compile --upload -v -b SparkFun:avr:promicro:cpu=16MHzatmega32U4 -p /dev/ttyACM0'"
if grep -q "^alias ac=" "$USER_HOME/.bashrc" 2>/dev/null; then
    sed -i "s|^alias ac=.*|$AC_ALIAS|" "$USER_HOME/.bashrc"
else
    echo "$AC_ALIAS" >> "$USER_HOME/.bashrc"
fi
echo "  ✓ 'ac' alias ready (open a new terminal, or run: source ~/.bashrc)"

echo ""
echo "Done. To flash the Reader:"
echo "  1. Quit the app (Escape)."
echo "  2. arduino-cli board list          # find the port, usually /dev/ttyACM0"
echo "  3. ac reader                       # in a new terminal; = arduino-cli compile --upload ... reader"
echo "  4. arduino-cli monitor -p /dev/ttyACM0   # expect 'L boot module=ok ...', Ctrl+C to exit"
