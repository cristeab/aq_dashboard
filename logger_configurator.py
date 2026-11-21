import logging


class LoggerConfigurator:
    log_level = logging.INFO

    def __init__(self):
        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(name)s.%(funcName)s:%(lineno)d | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        # systemd captures stderr and stores it in the journal.
        self.stream_handler = logging.StreamHandler()
        self.stream_handler.setFormatter(formatter)

    @staticmethod
    def configure_logger(class_name):
        logger = logging.getLogger(f"AQI.{class_name}")
        # configured once per logger: several instances of a class (e.g. two database
        # connections) must not write every line twice
        if not logger.handlers:
            lc = LoggerConfigurator()
            logger.setLevel(lc.log_level)
            logger.addHandler(lc.stream_handler)
        return logger
    
    @staticmethod
    def set_handler(logger):
        # Remove any existing handlers to avoid duplication
        logger.handlers.clear()

        lc = LoggerConfigurator()
        logger.setLevel(lc.log_level)
        logger.addHandler(lc.stream_handler)
