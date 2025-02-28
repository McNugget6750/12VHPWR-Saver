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
from PIL import Image
import io

class TemperatureMonitor:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Temperature Monitor")
        self.root.geometry("600x400")
        self.root.protocol("WM_DELETE_WINDOW", self.minimize_to_tray)

        # Temperature data storage (10 minutes = 600 seconds)
        self.max_points = 600
        self.temp_data = [deque(maxlen=self.max_points) for _ in range(4)]
        self.timestamps = deque(maxlen=self.max_points)

        # Serial port
        self.serial_port = None
        self.baud_rate = 115200
        self.last_port = self.load_last_port()

        # Watchdog flag
        self.running = True

        # Setup UI
        self.setup_graph()
        self.setup_tray()

        # Start with port selection
        self.show_port_selector()

        # Start watchdog thread
        self.watchdog_thread = threading.Thread(target=self.watchdog, daemon=True)
        self.watchdog_thread.start()

    def setup_graph(self):
        self.fig, self.ax = plt.subplots()
        self.lines = [self.ax.plot([], [], label=f'Temp {i}')[0] for i in range(4)]
        self.ax.set_ylim(0, 120)  # Temp range 0-120C
        self.ax.set_xlim(0, self.max_points)
        self.ax.set_title("Temperature Readings (Last 10 Minutes)")
        self.ax.set_xlabel("Time (s)")
        self.ax.set_ylabel("Temperature (C)")
        self.ax.legend()

        self.canvas = FigureCanvasTkAgg(self.fig, master=self.root)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    def setup_tray(self):
        # Create a simple icon (red square for this example)
        image = Image.new('RGB', (64, 64), (255, 0, 0))
        self.tray_icon = Icon("TempMonitor", image, menu=Menu(
            MenuItem("Open", self.restore_from_tray),
            MenuItem("Quit", self.quit_app)
        ))
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def load_last_port(self):
        try:
            with open("last_port.txt", "r") as f:
                return f.read().strip()
        except FileNotFoundError:
            return None

    def save_last_port(self, port):
        with open("last_port.txt", "w") as f:
            f.write(port)

    def show_port_selector(self):
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
        self.read_thread = threading.Thread(target=self.read_serial, daemon=True)
        self.read_thread.start()
        self.update_graph()

    def read_serial(self):
        while self.running:
            if self.serial_port and self.serial_port.is_open:
                try:
                    line = self.serial_port.readline().decode('utf-8').strip()
                    if line.startswith("Temp"):
                        temp_num = int(line.split()[1][:-1])
                        temp_value = int(line.split()[-1][:-1])
                        self.temp_data[temp_num].append(temp_value)
                        if not self.timestamps or time.time() - self.timestamps[-1] >= 1:
                            self.timestamps.append(time.time())

                        # Log the temperature
                        with open("temp_log.txt", "a") as log:
                            log.write(f"{datetime.datetime.now()} - Temp {temp_num}: {temp_value}C\n")

                        # Check for shutdown condition
                        if temp_value > 100:
                            with open("temp_log.txt", "a") as log:
                                log.write(f"{datetime.datetime.now()} - Shutdown triggered: Temp {temp_num} exceeded 100C\n")
                            subprocess.run(["shutdown", "/s", "/t", "5"])
                            self.quit_app()
                except Exception as e:
                    print(f"Error reading serial: {e}")
            time.sleep(0.1)

    def update_graph(self):
        if self.running:
            for i, line in enumerate(self.lines):
                if self.temp_data[i]:
                    x_data = [t - self.timestamps[0] for t in list(self.timestamps)[:len(self.temp_data[i])]]
                    line.set_data(x_data, list(self.temp_data[i]))
            self.ax.set_xlim(0, max(self.max_points, len(self.timestamps)))
            self.canvas.draw()
            self.root.after(1000, self.update_graph)

    def watchdog(self):
        while self.running:
            time.sleep(5)  # Simple watchdog checking every 5 seconds

    def minimize_to_tray(self):
        self.root.withdraw()

    def restore_from_tray(self, icon=None, item=None):
        self.root.deiconify()

    def quit_app(self, icon=None, item=None):
        self.running = False
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()
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