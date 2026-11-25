# RFID Reader: Lessons Learned

Last updated: 2026-11-25

## Context

Most of the bear X-ray exhibit's downtime came from the RFID reader, not from the app. The reader is a Pro Micro (ATmega32U4) driving an MFRC522 module and a buzzer, plugged into a Raspberry Pi over USB. Between 21 Oct and 16 Nov 2026 it went from a USB-keyboard reader with a Pi-side power-cycling watchdog to a USB-serial reader that looks after itself.

The usual failure: the Arduino kept running but the RFID module went deaf, so tags stopped beeping and nothing reached the screen.

## Hardware lessons

1. **Build the reader on a proper perfboard, never loose jumpers.** Keep the schematic and board source in the repo (`reader/schematics.pdf`, `reader/easyeda/`). [see for example](https://github.com/jerusalem-science-museum/bear-rentgen/tree/main/reader)
2. **Use a good power supply for the Pi, and so for the reader.** The reader draws its power from the Pi's USB port, so a weak Pi supply starves the MFRC522 too. Rule out power first, before debugging code. On the Pi, `vcgencmd get_throttled` shows past under-voltage: anything other than `0x0` means the supply is too weak.

nice to haves:

3. **Give the module clean 3.3 V and clean logic levels.** The MFRC522 is a 3.3 V part. Ours has a 5→3.3 V regulator, but its SPI inputs are still driven at 5 V straight from the Pro Micro. seems like it works but the "correct" way is to drive everything with 3.3V.
4. **Wire the module's RST pin to a spare GPIO.** Ours is tied to the Pro Micro's RST, so the firmware can only soft-reset the module. A hard reset is the strongest fix for a deaf module, and we can't do it without a GPIO.
5. **Test the watchdog on every new Pro Micro.** Some old bootloaders hang after a watchdog reset instead of rebooting. Add `while (1);` at the top of `loop()` once and check that `L boot` comes back about every 4 s.

## Software lessons (see [rentgen](https://github.com/jerusalem-science-museum/bear-rentgen) as example)

1. **In a GUI app, have the reader talk USB serial, not act as a keyboard.** Keyboard input only reaches the window that has focus. In the old diagnostics log, 5,354 of 6,199 heartbeats show focus on the root window instead of the canvas that listened for keys. That code needed focus checks, a 2 s buffer timeout, and buffer resets every time focus came back. Over serial the app just reads `S <id>` lines, whatever window is on top.
2. **Use a tiny line protocol with a type prefix.** `S <card id>` for a Scan and `L <text>` for a Reader Report keep scans and diagnostics on one cable, and both are easy to fake from a terminal (`--debug`).
3. **On the AVR, `int` is 16 bits.** Cast each UID byte to `uint32_t` before shifting it into the 32-bit Card ID, or the top bytes are lost.
4. **Expect anything sent before the Pi opens the port to be lost.** The firmware holds its boot report until `Serial` is true, and never blocks waiting for the host.

## Other things we discovered

note - on some exhibits there were no problems (specifically the space rfid exhibit). so you might not need this rabbit hole at all.

1. **The reader should heal itself, not the Pi.** Power-cycling the reader from the Pi (uhubctl, a systemd timer, ~200 lines of shell) was fragile. On the Pi's built-in ports power is ganged, so you can only cut all ports at once. Some models (e.g. Pi 3B+) have a nested hub that can't switch power at all. A reset also took ~10 s.
2. **Check the module, not just the Arduino.** The module can go deaf while the Arduino runs fine. The firmware now reads the module's version register every 5 s (`0x00`/`0xFF` = dead), reinits it up to 3 times on failure, and reinits it every 10 min anyway. A reinit takes ~50 ms, so visitors don't notice.
3. **Add a hardware watchdog, but keep uploads working.** A 4 s `wdt` reboots the board if the firmware stalls. But arduino-cli starts an upload with a 1200-baud "touch" that arms a short watchdog reset into the bootloader. Petting the watchdog then cancels it and breaks uploads, so the firmware skips `wdt_reset()` at 1200 baud.
4. **Add a scan cooldown.** A tag at the edge of the field, or next to another tag, was read over and over. A cooldown after each Scan fixed it (400 ms first, now 1000 ms), together with `PICC_HaltA()` so a tag is not read again until it is lifted.
5. **Make the reader's reports a liveness trace.** Every periodic reinit writes a `READER reinit` line to `rentgen.log`. A gap of more than 10 min means the reader was silent.
6. **Use one append-only log.** Several rotating logs, a crash log and a scan log were hard to read. One line per event in `rentgen.log`, never rotated, is about 5 MB a year and countable with `grep`.
7. **Quit the app before flashing.** The app holds the serial port, so uploads fail while it runs (Escape first).

## Board choice for next time

| Where the module is | What to build | Why |
| --- | --- | --- |
| Far from the Pi (the bear: module in the claw, Pi in a separate box by the screen) | Microcontroller on the perfboard next to the module; one long USB cable to the Pi | SPI is only good for a few tens of cm and picks up noise on long wires. USB is designed for the long run. |
| In the same box as the Pi, a short reach away | The same reader still works best. Wiring the MFRC522 straight to the Pi's SPI pins is possible. | Direct SPI saves a board, but the Pi app then has to do the health checks and reinits, and a stuck module can't be fixed by rebooting the reader alone. |

## Checklist for the next RFID exhibit

- [ ] Reader soldered on perfboard; schematic committed with the code
- [ ] Official-rated Pi power supply; `vcgencmd get_throttled` reads `0x0` after a day of running
- [ ] Reader speaks USB serial with `S` / `L` lines, not keyboard
- [ ] Firmware: health check, periodic reinit, scan cooldown, hardware watchdog that skips 1200 baud
- [ ] Watchdog tested once on the actual board
- [ ] App tested with `--debug` before it goes on the Pi
