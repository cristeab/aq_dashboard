#!/usr/bin/env python3

from sensirion_i2c_driver import LinuxI2cTransceiver, I2cConnection
from sensirion_i2c_sgp4x import Sgp41I2cDevice
from sensirion_gas_index_algorithm.voc_algorithm import VocAlgorithm
from sensirion_gas_index_algorithm.nox_algorithm import NoxAlgorithm
from persistent_storage import PersistentStorage
from logger_configurator import LoggerConfigurator
from datetime import datetime, timezone
import time
from constants import SLEEP_DURATION_SECONDS


# Connect to I2C port
logger = LoggerConfigurator.configure_logger("VocNoxSensor")
persistent_storage = PersistentStorage()
with LinuxI2cTransceiver('/dev/i2c-1') as i2c_transceiver:
    sgp41 = Sgp41I2cDevice(I2cConnection(i2c_transceiver))

    # Print serial number
    logger.info(f"SGP41 Serial: {sgp41.get_serial_number()}")

    # First 10 seconds: conditioning (recommended by Sensirion)
    logger.info("Running conditioning...")
    for _ in range(10):
        voc_raw = sgp41.conditioning()
        logger.info(f"VOC raw (conditioning): {voc_raw}")
        time.sleep(1)

    # Initialize Gas Index Algorithm
    voc_algorithm = VocAlgorithm()
    nox_algorithm = NoxAlgorithm()

    logger.info("Measuring VOC+NOx...")
    while True:
        timestamp = datetime.now(timezone.utc)
        raw_voc, raw_nox = sgp41.measure_raw()

        voc_index = voc_algorithm.process(raw_voc.ticks)
        nox_index = nox_algorithm.process(raw_nox.ticks)
        persistent_storage.write_sgp41_data(timestamp, voc_index, nox_index)

        local_time = timestamp.astimezone().strftime('%d/%m/%Y, %H:%M:%S')
        print(f'Timestamp: {local_time}, VOC index: {voc_index}, NOx index: {nox_index}', flush=True)
        time.sleep(SLEEP_DURATION_SECONDS)