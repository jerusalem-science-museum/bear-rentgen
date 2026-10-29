#!/usr/bin/env bash
# =============================================================================
# RFID reader watchdog - runs every minute as root (rfid-reader-watchdog.timer).
# Installed by setup_rfid_reader.sh; settings live in /etc/default/rfid-reader.
#
# The reader (an Arduino Leonardo acting as a USB keyboard) sometimes freezes
# and stops beeping. It can't tell us it's frozen, so this script:
#   - keeps USB autosuspend off for the reader
#   - logs Pi under-voltage events (vcgencmd get_throttled)
#   - power-cycles the reader if it disappears from USB
#   - power-cycles it preventively every RESET_INTERVAL_MIN minutes, but only
#     when nobody has scanned for IDLE_SECONDS (a reset takes ~10 s)
#
# Manual use:  sudo ./rfid_reader_watchdog.sh --reset-now
# Log:         rfid_reader_watchdog.log (repo dir) and journalctl -u rfid-reader-watchdog
# =============================================================================

set -uo pipefail

CONFIG=/etc/default/rfid-reader
# shellcheck source=/dev/null
[ -f "$CONFIG" ] && . "$CONFIG"

: "${READER_VID:?READER_VID not set - run setup_rfid_reader.sh first}"
: "${READER_PID:?READER_PID not set - run setup_rfid_reader.sh first}"
REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
RESET_INTERVAL_MIN="${RESET_INTERVAL_MIN:-30}"   # 0 = no preventive resets
IDLE_SECONDS="${IDLE_SECONDS:-60}"
RESET_SCOPE="${RESET_SCOPE:-hub}"                # hub | port (see setup script)
MISSING_RETRY_MIN="${MISSING_RETRY_MIN:-5}"

STATE_DIR=/run/rfid-reader                       # tmpfs, cleared on boot
LOG_FILE="$REPO_DIR/rfid_reader_watchdog.log"
SCAN_LOG="$REPO_DIR/rfid_log.txt"
mkdir -p "$STATE_DIR"
now=$(date +%s)
# The Pi has no RTC, so the wall clock jumps when NTP syncs after boot. Reset
# timing uses uptime instead, which only ever moves forward.
uptime_s=$(cut -d. -f1 /proc/uptime)

log() {
    echo "$*"
    echo "$(date '+%F %T') $*" >> "$LOG_FILE"
}
read_state()  { cat "$STATE_DIR/$1" 2>/dev/null; }
write_state() { echo "$2" > "$STATE_DIR/$1"; }

# Prints the sysfs dir of the reader (e.g. /sys/bus/usb/devices/1-1.3).
find_device() {
    local d
    for d in /sys/bus/usb/devices/*; do
        [ -f "$d/idVendor" ] || continue
        if [ "$(cat "$d/idVendor")" = "$READER_VID" ] && [ "$(cat "$d/idProduct")" = "$READER_PID" ]; then
            echo "$d"
            return 0
        fi
    done
    return 1
}

wait_for_device() {
    local i
    for i in $(seq 1 "$1"); do
        find_device >/dev/null && return 0
        sleep 1
    done
    return 1
}

# True once the reader is back with a NEW USB device number, i.e. it really
# dropped off the bus. A command that "succeeded" without cutting power leaves
# the old number. $1 = old devnum (empty = any), $2 = seconds to wait
wait_for_reenumeration() {
    local i d
    for i in $(seq 1 "$2"); do
        d=$(find_device) && [ "$(cat "$d/devnum")" != "$1" ] && return 0
        sleep 1
    done
    return 1
}

check_power() {
    command -v vcgencmd >/dev/null || return 0
    local t
    t=$(vcgencmd get_throttled 2>/dev/null | cut -d= -f2)
    [ -n "$t" ] || return 0
    [ "$t" = "$(read_state throttled)" ] && return 0
    write_state throttled "$t"
    if (( t & 0x1 )); then
        log "POWER: under-voltage RIGHT NOW (throttled=$t) - Pi power supply is too weak"
    elif (( t & 0x10000 )); then
        log "POWER: under-voltage happened since boot (throttled=$t) - Pi power supply is too weak"
    elif [ "$t" != "0x0" ]; then
        log "POWER: throttled=$t"
    fi
}

# --- Reset methods (strongest first) ------------------------------------------

# Cut USB power to the reader with uhubctl and confirm it re-enumerated.
# $1 = sysfs name like 1-1.3, $2 = its devnum before the reset (may be empty)
# On the Pi's built-in ports power is ganged, so "hub" scope (all ports) is the
# only one that really cuts power; "port" only works through a hub with
# per-port switching.
power_cycle() {
    command -v uhubctl >/dev/null || return 1
    local name=$1 old=$2 hub port
    if [[ $name == *.* ]]; then
        hub=${name%.*};  port=${name##*.}
    else
        hub=${name%%-*}; port=${name#*-}
    fi
    if [ "$RESET_SCOPE" = port ]; then
        uhubctl -l "$hub" -p "$port" -a cycle -d 5 && wait_for_reenumeration "$old" 20
        return
    fi
    # Some models (e.g. Pi 3B+) put the ports behind a nested internal hub that
    # can't switch power; walk up the hub chain until a cycle actually works.
    while :; do
        if uhubctl -l "$hub" -a cycle -d 5 && wait_for_reenumeration "$old" 20; then
            return 0
        fi
        [[ $hub == *.* ]] || return 1
        hub=${hub%.*}
    done
}

# Leonardo "1200 baud touch": reboots the board if it exposes a serial port.
serial_reset() {
    local t
    for t in "$1"/*/tty/*; do
        [ -e "$t" ] || continue
        stty -F "/dev/$(basename "$t")" 1200 && return 0
    done
    return 1
}

# Re-enumerate on USB without cutting power (unsticks a hung USB link only).
reauthorize() {
    echo 0 > "$1/authorized" && sleep 2 && echo 1 > "$1/authorized"
}

reset_reader() {
    local dev=$1 reason=$2 name old=""
    write_state last_reset "$uptime_s"
    if [ -n "$dev" ]; then
        name=$(basename "$dev")
        old=$(cat "$dev/devnum")
    else
        name=$(read_state last_port)
    fi
    log "RESET ($reason) usb=${name:-unknown}"

    if [ -n "$name" ] && power_cycle "$name" "$old" >> "$LOG_FILE" 2>&1; then
        log "  power-cycled OK"
        return 0
    fi
    if [ -n "$dev" ] && [ -d "$dev" ] && serial_reset "$dev" && wait_for_reenumeration "$old" 20; then
        log "  rebooted via 1200-baud serial touch"
        return 0
    fi
    dev=$(find_device) || dev=""
    if [ -n "$dev" ] && reauthorize "$dev" && wait_for_device 10; then
        log "  re-enumerated on USB (no power cut)"
        return 0
    fi
    log "  all reset methods failed - check the cable, the USB port and power"
    return 1
}

# --- Main ---------------------------------------------------------------------

check_power

dev=$(find_device) || dev=""

if [ "${1:-}" = "--reset-now" ]; then
    reset_reader "$dev" "manual"
    exit $?
fi

last_reset=$(read_state last_reset)
if [ -z "$last_reset" ]; then
    last_reset=$uptime_s
    write_state last_reset "$uptime_s"
fi

if [ -z "$dev" ]; then
    if [ "$(read_state missing)" != 1 ]; then
        log "Reader $READER_VID:$READER_PID not found on USB"
        write_state missing 1
    fi
    if (( uptime_s - last_reset >= MISSING_RETRY_MIN * 60 )); then
        reset_reader "" "reader missing from USB"
    fi
    exit 0
fi

if [ "$(read_state missing)" = 1 ]; then
    log "Reader is back on USB at $(basename "$dev")"
    write_state missing 0
fi
write_state last_port "$(basename "$dev")"

# Belt and braces with the udev rule: never let the reader autosuspend.
if [ -w "$dev/power/control" ] && [ "$(cat "$dev/power/control")" != on ]; then
    echo on > "$dev/power/control"
    log "Turned USB autosuspend off for reader at $(basename "$dev")"
fi

if (( RESET_INTERVAL_MIN > 0 && uptime_s - last_reset >= RESET_INTERVAL_MIN * 60 )); then
    last_scan=$(stat -c %Y "$SCAN_LOG" 2>/dev/null || echo 0)
    if (( now - last_scan >= IDLE_SECONDS )); then
        reset_reader "$dev" "scheduled preventive reset"
    fi
fi
