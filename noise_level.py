#!/usr/bin/env python3

from noise_detector.noise_detector import NoiseDetector
from persistent_storage import PersistentStorage
from logger_configurator import LoggerConfigurator
import argparse
import time
from datetime import datetime, timezone
from constants import SLEEP_DURATION_SECONDS


parser = argparse.ArgumentParser(description='Script to read the noise level from the serial port')
parser.add_argument('--port', required=True, help='Serial port to use (e.g., /dev/ttyACM0)')

args = parser.parse_args()

noise_detector = NoiseDetector(args.port)
noise_detector.logger = LoggerConfigurator.configure_logger("NoiseDetector")
persistent_storage = PersistentStorage()

while True:
    timestamp = datetime.now(timezone.utc)
    noise_level_db = noise_detector.read_noise_level()
    persistent_storage.write_noise_level(timestamp, noise_level_db)

    local_time = timestamp.astimezone().strftime('%d/%m/%Y, %H:%M:%S')
    print(f'Timestamp: {local_time}, Noise level: {noise_level_db} dB', flush=True)
    time.sleep(SLEEP_DURATION_SECONDS)
