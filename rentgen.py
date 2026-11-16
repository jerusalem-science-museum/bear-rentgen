#!/usr/bin/env python3
"""Bear Rentgen exhibit: show the X-ray when the Reader sends a Scan.

See README.md for the design. Run with --debug to type reader lines into the
terminal (e.g. "S 1234") instead of using the real Reader.
"""

import argparse
import queue
import sys
import threading
import time
import tkinter as tk
import traceback
from datetime import datetime
from pathlib import Path

import serial
from PIL import Image, ImageTk
from serial.tools import list_ports

BASE_DIR = Path(__file__).resolve().parent
BACKGROUND_IMAGE = BASE_DIR / "background.png"
SCAN_IMAGE = BASE_DIR / "scan_result.png"
LOG_FILE = BASE_DIR / "rentgen.log"
SCAN_RESULT_MS = 7000
PORT_RETRY_S = 2
DEBUG_WINDOW = (960, 540)

log_to_file = True
log_lock = threading.Lock()


def log(kind, text):
    """Append one line to rentgen.log: timestamp, kind (SCAN/READER/INFO/ERROR), text."""
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {kind:<6} {text}\n"
    with log_lock:
        sys.stdout.write(line)
        sys.stdout.flush()
        if log_to_file:
            try:
                with open(LOG_FILE, "a", encoding="utf-8") as f:
                    f.write(line)
            except OSError as exc:
                sys.stderr.write(f"cannot write {LOG_FILE}: {exc}\n")


def log_exception(exc_type, exc, tb):
    log("ERROR", "".join(traceback.format_exception(exc_type, exc, tb)).rstrip())


def reader_lines():
    """Yield lines from the Reader forever, reconnecting whenever it disappears."""
    missing_logged = False
    while True:
        # Only one USB serial device is attached: the Reader.
        port = next((p.device for p in list_ports.comports() if p.vid is not None), None)
        if port is None:
            if not missing_logged:
                log("INFO", "reader not found, retrying")
                missing_logged = True
        else:
            missing_logged = False
            try:
                # The Reader's serial runs over native USB, so the baud rate is
                # ignored; just never use 1200, which reboots it into its bootloader.
                with serial.Serial(port, 9600) as conn:
                    log("INFO", f"reader connected on {port}")
                    for raw in conn:
                        yield raw.decode("ascii", "replace").strip()
            except (serial.SerialException, OSError) as exc:
                log("INFO", f"reader lost on {port}: {exc}")
        time.sleep(PORT_RETRY_S)


def terminal_lines():
    for line in sys.stdin:
        yield line.strip()


class Exhibit:
    def __init__(self, root, debug):
        self.root = root
        if debug:
            size = DEBUG_WINDOW
            root.geometry(f"{size[0]}x{size[1]}")
        else:
            size = (root.winfo_screenwidth(), root.winfo_screenheight())
            root.attributes("-fullscreen", True)
            root.config(cursor="none")
        self.background = self.load(BACKGROUND_IMAGE, size)
        self.scan_result = self.load(SCAN_IMAGE, size)
        self.screen = tk.Label(root, image=self.background, bd=0, bg="black")
        self.screen.pack(fill="both", expand=True)
        self.back_timer = None
        self.lines = queue.Queue()
        root.bind("<Escape>", lambda _e: root.destroy())

    @staticmethod
    def load(path, size):
        with Image.open(path) as img:
            return ImageTk.PhotoImage(img.resize(size, Image.Resampling.LANCZOS))

    def poll(self):
        """Handle lines queued by the reader thread (Tk is only touched here)."""
        while not self.lines.empty():
            self.handle(self.lines.get())
        self.root.after(50, self.poll)

    def handle(self, line):
        kind, _, rest = line.partition(" ")
        if kind == "S" and rest:
            log("SCAN", rest)
            self.show_scan_result()
        elif kind == "L":
            log("READER", rest)
        elif line:
            log("INFO", f"unknown line from reader: {line!r}")

    def show_scan_result(self):
        # A new Scan while the result is showing restarts the timer.
        self.screen.config(image=self.scan_result)
        if self.back_timer is not None:
            self.root.after_cancel(self.back_timer)
        self.back_timer = self.root.after(SCAN_RESULT_MS, self.show_background)

    def show_background(self):
        self.screen.config(image=self.background)
        self.back_timer = None


def main():
    global log_to_file
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--debug", action="store_true",
                        help="windowed; read reader lines from the terminal; don't write rentgen.log")
    args = parser.parse_args()
    log_to_file = not args.debug
    threading.excepthook = lambda a: log_exception(a.exc_type, a.exc_value, a.exc_traceback)

    root = tk.Tk()
    root.title("Bear Rentgen")
    root.report_callback_exception = log_exception
    exhibit = Exhibit(root, args.debug)

    def pump(source):
        for line in source():
            exhibit.lines.put(line)

    source = terminal_lines if args.debug else reader_lines
    threading.Thread(target=pump, args=(source,), daemon=True).start()
    exhibit.poll()

    log("INFO", "started" + (" (debug)" if args.debug else ""))
    try:
        root.mainloop()
    except Exception:
        log_exception(*sys.exc_info())
        raise
    log("INFO", "stopped")


if __name__ == "__main__":
    main()
