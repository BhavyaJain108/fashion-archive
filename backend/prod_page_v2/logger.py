"""
Logging configuration for product extraction.
"""

import logging
import sys

# Create logger
logger = logging.getLogger('prod_extract')
logger.setLevel(logging.DEBUG)

# Console handler with formatting
console = logging.StreamHandler(sys.stdout)
console.setLevel(logging.DEBUG)

formatter = logging.Formatter(
    '%(asctime)s | %(levelname)-5s | %(name)s | %(message)s',
    datefmt='%H:%M:%S'
)
console.setFormatter(formatter)

logger.addHandler(console)

# Convenience functions
def debug(msg): logger.debug(msg)
def info(msg): logger.info(msg)
def warn(msg): logger.warning(msg)
def error(msg): logger.error(msg)

# Strategy-specific loggers
def get_strategy_logger(name):
    """Get a child logger for a specific strategy."""
    return logger.getChild(name)
