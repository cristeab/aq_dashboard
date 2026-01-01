#!/usr/bin/env python3

from bosh_bme68x.ambient_monitor import AmbientMonitor
from persistent_storage import PersistentStorage
import time
from constants import SLEEP_DURATION_SECONDS


monitor = AmbientMonitor()
persistent_storage = PersistentStorage()

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

        print(f'{monitor.elapsed_time}, Temperature: {temperature:.1f} C, Humidity: {humidity:.1f} %, Pressure: {pressure:.1f} hPa, Gas: {gas} ohms, IAQ: {iaq:.1f}', flush=True)
    time.sleep(SLEEP_DURATION_SECONDS)
