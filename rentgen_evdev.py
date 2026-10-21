#!/usr/bin/env python3
"""USB RFID kiosk for Raspberry Pi - Fixed Direct Hardware Mode."""

import faulthandler
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import signal
import sys
import time
import threading
import tkinter as tk
from datetime import datetime

import pygame
from PIL import Image, ImageTk
import evdev
from evdev import InputDevice, ecodes

BASE_DIR = Path(__file__).resolve().parent
BACKGROUND_IMAGE = BASE_DIR / "background.png"
SCAN_IMAGE = BASE_DIR / "scan_result.png"
SOUND_FILE = BASE_DIR / "beep.mp3"
LOG_FILE_PATH = BASE_DIR / "rfid_log.txt"  
DIAGNOSTIC_LOG = BASE_DIR / "rfid_diagnostics.log"
DISPLAY_TIME = 15000  # milliseconds
HEARTBEAT_TIME = 5000  # milliseconds
MAX_CARD_LENGTH = 128

# מפת תרגום מקשים מלינוקס לתווים (תומך במספרים עליונים ובפאד המספרים בצד)
KEY_MAP = {
    ecodes.KEY_1: "1", ecodes.KEY_2: "2", ecodes.KEY_3: "3", ecodes.KEY_4: "4", ecodes.KEY_5: "5",
    ecodes.KEY_6: "6", ecodes.KEY_7: "7", ecodes.KEY_8: "8", ecodes.KEY_9: "9", ecodes.KEY_0: "0",
    ecodes.KEY_KP1: "1", ecodes.KEY_KP2: "2", ecodes.KEY_KP3: "3", ecodes.KEY_KP4: "4", ecodes.KEY_KP5: "5",
    ecodes.KEY_KP6: "6", ecodes.KEY_KP7: "7", ecodes.KEY_KP8: "8", ecodes.KEY_KP9: "9", ecodes.KEY_KP0: "0"
}


def configure_logging():
    logger = logging.getLogger("rfid_kiosk")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    stream = logging.StreamHandler(sys.stderr)
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
faulthandler.enable(file=sys.stderr)


class RFIDUsbApp:
    def __init__(self, root):
        self.root = root
        self.root.title("RFID USB Kiosk")
        self.log_filename = LOG_FILE_PATH
        self.root.report_callback_exception = self.report_callback_exception

        self.scan_sound = None
        try:
            pygame.mixer.init()
            self.scan_sound = pygame.mixer.Sound(str(SOUND_FILE))
        except Exception:
            logger.exception("Audio initialization/sound loading failed; continuing silently")

        self.root.attributes("-fullscreen", True)
        self.canvas = tk.Canvas(root, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.screen_width = self.root.winfo_screenwidth()
        self.screen_height = self.root.winfo_screenheight()

        self.bg_image = self.load_and_resize(BACKGROUND_IMAGE)
        self.scan_image = self.load_and_resize(SCAN_IMAGE)
        self.image_on_canvas = self.canvas.create_image(
            0, 0, anchor="nw", image=self.bg_image
        )

        self.is_showing_scan = False
        self.timer_id = None
        self.scan_display_started = None
        self.running = True

        # יציאה מהתוכנה בלחיצה על Escape
        self.root.bind_all("<Escape>", lambda e: self.close_kiosk())

        # הפעלת קורא החומרה ברקע
        self.rfid_thread = threading.Thread(target=self.hardware_rfid_listener, daemon=True)
        self.rfid_thread.start()

        self.root.after(HEARTBEAT_TIME, self.heartbeat)
        logger.info("Kiosk started in Hardware Mode; display %sx%s", self.screen_width, self.screen_height)

    def report_callback_exception(self, exc_type, exc_value, exc_traceback):
        logger.error("Tkinter callback exception", exc_info=(exc_type, exc_value, exc_traceback))

    def load_and_resize(self, image_path):
        with Image.open(image_path) as img:
            resized = img.resize(
                (self.screen_width, self.screen_height), Image.Resampling.LANCZOS
            )
            return ImageTk.PhotoImage(resized)

    def find_rfid_device(self):
        """מחפש באופן אוטומטי את קורא ה-RFID מתוך רשימת התקני הקלט בלינוקס"""
        try:
            devices = [InputDevice(path) for path in evdev.list_devices()]
            if not devices:
                return None
            
            # עדיפות ראשונה: התקנים עם שמות מובהקים
            for device in devices:
                name = device.name.lower()
                if "rfid" in name or "reader" in name or "barcode" in name:
                    logger.info("Matched RFID device by name: %s at %s", device.name, device.path)
                    return device.path
            
            # עדיפות שנייה: מקלדות USB חיצוניות (שזה מה שקורא RFID מדמה)
            for device in devices:
                if "keyboard" in device.name.lower():
                    logger.info("Matched RFID device by keyboard emulation: %s at %s", device.name, device.path)
                    return device.path
                    
            # מוצא אחרון: קח את התקן הקלט הראשון הזמין
            logger.info("Using fallback first available input device: %s", devices[0].name)
            return devices[0].path
        except Exception as e:
            logger.error("Error listing input devices: %s", e)
            return None

    def hardware_rfid_listener(self):
        """לולאת רקע חסינה שקוראת מה-USB דרך הקרנל של לינוקס"""
        buffer = ""
        while self.running:
            device_path = self.find_rfid_device()
            if not device_path:
                logger.warning("RFID reader device not found. Retrying in 3 seconds...")
                time.sleep(3)
                continue

            try:
                device = InputDevice(device_path)
                logger.info("Successfully bound to hardware: %s (%s)", device.name, device.path)
                
                for event in device.read_loop():
                    if not self.running:
                        break
                    
                    if event.type == ecodes.EV_KEY:
                        key_event = evdev.categorize(event)
                        if key_event.keystate == 1:  # Key Press בלבד (בלי שחרור מקש)
                            
                            # אם לחצו אנטר - סימן שהסריקה הסתיימה
                            if key_event.scancode in (ecodes.KEY_ENTER, ecodes.KEY_KPENTER):
                                if buffer:
                                    card_id = buffer
                                    buffer = ""
                                    logger.info("Hardware RFID tag detected: %s", card_id)
                                    
                                    # שליחה בטוחה ל-Thread הראשי באמצעות .after
                                    self.root.after(0, self.process_valid_scan, card_id)
                            
                            # הוספת תווים מזהים לבאפר
                            elif key_event.scancode in KEY_MAP:
                                buffer += KEY_MAP[key_event.scancode]
                                if len(buffer) > MAX_CARD_LENGTH:
                                    buffer = ""
                                    
            except Exception as e:
                logger.error("Hardware disconnected or read error: %s. Reconnecting in 2 seconds...", e)
                buffer = ""
                time.sleep(2)

    def process_valid_scan(self, card_id):
        """פונקציה זו רצה בתוך ה-Thread הגרפי הראשי ולכן היא תתניע את המסכים"""
        if self.scan_sound is not None:
            try:
                self.scan_sound.play()
            except Exception:
                logger.exception("Could not play scan sound")
        self.log_card_scan(card_id)
        self.show_scan_image()

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
        logger.info("HEARTBEAT hardware_mode=True showing_scan=%s scan_elapsed=%.1fs",
                    self.is_showing_scan, scan_seconds)
        
        if self.is_showing_scan and scan_seconds > (DISPLAY_TIME / 1000) + 5:
            logger.warning("Scan image displayed longer than expected - forcing reset")
            self.show_background_image()
            
        self.root.after(HEARTBEAT_TIME, self.heartbeat)

    def close_kiosk(self):
        logger.info("Closing kiosk")
        self.running = False
        self.root.destroy()


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
