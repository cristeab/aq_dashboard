#!/usr/bin/env python3

import os
os.environ["BLINKA_FT232H"] = "1"
try:
    import board
except ValueError as e:
    print(e)
    import sys
    sys.exit(1)
import adafruit_bme680
from persistent_storage import PersistentStorage
from print_utils import clear_lines
import time
from datetime import datetime, timezone


i2c = board.I2C()  # Automatically uses FT232H as I2C if BLINKA_FT232H=1 is set
sensor = adafruit_bme680.Adafruit_BME680_I2C(i2c)
persistent_storage = PersistentStorage()

SLEEP_DURATION_SECONDS = 2
# pressure (hPa) at sea level
sensor.sea_level_pressure = 1013.25

once = True
while True:
    timestamp = datetime.now(timezone.utc)
    temperature = sensor.temperature
    gas = sensor.gas
    relative_humidity = sensor.relative_humidity
    pressure = sensor.pressure
    altitude = sensor.altitude
    persistent_storage.write_ambient_data(timestamp, temperature, gas, relative_humidity, pressure, altitude)
    # print data
    if once:
        once = False
    else:
        clear_lines(1)
    local_time = timestamp.astimezone().strftime('%d/%m/%Y, %H:%M:%S')
    print(f'Timestamp: {local_time}, Temperature: {temperature:.2f} C, Gas: {gas} ohms, Humidity: {relative_humidity:.2f}%, Pressure: {pressure:.2f} hPa, Altitude: {altitude:.2f} meters')
    time.sleep(SLEEP_DURATION_SECONDS)
