"""
5090TempWatch - GPU Power Connector Temperature Monitoring System

This application monitors temperatures from multiple thermistors connected to GPU power connectors
via a microcontroller. It provides real-time temperature monitoring, logging, and safety features
including automatic shutdown if temperatures exceed safe thresholds.

Features:
- Real-time temperature monitoring via serial connection
- System tray icon with color-coded temperature display
- Automatic logging of temperature data and errors
- Watchdog monitoring for sensor system failures
- Text-to-speech alerts for critical issues
- Emergency shutdown capability for unsafe temperatures
"""

import tkinter as tk
from tkinter import ttk
import serial
import serial.tools.list_ports
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from collections import deque
import time
import datetime
import os
import threading
import subprocess
import sys
from pystray import Icon, Menu, MenuItem
from PIL import Image, ImageDraw, ImageFont
import io
from io import BytesIO
import pyttsx3
from tkinter import messagebox

# Global configuration
numberOfThermistors = 8  # Number of temperature sensors in the system
SERIAL_BAUDRATE = 115200   # Serial communication speed
LOG_FILE = "temp_log.txt"

class TemperatureMonitor:
    """
    Main application class for temperature monitoring system.
    Handles serial communication, data processing, UI, and safety features.
    """

    def __init__(self):
        """Initialize the temperature monitoring system and its components."""
        self.root = tk.Tk()
        self.root.title("Temperature Monitor")
        self.root.geometry("600x400")
        self.root.protocol("WM_DELETE_WINDOW", self.minimize_to_tray)

        # Temperature data storage (10 minutes = 600 seconds)
        self.max_points = 600
        self.temp_data = [deque(maxlen=self.max_points) for _ in range(numberOfThermistors)]
        self.timestamps = deque(maxlen=self.max_points)

        # Serial port
        self.serial_port = None
        self.baud_rate = SERIAL_BAUDRATE
        self.last_port = self.load_last_port()

        # Watchdog flag
        self.running = True

        # Add watchdog timer attributes
        self.last_data_time = time.time()
        self.watchdog_active = True
        self.watchdog_thread = threading.Thread(target=self.watchdog_monitor)
        self.watchdog_thread.daemon = True
        self.watchdog_thread.start()
        
        # Initialize text-to-speech engine
        self.tts_engine = pyttsx3.init()

        # Setup UI
        self.setup_graph()
        self.setup_tray()

        # Try to connect to last port first
        if self.last_port and self.try_connect_to_port(self.last_port):
            self.start_reading()
        else:
            self.show_port_selector()

    def try_connect_to_port(self, port):
        """
        Check if the specified port exists in the list of available ports.
        
        Args:
            port (str): The port to check
            
        Returns:
            bool: True if the port exists and can be connected to, False otherwise
        """
        # Check if port exists in available ports
        available_ports = [p.device for p in serial.tools.list_ports.comports()]
        if port not in available_ports:
            return False
        
        # Try to connect to the port
        try:
            self.serial_port = serial.Serial(port, self.baud_rate, timeout=1)
            return True
        except serial.SerialException:
            return False

    def setup_graph(self):
        """Set up the graph for temperature monitoring."""
        self.fig, self.ax = plt.subplots()
        self.lines = [self.ax.plot([], [], label=f'Temp {i}')[0] for i in range(numberOfThermistors)]
        self.ax.set_ylim(0, 120)  # Temp range 0-120C
        self.ax.set_xlim(0, self.max_points)
        self.ax.set_title("Temperature Readings (Last 10 Minutes)")
        self.ax.set_xlabel("Time (s)")
        self.ax.set_ylabel("Temperature (C)")
        self.ax.legend()

        self.canvas = FigureCanvasTkAgg(self.fig, master=self.root)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    def setup_tray(self):
        """Set up the system tray icon and its menu."""
        # Create a simple icon (red square for this example)
        image = Image.new('RGB', (64, 64), (255, 0, 0))
        self.tray_icon = Icon("TempMonitor", image, menu=Menu(
            MenuItem("Open", self.restore_from_tray),
            MenuItem("Quit", self.quit_app)
        ))
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def load_last_port(self):
        """Load the last used serial port from a file."""
        try:
            with open("last_port.txt", "r") as f:
                return f.read().strip()
        except FileNotFoundError:
            return None

    def save_last_port(self, port):
        """Save the last used serial port to a file."""
        with open("last_port.txt", "w") as f:
            f.write(port)

    def show_port_selector(self):
        """Show a port selection dialog to the user."""
        selector = tk.Toplevel(self.root)
        selector.title("Select Serial Port")
        selector.geometry("300x100")

        ports = [port.device for port in serial.tools.list_ports.comports()]
        port_var = tk.StringVar()

        if self.last_port in ports:
            port_var.set(self.last_port)
        elif ports:
            port_var.set(ports[0])

        ttk.Label(selector, text="Select Serial Port:").pack(pady=5)
        port_menu = ttk.Combobox(selector, textvariable=port_var, values=ports)
        port_menu.pack(pady=5)

        def connect():
            selected_port = port_var.get()
            try:
                self.serial_port = serial.Serial(selected_port, self.baud_rate, timeout=1)
                self.save_last_port(selected_port)
                selector.destroy()
                self.start_reading()
            except serial.SerialException:
                tk.messagebox.showerror("Error", "Could not open serial port")

        ttk.Button(selector, text="Connect", command=connect).pack(pady=5)
        selector.transient(self.root)
        selector.grab_set()

    def start_reading(self):
        """Start reading temperature data from the serial port."""
        self.read_thread = threading.Thread(target=self.read_serial, daemon=True)
        self.read_thread.start()
        self.update_graph()

    def create_temp_icon(self, temperature):
        """
        Create a system tray icon showing the current maximum temperature.
        
        Args:
            temperature (int): Temperature value to display
            
        Returns:
            PIL.Image: Generated icon image with temperature display
            
        The background color changes based on temperature thresholds:
        - Green: < 65°C
        - Yellow: 65-80°C
        - Red: > 80°C
        """
        # Create a new image with RGBA (including alpha channel)
        img = Image.new('RGBA', (32, 32), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        # Determine background color based on temperature
        if temperature < 65:
            bg_color = (0, 255, 0)  # Green
        elif temperature < 80:
            bg_color = (255, 255, 0)  # Yellow
        else:
            bg_color = (255, 0, 0)  # Red
        
        # Draw background rectangle
        draw.rectangle([0, 0, 31, 31], fill=bg_color)
        
        # Load a font that will fit in the icon
        try:
            font = ImageFont.truetype("arial.ttf", 16)
        except:
            font = ImageFont.load_default()
        
        # Convert temperature to string and ensure it's max 3 chars
        temp_str = str(min(999, max(-99, int(temperature))))
        
        # Calculate text size and position to center it
        text_bbox = draw.textbbox((0, 0), temp_str, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]
        x = (32 - text_width) // 2
        y = (32 - text_height) // 2
        
        # Draw the text in black
        draw.text((x, y), temp_str, fill=(0, 0, 0), font=font)
        
        # Convert to icon
        icon_buffer = BytesIO()
        img.save(icon_buffer, format='PNG')
        icon = Image.open(icon_buffer)
        return icon

    def read_serial(self):
        """
        Read and process temperature data from the serial port.
        Validates data format, updates displays, and handles error conditions.
        """
        while self.running:
            if self.serial_port and self.serial_port.is_open:
                try:
                    line = self.serial_port.readline().decode('utf-8').strip()
                    
                    # Update watchdog timer on any data reception
                    self.last_data_time = time.time()
                    self.watchdog_active = True  # Re-enable watchdog after receiving data
                    
                    # Validate basic packet format
                    if not line.startswith("Temp"):
                        error_msg = f"Malformed packet (invalid prefix): {line}"
                        print(error_msg)
                        with open(LOG_FILE, "a") as log:
                            log.write(f"{datetime.datetime.now()} - ERROR: {error_msg}\n")
                        continue

                    # Parse temperature number and value
                    try:
                        parts = line.split()
                        if len(parts) != 3:
                            raise ValueError("Invalid number of parts")
                        
                        temp_num = int(parts[1][:-1])
                        temp_value = int(parts[2][:-1])
                        
                        if temp_num < 0 or temp_num >= numberOfThermistors:
                            raise ValueError(f"Temperature number {temp_num} out of range")
                        
                        if temp_value < -20 or temp_value > 150:
                            raise ValueError(f"Temperature value {temp_value}C out of range")
                        
                        self.temp_data[temp_num].append(temp_value)
                        if not self.timestamps or time.time() - self.timestamps[-1] >= 1:
                            self.timestamps.append(time.time())

                        # Update the tray icon with the highest temperature
                        max_temp = max(max(data) if data else -999 for data in self.temp_data)
                        icon = self.create_temp_icon(max_temp)
                        self.tray_icon.icon = icon
                        
                        # Log the temperature
                        with open(LOG_FILE, "a") as log:
                            log.write(f"{datetime.datetime.now()} - Temp {temp_num}: {temp_value}C\n")

                        if temp_value > 100:
                            with open(LOG_FILE, "a") as log:
                                log.write(f"{datetime.datetime.now()} - Shutdown triggered: Temp {temp_num} exceeded 100C\n")
                            subprocess.run(["shutdown", "/s", "/t", "5"])
                            self.quit_app()
                            
                    except ValueError as ve:
                        error_msg = f"Malformed packet (parsing error): {line} - {str(ve)}"
                        print(error_msg)
                        with open(LOG_FILE, "a") as log:
                            log.write(f"{datetime.datetime.now()} - ERROR: {error_msg}\n")
                    
                except Exception as e:
                    error_msg = f"Serial read error: {str(e)}"
                    print(error_msg)
                    with open(LOG_FILE, "a") as log:
                        log.write(f"{datetime.datetime.now()} - ERROR: {error_msg}\n")
            
                time.sleep(0.1)

    def update_graph(self):
        """Update the temperature graph on the main window."""
        if self.running:
            for i, line in enumerate(self.lines):
                if self.temp_data[i]:
                    x_data = [t - self.timestamps[0] for t in list(self.timestamps)[:len(self.temp_data[i])]]
                    line.set_data(x_data, list(self.temp_data[i]))
            self.ax.set_xlim(0, max(self.max_points, len(self.timestamps)))
            self.canvas.draw()
            self.root.after(1000, self.update_graph)

    def watchdog_monitor(self):
        """
        Monitor for data reception timeouts.
        Triggers alerts if no data is received for 2.5 seconds.
        """
        while self.running:
            if self.watchdog_active and time.time() - self.last_data_time > 2.5:
                self.watchdog_active = False  # Prevent multiple alerts
                
                # Log the timeout
                error_msg = "No data received for 2.5 seconds - possible sensor system failure"
                print(error_msg)
                with open(LOG_FILE, "a") as log:
                    log.write(f"{datetime.datetime.now()} - ERROR: {error_msg}\n")
                
                # Show message box (in a separate thread to prevent blocking)
                threading.Thread(target=lambda: messagebox.showwarning(
                    "Sensor System Error",
                    "The thermal sensor system is not responding.\nPlease check all connections."
                )).start()
                
                # Text-to-speech alert
                threading.Thread(target=lambda: self.tts_engine.say(
                    "The NVidia GPU power connector thermal sensor is not operating correctly. Please check connections before continuing."
                ) or self.tts_engine.runAndWait()).start()
                
            time.sleep(0.1)

    def minimize_to_tray(self):
        """Minimize the main window to the system tray."""
        self.root.withdraw()

    def restore_from_tray(self, icon=None, item=None):
        """Restore the main window from the system tray."""
        self.root.deiconify()

    def quit_app(self, icon=None, item=None):
        """Clean up resources and exit the application."""
        self.running = False
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()
        if hasattr(self, 'tts_engine'):
            self.tts_engine.stop()
        self.tray_icon.stop()
        self.root.quit()
        sys.exit(0)

if __name__ == "__main__":
    # Check if running with admin privileges
    try:
        if not os.path.exists("C:\\Windows\\System32"):
            raise PermissionError
    except PermissionError:
        print("Please run as administrator for shutdown functionality")
        sys.exit(1)

    app = TemperatureMonitor()
    app.root.mainloop()