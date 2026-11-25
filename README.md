# Bear Rentgen

A science-museum "X-ray" exhibit. A visitor holds a tagged object to the reader; the screen swaps its idle picture (`background.png`) for the X-ray (`scan_result.png`) for 15 seconds, then goes back.

Terms used here (Reader, Scan, Health Check, Module Reinit, Reader Report, ...) are defined in [GLOSSARY.md](GLOSSARY.md).

## Quick setup (Raspberry Pi)

On a fresh Raspberry Pi OS with internet:

```bash
git clone https://github.com/jerusalem-science-museum/bear-rentgen.git
cd bear-rentgen
./setup_gui_rpi.sh            # venv, serial access, AnyDesk, autologin, autostart (asks for an AnyDesk password)
./setup_arduino_cli.sh        # only if you'll flash the Reader from the Pi (see below)
sudo reboot
```

Plug the Reader into the Pi's USB. After the reboot the app starts fullscreen; tap a tag to check.

**Flashing:** skip this (and `setup_arduino_cli.sh`) if the Reader was flashed beforehand, e.g. from a PC with the Arduino IDE. Otherwise, after the reboot press Escape to quit the app (it holds the serial port), then in a terminal:

```bash
cd bear-rentgen
ac reader                     # compile + upload to /dev/ttyACM0
sudo reboot
```

Details: [Raspberry Pi setup](#raspberry-pi-setup) and [Flashing the Reader](#flashing-the-reader).

## Hardware

```
MFRC522 RFID module ──SPI── Pro Micro (ATmega32U4) ──USB── Raspberry Pi ──HDMI── screen
                            └── buzzer (pin 7)
```

- **Reader**: a Pro Micro running [reader/reader.ino](reader/reader.ino), with an MFRC522 module and a buzzer. Wiring: [reader/schematics.pdf](reader/schematics.pdf) (EasyEDA source in [reader/easyeda/](reader/easyeda/)).
- The module is powered from a 5→3.3 V regulator. Its SPI inputs are driven straight from the 5 V Pro Micro, and its RST pin is tied to the Pro Micro's RST, so the firmware can only soft-reset it. A future board revision should add level shifting and route the module's RST to a spare GPIO.
- **Pi**: runs [rentgen.py](rentgen.py) fullscreen on the desktop.

## Reader → Pi protocol

The Reader is a USB serial device (not a keyboard). It sends plain text lines:

| Line | Meaning |
|------|---------|
| `S <card id>` | A Scan. The Card ID is the tag's first 4 UID bytes as one decimal number. |
| `L <text>` | A Reader Report, e.g. `L boot module=ok version=0x92` or `L reinit reason=periodic before=0x92 result=ok attempts=1 version=0x92`. |

Anything sent while the Pi doesn't have the port open is lost; the Reader never waits for the Pi.

After a Scan the Reader doesn't look for tags for 400 ms (`SCAN_COOLDOWN_MS`), so a tag at the edge of the field, or next to another tag, isn't re-read over and over.

## How the Reader looks after itself

The weak point is the RFID module, which can go deaf while the Arduino keeps running. The firmware handles that on its own:

- **Health Check every 5 s**: reads the module's version register; `0x00`/`0xFF` means it isn't answering. On failure it does a Module Reinit (up to 3 attempts) and sends a Reader Report with the result.
- **Periodic Module Reinit every 10 min**, also reported. This covers a module that still answers the Health Check but has stopped detecting tags. A reinit takes ~50 ms and only happens between reads, so visitors don't notice. Side effect: a tag left lying on the reader may be scanned again at that moment.
- **Hardware watchdog**: if the firmware ever stalls for 4 s, the chip reboots itself and sends `L boot ...` once the Pi has the port open.

The Pi does not monitor or reset the Reader. The periodic reinit reports double as a liveness trace: a gap of more than 10 minutes between `READER reinit` lines in the log means the Reader was silent.

## The app

[rentgen.py](rentgen.py), one small file:

- Fullscreen, cursor hidden, **Escape** quits.
- Finds the Reader as the only USB serial port; if it disappears, logs it and retries every 2 s.
- On a Scan: shows the X-ray for 15 s. A new Scan during that time restarts the 15 s.
- Writes everything to **`rentgen.log`** (appended forever, never rotated or overwritten; about 5 MB a year). One line per event:

  ```
  2026-11-16 12:00:03 SCAN   1234567890
  2026-11-16 12:10:00 READER reinit reason=periodic before=0x92 result=ok attempts=1 version=0x92
  2026-11-16 12:10:05 INFO   reader lost on /dev/ttyACM0: ...
  2026-11-16 12:10:07 ERROR  <traceback>
  ```

  To count visits: `grep -c ' SCAN ' rentgen.log`. To archive, rename the file; the app starts a new one.

## Running

```bash
pip install -r requirements.txt
python3 rentgen.py            # real Reader on USB
python3 rentgen.py --debug    # no Reader needed
```

`--debug` opens a normal window, shows the cursor, and reads Reader lines from the terminal instead of USB: type `S 1234` and Enter to fake a Scan, `L anything` for a Reader Report. Debug runs log to the terminal only, never to `rentgen.log`.

## Flashing the Reader

1. Arduino IDE → Library Manager → install **MFRC522** (by GithubCommunity), version 1.4 or newer.
2. Open [reader/reader.ino](reader/reader.ino), board **SparkFun Pro Micro, ATmega32U4 (5V, 16 MHz)** (add SparkFun's board package URL `https://raw.githubusercontent.com/sparkfun/Arduino_Boards/main/IDE_Board_Manager/package_sparkfun_index.json` in Preferences, then install **SparkFun AVR Boards**), upload.
3. Check: Arduino serial monitor shows `L boot module=ok version=0x..` and `S <id>` when you tap a tag.
4. Once per new board, test the watchdog: temporarily add `while (1);` at the top of `loop()`, upload, and confirm the board reboots (a new `L boot` line about every 4 s). Some old Pro Micro bootloaders hang after a watchdog reset instead.

### From the Pi

Run `./setup_arduino_cli.sh` once: it installs `arduino-cli`, the `arduino:avr` core (compiler + avrdude), SparkFun's Pro Micro board package and the MFRC522 and Keyboard libraries, and adds an `ac` alias to `~/.bashrc` for `arduino-cli compile --upload -v -b SparkFun:avr:promicro:cpu=16MHzatmega32U4 -p /dev/ttyACM0`. Then quit the app (Escape, it holds the port) and, from the repo folder:

```bash
arduino-cli board list                                                       # find the port
ac reader                                                                    # compile + upload the reader/ sketch (open a new terminal after setup)
arduino-cli monitor -p /dev/ttyACM0                                          # expect "L boot module=ok ...", then "S <id>" per tag; Ctrl+C exits
```

## Raspberry Pi setup

On a fresh Raspberry Pi OS, from the cloned repo:

```bash
./setup_gui_rpi.sh
sudo reboot
```

It creates `.venv` with the packages from `requirements.txt` ([run.sh](run.sh) runs the app with `.venv/bin/python`), installs `python3-tk` from apt, adds the user to `dialout` (needed to open the serial port), installs AnyDesk, forces X11, enables desktop autologin, disables screen blanking, and autostarts [run.sh](run.sh) in a terminal window. Setup guides with screenshots: `Raspberry_Pi_RFID_Kiosk_Setup-v2.pdf`, `autorun a script in rasbery pi.docx`.
