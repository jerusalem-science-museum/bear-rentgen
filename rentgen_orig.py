#!/usr/bin/env python3
import tkinter as tk
from PIL import Image, ImageTk
from datetime import datetime
import pygame  # Added for audio handling

# File paths configuration
BACKGROUND_IMAGE = "background.png"
SCAN_IMAGE = "scan_result.png"
SOUND_FILE = "beep.mp3"  # Can be an .mp3 or .wav file
LOG_FILE_PATH = "rfid_log.txt"
DISPLAY_TIME = 15000  # 15 seconds

class RFIDUsbApp:
    def __init__(self, root):
        self.root = root
        self.root.title("RFID USB Kiosk")
        
        # Save log filename to self so all functions can access it
        self.log_filename = LOG_FILE_PATH
        
        # Initialize the pygame mixer engine for sound playback
        pygame.mixer.init()
        try:
            self.scan_sound = pygame.mixer.Sound(SOUND_FILE)
        except Exception as e:
            print(f"Error loading sound file: {e}")
            self.scan_sound = None
        
        # Configure window to fullscreen mode
        self.root.attributes('-fullscreen', True)
        self.canvas = tk.Canvas(root, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        
        # Get screen metrics for automatic image scaling
        self.screen_width = self.root.winfo_screenwidth()
        self.screen_height = self.root.winfo_screenheight()
        
        # Load and scale images using PIL
        self.bg_image = self.load_and_resize(BACKGROUND_IMAGE)
        self.scan_image = self.load_and_resize(SCAN_IMAGE)
        self.image_on_canvas = self.canvas.create_image(0, 0, anchor="nw", image=self.bg_image)
        
        # State tracking variables
        self.card_buffer = ""
        self.is_showing_scan = False  # Track if scan_image is currently displayed
        self.timer_id = None  
        
        # Intercept keystrokes from the USB RFID reader
        self.root.bind("<Key>", self.on_key_press)

    def load_and_resize(self, image_path):
        """Loads an image and stretches it to match the exact screen size"""
        img = Image.open(image_path)
        img = img.resize((self.screen_width, self.screen_height), Image.Resampling.LANCZOS)
        return ImageTk.PhotoImage(img)

    def on_key_press(self, event):
        """Processes fast-typed inputs from the USB reader device"""
        if event.keysym == "Escape":
            self.root.destroy()
            return

        # GATEKEEPER: If scan image is showing, exit immediately.
        # This prevents any text tracking, logs, or sounds from executing.
        if self.is_showing_scan:
            return

        if event.keysym == "Return":
            if self.card_buffer:
                print(f"Card scanned: {self.card_buffer}")
                
                # Play the sound effect immediately upon successful card reading
                if self.scan_sound:
                    self.scan_sound.play()
                
                self.log_card_scan(self.card_buffer)
                self.show_scan_image()
                self.card_buffer = ""  # Reset buffer for next scan
        else:
            if event.char:
                self.card_buffer += event.char

    def log_card_scan(self, card_id):
        """Appends a new line with the timestamp and card number to a text file"""
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{current_time}] Scanned Card ID: {card_id}\n"
        try:
            with open(self.log_filename, "a", encoding="utf-8") as file:
                file.write(log_entry)
        except Exception as e:
            print(f"Logging error: {e}")

    def show_scan_image(self):
        """Switches display to the scan result image and handles the timer"""
        self.canvas.itemconfig(self.image_on_canvas, image=self.scan_image)
        self.is_showing_scan = True  # Disables input collection and sounds
        
        # Cancel any unexpected leftover timers
        if self.timer_id:
            self.root.after_cancel(self.timer_id)
            
        self.timer_id = self.root.after(DISPLAY_TIME, self.show_background_image)

    def show_background_image(self):
        """Reverts the screen back to the idle background image"""
        self.canvas.itemconfig(self.image_on_canvas, image=self.bg_image)
        self.is_showing_scan = False  # Re-enables input collection and sounds
        self.timer_id = None

if __name__ == "__main__":
    root = tk.Tk()
    app = RFIDUsbApp(root)
    
    # Hide the mouse cursor globally across the window right before starting
    root.config(cursor="none")
    
    root.mainloop()
