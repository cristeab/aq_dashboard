#!/usr/bin/env python3

from noise_detector.noise_detector import NoiseDetector
from persistent_storage import PersistentStorage
from logger_configurator import LoggerConfigurator
from print_utils import clear_lines
import argparse
import time
from datetime import datetime, timezone


SLEEP_DURATION_SECONDS = 2
parser = argparse.ArgumentParser(description='Script to read the noise level from the serial port')
parser.add_argument('--port', required=True, help='Serial port to use (e.g., /dev/ttyACM0)')

args = parser.parse_args()

noise_detector = NoiseDetector(args.port)
noise_detector.logger = LoggerConfigurator.configure_logger("NoiseDetector")
persistent_storage = PersistentStorage()

once = True
while True:
    timestamp = datetime.now(timezone.utc)
    noise_level_db = noise_detector.read_noise_level()
    persistent_storage.write_noise_level(timestamp, noise_level_db)
    # print data
    if once:
        once = False
    else:
        clear_lines(1)
    local_time = timestamp.astimezone().strftime('%d/%m/%Y, %H:%M:%S')
    print(f'Timestamp: {local_time}, Noise level: {noise_level_db} dB')
    time.sleep(SLEEP_DURATION_SECONDS)
