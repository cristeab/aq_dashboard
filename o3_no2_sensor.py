#!/usr/bin/env python3

from zmod4510 import *
from persistent_storage import PersistentStorage
from logger_configurator import LoggerConfigurator
from datetime import datetime, timezone


logger = LoggerConfigurator.configure_logger("O3No2Sensor")
persistent_storage = PersistentStorage()
sensor = ZMOD4510(logger=logger)

if not sensor.start():
    logger.error("Failed to start ZMOD4510 sensor")
    exit(1)

while True:
    # Get real T/RH
    temperature, relative_humidity = persistent_storage.read_temperature_relative_humidity_data()

    # Get and process sensor data
    if temperature is not None and relative_humidity is not None:
        logger.info(f"Using temperature: {temperature}, relative_humidity: {relative_humidity}")
        data = sensor.get_data(temperature_celsius_deg=temperature, relative_humidity_percent=relative_humidity)
    else:
        data = sensor.get_data()
            
    match data.status:
        case ZMODStatus.STABILIZATION:
            logger.info("Warming up...")
        case ZMODStatus.OK:
            timestamp = datetime.now(timezone.utc)
            persistent_storage.write_zmod4510_data(timestamp, data.o3_ppb, data.no2_ppb, data.fast_aqi, data.epa_aqi)

            local_time = timestamp.astimezone().strftime('%d/%m/%Y, %H:%M:%S')
            logger.info(f"Timestamp: {local_time}, O3: {data.o3_ppb:.3f} ppb, NO2: {data.no2_ppb:.3f} ppb, "
                        f"Fast AQI: {data.fast_aqi}, EPA AQI: {data.epa_aqi}")
        case ZMODStatus.DAMAGE:
            logger.error("Damaged.")
        case _:
            logger.error(f"Unknown status: {data.status}")