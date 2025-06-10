import logging
import logging.handlers
from pathlib import Path

def setup_logger(config):
    logger = logging.getLogger('trading')
    logger.setLevel(getattr(logging, config.level.upper()))
    logger.handlers.clear()

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logger.addHandler(console)

    log_file = Path(config.file)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=config.max_file_size,
        backupCount=config.backup_count
    )
    file_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logger.addHandler(file_handler)
    return logger

def get_logger():
    return logging.getLogger('trading')
