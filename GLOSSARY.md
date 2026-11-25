# Bear Rentgen

A science-museum "X-ray" exhibit: a visitor presents a tagged object to the reader and the screen shows its X-ray for a moment before returning to the idle picture.

## Language

**Reader**:
The physical RFID unit attached to the Pi — a small Arduino board plus its MFRC522 RFID module and buzzer — treated as one device.
_Avoid_: Arduino, keyboard, scanner

**RFID Module**:
The MFRC522 board inside the Reader that actually talks to tags; distinct from the Arduino that drives it.
_Avoid_: Reader (when you mean only the module), antenna

**Card ID**:
The number a Reader reports for a tag it has read.
_Avoid_: NUID, UID, code

**Scan**:
One Card ID arriving from the Reader; the event that makes the exhibit show the Scan Result.
_Avoid_: Read, swipe

**Background**:
The idle picture shown while no Scan is being displayed.

**Scan Result**:
The X-ray picture shown for a fixed time after a Scan.
_Avoid_: X-ray screen, result image

## Reader self-care

**Health Check**:
The Reader asking its RFID Module to identify itself; a wrong or missing answer means the module is dead.
_Avoid_: Ping, heartbeat

**Module Reinit**:
The Reader restarting its RFID Module, either because a Health Check failed or as a periodic precaution.
_Avoid_: Reset (reserved for rebooting the whole Reader), reboot

**Reader Report**:
A message the Reader sends about itself (it booted, a Module Reinit succeeded or failed), as opposed to a Scan.
_Avoid_: L message, reader log, heartbeat
