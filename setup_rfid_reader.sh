#!/usr/bin/env bash
# =============================================================================
# RFID reader reliability setup (Raspberry Pi). Run once, from the repo:
#
#   sudo ./setup_rfid_reader.sh                    # auto-detect the reader
#   sudo ./setup_rfid_reader.sh --vid 2341 --pid 8036
#
# What it does:
#   1. Installs uhubctl (cuts/restores USB port power) and usbutils
#   2. Identifies the reader's USB vendor:product ID
#   3. Disables USB autosuspend (kernel cmdline + udev rule for the reader)
#   4. Writes /etc/default/rfid-reader (re-runs keep your tuned values)
#   5. Installs a systemd timer that runs rfid_reader_watchdog.sh every minute
#   6. Reports whether the Pi has had under-voltage
#
# Safe to re-run. Needs a reboot for the cmdline change.
# =============================================================================

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG=/etc/default/rfid-reader
UDEV_RULE=/etc/udev/rules.d/90-rfid-reader.rules
UNIT_DIR=/etc/systemd/system

if [ "$EUID" -ne 0 ]; then
    exec sudo "$0" "$@"
fi

VID=""; PID=""
while [ $# -gt 0 ]; do
    case "$1" in
        --vid) VID="${2,,}"; shift 2 ;;
        --pid) PID="${2,,}"; shift 2 ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
done

echo "============================================="
echo " RFID reader reliability setup"
echo " Repo: $REPO_DIR"
echo "============================================="

# --- 1. Packages ----------------------------------------------------------------
echo ""
echo "[1/6] Installing uhubctl + usbutils..."
apt-get install -y uhubctl usbutils >/dev/null
echo "  ✓ Installed"

# --- 2. Identify the reader ----------------------------------------------------------
echo ""
echo "[2/6] Identifying the RFID reader..."

if [ -z "$VID" ] || [ -z "$PID" ]; then
    # Known Arduino-family vendor IDs (Arduino, Arduino.org, SparkFun, Adafruit)
    candidates=$(lsusb | grep -Eio 'ID (2341|2a03|1b4f|239a):[0-9a-f]{4}' || true)
    if [ "$(echo "$candidates" | grep -c .)" -eq 1 ]; then
        id=${candidates#ID }
        echo "  Found Arduino-type device: $(lsusb | grep -i "$id")"
    else
        echo "  Couldn't pick the reader automatically. Let's find it by replugging it."
        read -rp "  Unplug the RFID reader's USB cable, then press Enter... " _
        before=$(lsusb | sort)
        read -rp "  Plug it back in, wait 5 seconds, then press Enter... " _
        after=$(lsusb | sort)
        new=$(comm -13 <(echo "$before") <(echo "$after"))
        if [ "$(echo "$new" | grep -c .)" -ne 1 ]; then
            echo "  ⚠️  Expected exactly one new USB device, saw:"
            echo "${new:-  (none)}"
            echo "  Run 'lsusb' and re-run with --vid XXXX --pid YYYY"
            exit 1
        fi
        echo "  Found: $new"
        id=$(echo "$new" | grep -Eio 'ID [0-9a-f]{4}:[0-9a-f]{4}')
        id=${id#ID }
    fi
    VID=${id%%:*}; VID=${VID,,}
    PID=${id##*:}; PID=${PID,,}
fi
echo "  ✓ Reader is $VID:$PID"

# --- 3. Disable USB autosuspend ---------------------------------------------------
echo ""
echo "[3/6] Disabling USB autosuspend..."

CMDLINE=/boot/firmware/cmdline.txt
[ -f "$CMDLINE" ] || CMDLINE=/boot/cmdline.txt
if grep -q 'usbcore\.autosuspend=-1' "$CMDLINE"; then
    echo "  cmdline already has usbcore.autosuspend=-1"
else
    cp "$CMDLINE" "$CMDLINE.bak-rfid"
    if grep -q 'usbcore\.autosuspend=' "$CMDLINE"; then
        sed -i 's/usbcore\.autosuspend=[^ ]*/usbcore.autosuspend=-1/' "$CMDLINE"
    else
        sed -i '1 s/$/ usbcore.autosuspend=-1/' "$CMDLINE"
    fi
    echo "  ✓ Added usbcore.autosuspend=-1 to $CMDLINE (backup: $CMDLINE.bak-rfid)"
fi
# Apply now for newly plugged devices, without waiting for the reboot
echo -1 > /sys/module/usbcore/parameters/autosuspend 2>/dev/null || true

cat > "$UDEV_RULE" << EOF
# Keep the RFID reader (Arduino Leonardo keyboard) from ever autosuspending
ACTION=="add", SUBSYSTEM=="usb", ATTR{idVendor}=="$VID", ATTR{idProduct}=="$PID", TEST=="power/control", ATTR{power/control}="on"
EOF
udevadm control --reload-rules
echo "  ✓ udev rule written to $UDEV_RULE"

# --- 4. Config -----------------------------------------------------------------
echo ""
echo "[4/6] Writing $CONFIG..."

# Keep values from a previous run if they were tuned
RESET_INTERVAL_MIN=30; IDLE_SECONDS=60; RESET_SCOPE=hub; MISSING_RETRY_MIN=5
# shellcheck source=/dev/null
[ -f "$CONFIG" ] && . "$CONFIG"

cat > "$CONFIG" << EOF
# RFID reader watchdog settings (read by rfid_reader_watchdog.sh every minute)
READER_VID=$VID
READER_PID=$PID
REPO_DIR="$REPO_DIR"
# Preventively power-cycle the reader this often (minutes). 0 = only when it
# disappears from USB. Lower it if the reader still freezes between resets.
RESET_INTERVAL_MIN=$RESET_INTERVAL_MIN
# ...but only if nobody has scanned for this many seconds.
IDLE_SECONDS=$IDLE_SECONDS
# hub = cut power to the whole USB hub (needed on the Pi's own ports, where
#       power is shared; other USB devices blink off for ~5 s too)
# port = only the reader's port (needs a powered hub with per-port switching)
RESET_SCOPE=$RESET_SCOPE
# If the reader vanishes from USB, retry a power-cycle at most this often.
MISSING_RETRY_MIN=$MISSING_RETRY_MIN
EOF
echo "  ✓ Config written"

# --- 5. systemd timer ----------------------------------------------------------
echo ""
echo "[5/6] Installing watchdog timer..."

chmod +x "$REPO_DIR/rfid_reader_watchdog.sh"

cat > "$UNIT_DIR/rfid-reader-watchdog.service" << EOF
[Unit]
Description=RFID reader watchdog (USB autosuspend, power checks, auto reset)

[Service]
Type=oneshot
ExecStart="$REPO_DIR/rfid_reader_watchdog.sh"
EOF

cat > "$UNIT_DIR/rfid-reader-watchdog.timer" << EOF
[Unit]
Description=Run the RFID reader watchdog every minute

[Timer]
# Monotonic timers (not wall-clock/cron), so NTP time jumps on the RTC-less Pi
# don't matter. OnActiveSec makes it start right after install, not only on boot.
OnBootSec=2min
OnActiveSec=1min
OnUnitActiveSec=1min
AccuracySec=10s

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now rfid-reader-watchdog.timer >/dev/null
echo "  ✓ rfid-reader-watchdog.timer enabled"

# --- 6. Power report -----------------------------------------------------------
echo ""
echo "[6/6] Checking Pi power..."

if command -v vcgencmd &>/dev/null; then
    t=$(vcgencmd get_throttled | cut -d= -f2)
    if (( t & 0x1 )); then
        echo "  ❌ Under-voltage RIGHT NOW ($t). Use the official Pi power supply."
    elif (( t & 0x10000 )); then
        echo "  ⚠️  Under-voltage has happened since boot ($t). Use the official Pi power supply."
    else
        echo "  ✓ No under-voltage since boot ($t)"
    fi
else
    echo "  vcgencmd not found - skipping"
fi

if command -v uhubctl &>/dev/null && ! uhubctl >/dev/null 2>&1; then
    echo "  ⚠️  uhubctl found no switchable USB hub - power-cycling won't work,"
    echo "     the watchdog will fall back to softer resets."
fi

echo ""
echo "============================================="
echo " Done! Reboot to apply the autosuspend change: sudo reboot"
echo ""
echo " Test a reset now (reader should beep/reconnect within ~15 s):"
echo "   sudo \"$REPO_DIR/rfid_reader_watchdog.sh\" --reset-now"
echo " Watch the log:"
echo "   tail -f \"$REPO_DIR/rfid_reader_watchdog.log\""
echo ""
echo " Hardware tip: if under-voltage shows up, or the reader still freezes,"
echo " put a POWERED USB hub between the Pi and the reader."
echo "============================================="
