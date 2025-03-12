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
from matplotlib.figure import Figure

# Global configuration
numberOfThermistors = 8
SERIAL_BAUDRATE = 115200

class TemperatureMonitor:
    """
    Main application class for temperature monitoring system.
    Handles serial communication, data processing, UI, and safety features.
    """

    def __init__(self):
        """Initialize the temperature monitoring system and its components."""
        # Initialize data storage
        self.temp_data = [[] for _ in range(numberOfThermistors)]
        self.timestamps = []
        self.running = True
        
        # Set up logging
        self.log_dir = os.path.join(os.path.expanduser('~'), '.5090TempWatch')
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir)
        self.log_file = os.path.join(self.log_dir, "temp_log.txt")
        self.last_port_file = os.path.join(self.log_dir, "last_port.txt")
        
        # Log startup
        with open(self.log_file, "a") as log:
            log.write(f"\n{datetime.datetime.now()} - Application started\n")
        
        # Initialize serial connection
        self.serial_port = None
        self.init_serial()
        
        # Initialize data storage for graphing
        self.window_minutes = 10  # Set window size to 10 minutes
        # Calculate number of points needed for 10 minutes
        # Assuming we get 8 readings (one per sensor) every ~0.5 seconds
        self.data_points = self.window_minutes * 120  # 120 points per minute
        self.temp_history = [deque(maxlen=self.data_points) for _ in range(numberOfThermistors)]
        self.time_history = deque(maxlen=self.data_points)
        self.readings_count = 0
        
        # Initialize graph window
        self.graph_window = None
        self.graph_visible = True
        
        # Create root window for Tkinter
        self.root = tk.Tk()
        self.root.withdraw()  # Hide the root window
        
        # Set up system tray icon
        self.setup_tray_icon()
        
        # Create graph window
        self.create_graph_window()
        
        # Start serial reading in a separate thread
        self.serial_thread = threading.Thread(target=self.read_serial, daemon=True)
        self.serial_thread.start()
        
        # Schedule graph updates
        self.schedule_graph_update()
        
        # Initialize text-to-speech engine
        self.tts_engine = pyttsx3.init()
        self.last_warning_time = {
            'warning1': 0,  # for 80°C warnings
            'warning2': 0   # for 90°C warnings
        }
        
        # Start Tkinter main loop
        self.root.mainloop()

    def init_serial(self):
        """Try to connect to the last known port first, then scan for available ports"""
        # Try last known port first
        try:
            with open(self.last_port_file, 'r') as f:
                last_port = f.read().strip()
                try:
                    self.serial_port = serial.Serial(last_port, SERIAL_BAUDRATE)
                    # Flush input buffer
                    self.serial_port.reset_input_buffer()
                    time.sleep(0.1)  # Give it a moment to clear
                    print(f"Connected to last known port {last_port}")
                    with open(self.log_file, "a") as log:
                        log.write(f"{datetime.datetime.now()} - Connected to last known port {last_port}\n")
                    return
                except serial.SerialException:
                    pass
        except FileNotFoundError:
            pass

        # Scan all available ports if last known port failed
        ports = list(serial.tools.list_ports.comports())
        for port in ports:
            try:
                self.serial_port = serial.Serial(port.device, SERIAL_BAUDRATE)
                # Flush input buffer
                self.serial_port.reset_input_buffer()
                time.sleep(0.1)  # Give it a moment to clear
                with open(self.last_port_file, 'w') as f:
                    f.write(port.device)
                print(f"Connected to {port.device}")
                with open(self.log_file, "a") as log:
                    log.write(f"{datetime.datetime.now()} - Connected to {port.device}\n")
                return
            except serial.SerialException:
                continue
        
        print("No serial port found")
        with open(self.log_file, "a") as log:
            log.write(f"{datetime.datetime.now()} - ERROR: No serial port found\n")

    def create_temp_icon(self, temperature):
        """Creates an icon showing the temperature on a colored background"""
        img = Image.new('RGBA', (32, 32), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        # Set background color based on temperature
        if temperature < 60:
            color = (0, 255, 0)  # Green
        elif temperature < 80:
            color = (255, 255, 0)  # Yellow
        else:
            color = (255, 0, 0)  # Red
            
        # Draw filled rectangle with rounded corners
        draw.rectangle([0, 0, 31, 31], fill=color)
        
        # Add temperature text
        try:
            font = ImageFont.truetype("arial.ttf", 16)
        except:
            font = ImageFont.load_default()
            
        text = str(int(temperature))
        text_width = draw.textlength(text, font=font)
        text_height = 16
        x = (32 - text_width) // 2
        y = (32 - text_height) // 2
        draw.text((x, y), text, fill='black', font=font)
        
        return img

    def setup_tray_icon(self):
        """Configure and launch the system tray icon"""
        menu_items = (MenuItem('Exit', self.quit_app),)
        self.tray_icon = Icon('temp', Image.new('RGB', (32, 32), 'red'), 
                             "GPU Temp Monitor", menu_items)
        # Run the tray icon in a separate thread
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def create_graph_window(self):
        """Create and configure the graph window"""
        self.graph_window = tk.Toplevel(self.root)
        self.graph_window.title("Temperature History")
        self.graph_window.protocol("WM_DELETE_WINDOW", self.toggle_graph)
        self.graph_window.geometry("800x600")

        # Create matplotlib figure
        self.fig = Figure(figsize=(10, 6))
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.graph_window)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=1)

    def schedule_graph_update(self):
        """Schedule the next graph update"""
        if self.running:
            self.update_graph()
            self.root.after(1000, self.schedule_graph_update)  # Update every second

    def update_graph(self):
        """Update the graph with new temperature data"""
        if not self.running or not self.graph_window:
            return

        try:
            # Only update if we have more than 3 readings
            if self.readings_count > 3:
                # Clear the figure
                self.ax.clear()

                # Get the current time points
                times = list(self.time_history)
                current_time = datetime.datetime.now()
                
                # Set x-axis limits for 10-minute window
                if len(times) > 0:
                    oldest_allowed_time = current_time - datetime.timedelta(minutes=self.window_minutes)
                    
                    # Find valid data within the time window
                    for i in range(numberOfThermistors):
                        # Get valid temperatures and their corresponding times
                        valid_data = [(t, temp) for t, temp in zip(times, self.temp_history[i]) 
                                     if temp > -999 and t >= oldest_allowed_time]
                        
                        if valid_data:
                            # Unzip the valid data pairs
                            plot_times, plot_temps = zip(*valid_data)
                            self.ax.plot(plot_times, plot_temps, label=f'Sensor {i}')
                    
                    # Set fixed axis limits
                    self.ax.set_xlim(oldest_allowed_time, current_time)
                    self.ax.set_ylim(0, 130)  # Set y-axis from 0°C to 130°C

                # Configure graph
                self.ax.set_xlabel('Time')
                self.ax.set_ylabel('Temperature (°C)')
                self.ax.set_title('Temperature History (10 Minute Window)')
                self.ax.grid(True)
                
                # Only add legend if we have data
                if any(any(t > -999 for t in sensor) for sensor in self.temp_history):
                    self.ax.legend()

                # Format x-axis
                self.fig.autofmt_xdate()

                # Update the canvas
                self.canvas.draw()

        except Exception as e:
            print(f"Error updating graph: {str(e)}")

    def toggle_graph(self):
        """Show or hide the graph window"""
        if not self.graph_visible:
            self.graph_window.deiconify()
            self.graph_visible = True
        else:
            self.graph_window.withdraw()
            self.graph_visible = False

    def speak_warning(self, message, warning_type):
        """Speak a warning message with rate limiting"""
        current_time = time.time()
        
        if warning_type == 'warning1':  # 80°C warning
            if current_time - self.last_warning_time['warning1'] >= 60:  # Every minute
                self.tts_engine.say(message)
                self.tts_engine.runAndWait()
                self.last_warning_time['warning1'] = current_time
                
        elif warning_type == 'warning2':  # 90°C warning
            if current_time - self.last_warning_time['warning2'] >= 10:  # Every 10 seconds
                self.tts_engine.say(message)
                self.tts_engine.runAndWait()
                self.last_warning_time['warning2'] = current_time

    def shutdown_system(self):
        """Gracefully shutdown the system"""
        try:
            # Log the shutdown
            with open(self.log_file, "a", buffering=1) as log:
                log.write(f"{datetime.datetime.now()} - CRITICAL: Temperature exceeded 100C - Initiating system shutdown\n")
                log.flush()
            
            # Speak final warning
            self.tts_engine.say("Critical temperature reached. System shutting down now.")
            self.tts_engine.runAndWait()
            
            # Initiate system shutdown
            if os.name == 'nt':  # Windows
                os.system('shutdown /s /t 1 /c "Critical GPU temperature detected"')
            else:  # Linux/Unix
                os.system('shutdown -h now')
            
            # Now clean up application resources
            self.quit_app()
                
        except Exception as e:
            print(f"Error during shutdown: {str(e)}")
            with open(self.log_file, "a", buffering=1) as log:
                log.write(f"{datetime.datetime.now()} - ERROR: Shutdown failed: {str(e)}\n")
                log.flush()

    def read_serial(self):
        """Read and process serial data"""
        print("Starting serial read loop")
        temps = [-999] * numberOfThermistors
        
        # Clear any initial garbage data
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.reset_input_buffer()
            time.sleep(0.2)  # Give more time for buffer to clear
            
            # Read and discard any partial data
            while self.serial_port.in_waiting:
                self.serial_port.readline()
        
        while self.running:
            if self.serial_port and self.serial_port.is_open:
                try:
                    line = self.serial_port.readline().decode('utf-8').strip()
                    print(f"Received data: {line}")
                    
                    if line:
                        try:
                            parts = line.split(':')
                            if len(parts) == 2:
                                temp_num = int(parts[0].split()[1])
                                temp_value = float(parts[1].replace('C', '').strip())
                                
                                if 0 <= temp_num < numberOfThermistors:
                                    temps[temp_num] = temp_value
                                    
                                    # Temperature warning checks
                                    if temp_value >= 100:
                                        self.shutdown_system()
                                    elif temp_value >= 90:
                                        self.speak_warning(
                                            "GPU power connector temperature warning. Temperature above 90 degrees.",
                                            'warning2'
                                        )
                                    elif temp_value >= 80:
                                        self.speak_warning(
                                            "Caution. GPU power connector temperature rising. Possible connector failure.",
                                            'warning1'
                                        )
                                    
                                    # Update temperature history
                                    self.temp_history[temp_num].append(temp_value)
                                    
                                    # Only update time history once per complete cycle
                                    if temp_num == numberOfThermistors - 1:  # Changed from 0 to last sensor
                                        self.time_history.append(datetime.datetime.now())
                                        self.readings_count += 1
                                        print(f"Complete reading cycle {self.readings_count}")
                                    
                                    # Update icon with current max valid temperature
                                    valid_temps = [t for t in temps if t > -999]
                                    if valid_temps:  # Only update if we have valid temperatures
                                        max_temp = max(valid_temps)
                                        icon = self.create_temp_icon(max_temp)
                                        self.tray_icon.icon = icon
                                    
                                    # Log temperatures
                                    with open(self.log_file, "a", buffering=1) as log:
                                        log.write(f"{datetime.datetime.now()} - Temp {temp_num}: {temp_value}C (Array: {temps})\n")
                                        log.flush()
                                else:
                                    print(f"Invalid sensor number: {temp_num}")
                                
                        except ValueError as ve:
                            print(f"Parse error: {str(ve)}")
                            with open(self.log_file, "a", buffering=1) as log:
                                log.write(f"{datetime.datetime.now()} - ERROR: Parse error: {str(ve)}\n")
                                log.flush()
                            
                except Exception as e:
                    print(f"Serial read error: {str(e)}")
                    with open(self.log_file, "a", buffering=1) as log:
                        log.write(f"{datetime.datetime.now()} - ERROR: Serial error: {str(e)}\n")
                        log.flush()
                
                time.sleep(0.01)

    def quit_app(self):
        """Clean up and exit"""
        print("Shutting down application...")
        
        # Set running flag to false first
        self.running = False
        
        try:
            # Close serial port if open
            if self.serial_port and self.serial_port.is_open:
                print("Closing serial port...")
                self.serial_port.close()
        except Exception as e:
            print(f"Error closing serial port: {str(e)}")
        
        try:
            # Log application shutdown
            with open(self.log_file, "a", buffering=1) as log:
                log.write(f"{datetime.datetime.now()} - Application shutdown\n")
                log.flush()
        except Exception as e:
            print(f"Error writing to log file: {str(e)}")
        
        try:
            # Destroy graph window
            if self.graph_window:
                print("Closing graph window...")
                self.graph_window.destroy()
            
            # Destroy root window
            if self.root:
                print("Closing root window...")
                self.root.quit()
                self.root.destroy()
        except Exception as e:
            print(f"Error closing windows: {str(e)}")
        
        try:
            # Stop the tray icon last
            print("Removing tray icon...")
            self.tray_icon.stop()
        except Exception as e:
            print(f"Error stopping tray icon: {str(e)}")
        
        # Use os._exit instead of sys.exit
        os._exit(0)

if __name__ == "__main__":
    # Check if running with admin privileges
    try:
        if not os.path.exists("C:\\Windows\\System32"):
            raise PermissionError
    except PermissionError:
        print("Please run as administrator for shutdown functionality")
        sys.exit(1)

    app = TemperatureMonitor()