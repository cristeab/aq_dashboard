#!/usr/bin/env python3

from ambient_monitor.ambient_monitor import AmbientMonitor
from persistent_storage import PersistentStorage
from print_utils import clear_lines
import time
from constants import SLEEP_DURATION_SECONDS


monitor = AmbientMonitor()
persistent_storage = PersistentStorage()

once = True
while True:
    data = monitor.get_data()
    if data is not None:
        timestamp = data['timestamp']
        temperature = data['temperature']
        gas = data['gas']
        humidity = data['humidity']
        pressure = data['pressure']
        iaq = data['iaq']
        persistent_storage.write_ambient_data(timestamp, temperature, gas, humidity, pressure, iaq)

        if once:
            once = False
        else:
            clear_lines(1)
        print(f'{monitor.elapsed_time}, Temperature: {temperature:.1f} C, Humidity: {humidity:.1f} %, Pressure: {pressure:.1f} hPa, Gas: {gas} ohms, IAQ: {iaq:.1f}', flush=True)
    time.sleep(SLEEP_DURATION_SECONDS)
