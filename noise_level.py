#!/usr/bin/env python3

from noise_detector.noise_detector import NoiseDetector
from noise_detector.reset_respeaker import reset_respeaker_lite
from persistent_storage import PersistentStorage
from logger_configurator import LoggerConfigurator
import time


logger = LoggerConfigurator.configure_logger("NoiseDetector")
noise_detector = NoiseDetector(logger)
persistent_storage = PersistentStorage()
noise_detector.set_noise_callback(
    lambda timestamp, noise_level_db: persistent_storage.write_noise_level(timestamp, noise_level_db)
)
noise_detector.set_stt_callback(
    lambda txt: logger.info(f"STT '{txt}'")
)
reset_respeaker_lite()
time.sleep(2)
noise_detector.run()
