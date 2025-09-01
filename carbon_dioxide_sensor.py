#!/usr/bin/env python3

import board
import adafruit_scd4x
from datetime import datetime, timezone
from persistent_storage import PersistentStorage
from logger_configurator import LoggerConfigurator
import time
from constants import SLEEP_DURATION_SECONDS

# Initialize logger
logger = LoggerConfigurator.configure_logger("CO2Sensor")

# Initialize persistent storage
persistent_storage = PersistentStorage()

# Initialize I2C bus
i2c = board.I2C()  # Uses default SDA (GPIO 2) and SCL (GPIO 3) pins on Raspberry Pi
# Initialize the SCD41 sensor
scd4x = adafruit_scd4x.SCD4X(i2c)
# Start continuous measurement
scd4x.start_periodic_measurement()
logger.info("Waiting for first measurement....")

while True:
    if scd4x.data_ready:
        timestamp = datetime.now(timezone.utc)
        co2 = scd4x.CO2
        temperature = scd4x.temperature
        relative_humidity = scd4x.relative_humidity
        persistent_storage.write_co2_data(timestamp, co2, temperature, relative_humidity)
        local_time = timestamp.astimezone().strftime('%d/%m/%Y, %H
        print(f"Timestamp: {local_time}, CO2: {co2} ppm, Temperature: {temperature:.1f} °C, Humidity: {relative_humidity:.1f} %RH")
    time.sleep(SLEEP_DURATION_SECONDS)
