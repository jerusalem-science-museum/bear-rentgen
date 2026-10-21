#!/usr/bin/env python3
"""USB keyboard-emulating RFID kiosk for Raspberry Pi."""

import faulthandler
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import signal
import sys
import time
import tkinter as tk
from datetime import datetime

import pygame
from PIL import Image, ImageTk

BASE_DIR = Path(__file__).resolve().parent
BACKGROUND_IMAGE = BASE_DIR / "background.png"
SCAN_IMAGE = BASE_DIR / "scan_result.png"
SOUND_FILE = BASE_DIR / "beep.mp3"
LOG_FILE_PATH = BASE_DIR / "rfid_log.txt"  # Original card scan log
DIAGNOSTIC_LOG = BASE_DIR / "rfid_diagnostics.log"
DISPLAY_TIME = 15000  # milliseconds
HEARTBEAT_TIME = 5000  # milliseconds
CARD_INPUT_TIMEOUT = 2000  # milliseconds; clears incomplete scans
MAX_CARD_LENGTH = 128
FOCUS_RETRY_TIME = 1000  # milliseconds


def configure_logging():
    logger = logging.getLogger("rfid_kiosk")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    stream = logging.StreamHandler(sys.stderr)  # Visible through journalctl
    stream.setFormatter(formatter)
    logger.addHandler(stream)

    try:
        rotating = RotatingFileHandler(
            DIAGNOSTIC_LOG, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        rotating.setFormatter(formatter)
        logger.addHandler(rotating)
    except OSError as exc:
        logger.warning("Cannot open diagnostic log %s: %s", DIAGNOSTIC_LOG, exc)
    return logger


logger = configure_logging()

# Captures Python thread stacks when SIGUSR1 is sent to the running process.
# Keep stderr open; systemd normally records it in the service journal.
faulthandler.enable(file=sys.stderr)
if hasattr(signal, "SIGUSR1"):
    faulthandler.register(signal.SIGUSR1, file=sys.stderr, all_threads=True)


class RFIDUsbApp:
    def __init__(self, root):
        self.root = root
        self.root.title("RFID USB Kiosk")
        self.log_filename = LOG_FILE_PATH
        self.root.report_callback_exception = self.report_callback_exception

        # Sound is optional; an unavailable audio device must not stop the kiosk.
        self.scan_sound = None
        try:
            pygame.mixer.init()
            self.scan_sound = pygame.mixer.Sound(str(SOUND_FILE))
        except Exception:
            logger.exception("Audio initialization/sound loading failed; continuing silently")

        self.root.attributes("-fullscreen", True)
        self.canvas = tk.Canvas(root, highlightthickness=0, takefocus=1)
        self.canvas.pack(fill="both", expand=True)
        self.screen_width = self.root.winfo_screenwidth()
        self.screen_height = self.root.winfo_screenheight()

        self.bg_image = self.load_and_resize(BACKGROUND_IMAGE)
        self.scan_image = self.load_and_resize(SCAN_IMAGE)
        self.image_on_canvas = self.canvas.create_image(
            0, 0, anchor="nw", image=self.bg_image
        )

        self.card_buffer = ""
        self.card_timer_id = None
        self.is_showing_scan = False
        self.timer_id = None
        self.scan_display_started = None
        self.focus_missing = False

        # bind_all also sees keystrokes if focus is on a different widget in
        # THIS Tk application. It cannot intercept keys in another application.
        self.root.bind_all("<KeyPress>", self.on_key_press)
        self.root.bind("<FocusIn>", self.on_focus_in)
        self.root.bind("<FocusOut>", self.on_focus_out)
        self.root.after(FOCUS_RETRY_TIME, self.check_focus)
        self.root.after(HEARTBEAT_TIME, self.heartbeat)
        self.root.after(250, self.request_focus)
        logger.info("Kiosk started; display %sx%s", self.screen_width, self.screen_height)

    def report_callback_exception(self, exc_type, exc_value, exc_traceback):
        logger.error("Tkinter callback exception", exc_info=(exc_type, exc_value, exc_traceback))

    def load_and_resize(self, image_path):
        with Image.open(image_path) as img:
            resized = img.resize(
                (self.screen_width, self.screen_height), Image.Resampling.LANCZOS
            )
            return ImageTk.PhotoImage(resized)

    def request_focus(self):
        try:
            self.root.lift()
            self.root.focus_force()  # Intended for a dedicated full-screen kiosk
        except tk.TclError:
            logger.exception("Could not restore keyboard focus")

    def on_focus_in(self, _event):
        if self.focus_missing:
            logger.info("Keyboard focus restored")
            self.focus_missing = False

    def on_focus_out(self, _event):
        # FocusOut may occur when focus switches between Tk widgets.
        self.root.after(200, self.check_focus_once)

    def check_focus_once(self):
        if self.root.focus_displayof() is None and not self.focus_missing:
            self.focus_missing = True
            logger.warning("Keyboard focus lost; RFID input may be missed")

    def check_focus(self):
        try:
            if self.root.focus_displayof() is None:
                if not self.focus_missing:
                    self.focus_missing = True
                    logger.warning("Keyboard focus lost; attempting recovery")
                self.request_focus()
            elif self.focus_missing:
                self.focus_missing = False
                logger.info("Keyboard focus restored")
        finally:
            self.root.after(FOCUS_RETRY_TIME, self.check_focus)

    def reset_card_buffer(self, reason):
        if self.card_timer_id is not None:
            self.root.after_cancel(self.card_timer_id)
            self.card_timer_id = None
        if self.card_buffer:
            logger.warning("Discarding incomplete RFID input (%s, length=%d)",
                           reason, len(self.card_buffer))
        self.card_buffer = ""

    def card_input_expired(self):
        self.card_timer_id = None
        if self.card_buffer:
            logger.warning("Discarding incomplete RFID input after timeout (length=%d)",
                           len(self.card_buffer))
            self.card_buffer = ""

    def on_key_press(self, event):
        if event.keysym == "Escape":
            logger.info("Escape pressed; closing kiosk")
            self.root.destroy()
            return

        if self.is_showing_scan:
            return  # Preserve original: ignore scans during the 15-second screen

        if event.keysym in ("Return", "KP_Enter"):
            if not self.card_buffer:
                logger.debug("Enter received with an empty buffer")
                return
            card_id = self.card_buffer
            self.reset_card_buffer("completed scan")
            logger.info("RFID scan completed (length=%d)", len(card_id))
            if self.scan_sound is not None:
                try:
                    self.scan_sound.play()
                except Exception:
                    logger.exception("Could not play scan sound")
            self.log_card_scan(card_id)
            self.show_scan_image()
            return

        # Only collect printable characters; ignore Shift, Ctrl, etc.
        if event.char and event.char.isprintable():
            self.card_buffer += event.char
            if len(self.card_buffer) > MAX_CARD_LENGTH:
                self.reset_card_buffer("maximum card length exceeded")
                return
            if self.card_timer_id is not None:
                self.root.after_cancel(self.card_timer_id)
            self.card_timer_id = self.root.after(
                CARD_INPUT_TIMEOUT, self.card_input_expired
            )

    def log_card_scan(self, card_id):
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{current_time}] Scanned Card ID: {card_id}\n"
        try:
            with open(self.log_filename, "a", encoding="utf-8") as file:
                file.write(log_entry)
        except OSError:
            logger.exception("Failed to append card scan to %s", self.log_filename)

    def show_scan_image(self):
        logger.info("Displaying scan result for %d milliseconds", DISPLAY_TIME)
        self.canvas.itemconfig(self.image_on_canvas, image=self.scan_image)
        self.is_showing_scan = True
        self.scan_display_started = time.monotonic()
        if self.timer_id is not None:
            self.root.after_cancel(self.timer_id)
        self.timer_id = self.root.after(DISPLAY_TIME, self.show_background_image)

    def show_background_image(self):
        self.canvas.itemconfig(self.image_on_canvas, image=self.bg_image)
        self.is_showing_scan = False
        self.timer_id = None
        self.scan_display_started = None
        logger.info("Background image restored; ready for next scan")

    def heartbeat(self):
        scan_seconds = (
            round(time.monotonic() - self.scan_display_started, 1)
            if self.scan_display_started is not None else 0
        )
        logger.info("HEARTBEAT focus=%s showing_scan=%s scan_elapsed=%.1fs buffer_len=%d",
                    self.root.focus_displayof(), self.is_showing_scan,
                    scan_seconds, len(self.card_buffer))
        if self.is_showing_scan and scan_seconds > (DISPLAY_TIME / 1000) + 5:
            logger.warning("Scan image displayed longer than expected")
        self.root.after(HEARTBEAT_TIME, self.heartbeat)


if __name__ == "__main__":
    try:
        root = tk.Tk()
        root.config(cursor="none")
        app = RFIDUsbApp(root)
        root.mainloop()
    except Exception:
        logger.exception("Uncaught fatal error")
        raise
    finally:
        try:
            pygame.mixer.quit()
        except Exception:
            pass
