#!/usr/bin/env python3

import board
import adafruit_bmp3xx
from datetime import datetime, timezone
from persistent_storage import PersistentStorage
from logger_configurator import LoggerConfigurator
import time
from constants import SLEEP_DURATION_SECONDS


# Initialize logger
logger = LoggerConfigurator.configure_logger("BMP390l")

# Initialize persistent storage
persistent_storage = PersistentStorage()

# Create I2C object using board's default SDA/SCL pins
i2c = board.I2C()  # For STEMMA QT, works with Pi or microcontrollers

# Create sensor object
bmp = adafruit_bmp3xx.BMP3XX_I2C(i2c, address=0x76)

# Optional: set oversampling (for better accuracy)
bmp.pressure_oversampling = 8
bmp.temperature_oversampling = 2

# Optional: set local sea level pressure for accurate altitude (in hPa)
bmp.sea_level_pressure = 1013.25

logger.info("Starting reading measurements...")
while True:
    timestamp = datetime.now(timezone.utc)
    persistent_storage.write_bmp390l_data(timestamp, bmp.temperature, bmp.pressure, bmp.altitude)
    local_time = timestamp.astimezone().strftime('%d/%m/%Y, %H:%M:%S')
    print(f"Timestamp: {local_time}, Pressure: {bmp.pressure:6.2f} hPa, Temperature: {bmp.temperature:5.2f} C, Altitude: {bmp.altitude:6.2f} m")
    time.sleep(SLEEP_DURATION_SECONDS)