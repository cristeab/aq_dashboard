#!/usr/bin/env python3

from noise_detector.noise_detector import NoiseDetector
from persistent_storage import PersistentStorage
from logger_configurator import LoggerConfigurator


noise_detector = NoiseDetector()
noise_detector.logger = LoggerConfigurator.configure_logger("NoiseDetector")
persistent_storage = PersistentStorage()
noise_detector.set_noise_callback(
    lambda timestamp, noise_level_db: persistent_storage.write_noise_level(timestamp, noise_level_db)
)
noise_detector.run()
