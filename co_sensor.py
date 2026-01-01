#!/usr/bin/env python3

from winsen_ze07co.carbon_monoxide_detector import CarbonMonoxideDetector
from persistent_storage import PersistentStorage
from logger_configurator import LoggerConfigurator
from constants import SLEEP_DURATION_SECONDS
import argparse
from datetime import datetime, timezone
import time


parser = argparse.ArgumentParser(description='Script to read CO concentration')
parser.add_argument('port', help='USB port to use (e.g., /dev/ttyACM0)')
args = parser.parse_args()

logger = LoggerConfigurator.configure_logger("CoSensor")
persistent_storage = PersistentStorage()

co_sensor = CarbonMonoxideDetector(port=args.port, logger=logger)
co_sensor.set_qa_mode()

while True:
    co_ppm = co_sensor.get_qa_co_ppm()
    if co_ppm is not None:
        timestamp = datetime.now(timezone.utc)
        persistent_storage.write_co_data(timestamp, co_ppm)
        local_time = timestamp.astimezone().strftime('%d/%m/%Y, %H:%M:%S')
        print(f'Timestamp: {local_time}, CO: {co_ppm:.1f} PPM', flush=True)
    time.sleep(SLEEP_DURATION_SECONDS)