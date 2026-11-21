"""
Logging for the processor tools.

Only the CSP-generation logger is used by SSBM Nucleus. The backend sets
NUCLEUS_LOGS_DIR (see backend/core/config.py) so logs land in the app's
logs folder; standalone use falls back to a logs/ folder next to the tools.
"""

import logging
import os
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler

LOGS_DIR = Path(os.environ.get('NUCLEUS_LOGS_DIR') or Path(__file__).parent.parent / 'logs')
LOGS_DIR.mkdir(parents=True, exist_ok=True)

LOG_FORMAT = '%(asctime)s | %(name)s | %(levelname)s | %(message)s'
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

# File handler configuration (10MB max per file, keep 3 backups)
MAX_BYTES = 10 * 1024 * 1024  # 10MB
BACKUP_COUNT = 3


def setup_logger(name, log_file, level=logging.INFO, also_console=True):
    """Set up a logger with file and optional console output."""
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Avoid duplicate handlers if logger already exists
    if logger.handlers:
        return logger

    file_handler = RotatingFileHandler(
        LOGS_DIR / log_file,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    logger.addHandler(file_handler)

    if also_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
        logger.addHandler(console_handler)

    return logger


def get_csp_logger():
    """Get the CSP generation logger."""
    return setup_logger('csp', 'csp_generation.log')
