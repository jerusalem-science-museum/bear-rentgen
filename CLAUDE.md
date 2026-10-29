# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A science-museum "X-ray" (rentgen) kiosk for a Raspberry Pi. A USB RFID reader that emulates a keyboard types a card ID followed by Enter; the app appends the ID to `rfid_log.txt` and swaps the fullscreen `background.png` for `scan_result.png` for 15 seconds before reverting. Single-file Tkinter app, no tests, no build step. Code comments are partly in Hebrew.

## Running

```bash
pip install -r requirements.txt   # pillow, evdev (Linux only); tkinter comes from apt python3-tk on the Pi
python3 rentgen.py                # or ./run.sh, which cds into the repo first
```

- Opens fullscreen with the cursor hidden; press **Escape** to quit.
- Runs on Windows for UI testing (keyboard input works the same; type digits + Enter to simulate a scan). `rentgen_evdev.py` is Linux-only.

## Files and variants

- `rentgen.py` — **the active version** (launched by `run.sh` and `rfid_display.service`). Reads input via Tk `<KeyPress>` events, so it depends on the window keeping keyboard focus.
- `rentgen_evdev.py` — alternative that reads the reader directly from `/dev/input` via `evdev` in a background thread (no focus dependency). Picks the device by name ("rfid"/"reader"/"barcode", then "keyboard", then first device), only maps digit keys, and hands scans to the Tk thread with `root.after(0, ...)`. Needs read access to `/dev/input` (e.g. user in the `input` group).
- `rentgen_orig.py`, `rentgen_chat_old.py`, `*_old.png.png`, `*_orig.png.png`, `rfid_kiosk.py.txt` — earlier versions kept for reference; don't edit them unless asked.

## Architecture notes for `rentgen.py`

Everything runs on the Tk main loop via `root.after` timers — no threads:
- **Card buffering:** printable chars accumulate in `card_buffer`; Enter completes a scan. The buffer is discarded on a 2 s inter-key timeout (`CARD_INPUT_TIMEOUT`), on exceeding `MAX_CARD_LENGTH`, or when focus is regained (to drop half-typed input).
- **Focus recovery:** losing focus means lost scans, so `check_focus` (every 1 s) and `heartbeat` (every 5 s) call `request_focus()` (lift + `focus_force` + canvas `focus_set`). The canvas has `takefocus=1` for this reason.
- **Scan display:** a new scan while the result is showing restarts the 15 s timer (intentional, so a tag left on the reader can't lock the screen). `heartbeat` force-resets the display if it has been showing >20 s.
- **Logging:** two separate outputs — `rfid_log.txt` (plain append, one line per scan, the museum's data) and `rfid_diagnostics.log` (rotating 1 MB × 3; falls back to stderr only if the file can't be opened) for operational diagnostics including HEARTBEAT lines. `faulthandler` dumps tracebacks to `rfid_crash.log` on crash and on `SIGUSR1` (`kill -USR1 <pid>`) for diagnosing hangs.
- All paths resolve relative to the script directory (`BASE_DIR`), so the working directory doesn't matter. Images are resized to the screen resolution at startup.

## Deployment (Raspberry Pi)

- `setup_gui_rpi.sh` — one-shot provisioning: apt packages, AnyDesk (with unattended password), `.venv` + `requirements.txt`, forces X11 (not Wayland), desktop autologin, disables screen blanking, and creates `~/.config/autostart/kiosk.desktop` that runs `run.sh` in an lxterminal.
- `setup_rfid_reader.sh` (run once with sudo) + `rfid_reader_watchdog.sh` — the RFID reader is an off-the-shelf Arduino Leonardo (USB keyboard, firmware we can't change) that sometimes freezes (stops beeping). The setup disables USB autosuspend (cmdline + udev rule), writes `/etc/default/rfid-reader` (reader VID:PID, reset interval), and installs `rfid-reader-watchdog.timer`, which runs the watchdog every minute as root: logs under-voltage, power-cycles the reader with `uhubctl` if it vanishes from USB, and preventively every `RESET_INTERVAL_MIN` minutes when no scan happened in the last `IDLE_SECONDS`. Log: `rfid_reader_watchdog.log`.
- On the Pi the app runs with the global system `python3` (`run.sh`, the systemd unit); the `.venv` the setup script creates is intentionally unused at runtime.
- `rfid_display.service` — alternative systemd unit (user `rentgen`, `/home/rentgen/rentgen.py`, `DISPLAY=:0`, `Restart=always`). Its first line is missing the leading `[` of `[Unit]`.
- `Raspberry_Pi_RFID_Kiosk_Setup-v2.pdf` and `autorun a script in rasbery pi.docx` are setup guides.
