"""Shared logger configuration for Dr. Manhattan projects."""

import logging
import sys


class ColoredFormatter(logging.Formatter):
    """Custom formatter with colors and symbols"""
    
    COLORS = {
        'DEBUG': '\033[36m',      # Cyan
        'INFO': '\033[32m',       # Green
        'WARNING': '\033[33m',    # Yellow
        'ERROR': '\033[31m',      # Red
        'CRITICAL': '\033[35m',   # Magenta
        'TIMESTAMP': '\033[90m',  # Bright Black (Gray)
        'RESET': '\033[0m'        # Reset
    }
    
    SYMBOLS = {
        'DEBUG': '🔍',
        'INFO': '📊',
        'WARNING': '⚠️ ',
        'ERROR': '❌',
        'CRITICAL': '🔥'
    }
    
    def format(self, record):
        # Color the level name
        levelname = record.levelname
        color = self.COLORS.get(levelname, '')
        reset = self.COLORS['RESET']
        symbol = self.SYMBOLS.get(levelname, '')
        timestamp_color = self.COLORS['TIMESTAMP']

        # Format timestamp
        from datetime import datetime
        timestamp = datetime.fromtimestamp(record.created).strftime('%H:%M:%S')

        # Format: [TIMESTAMP] [SYMBOL] MESSAGE
        if record.levelname in ['INFO', 'DEBUG']:
            # For INFO/DEBUG, no symbol prefix
            return f"{timestamp_color}[{timestamp}]{reset} {record.getMessage()}"
        else:
            # For warnings/errors, show symbol
            return f"{timestamp_color}[{timestamp}]{reset} {symbol} {record.getMessage()}"


def setup_logger(name: str = None, level: int = logging.INFO) -> logging.Logger:
    """
    Create a configured logger with colored output.
    
    Args:
        name: Logger name (default: root logger)
        level: Logging level (default: INFO)
        
    Returns:
        Configured logger instance
        
    Example:
        >>> from dr_manhattan.utils.logger import setup_logger
        >>> logger = setup_logger(__name__)
        >>> logger.info("Starting...")
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # Remove existing handlers to avoid duplicates
    logger.handlers = []
    
    # Console handler with colored formatter
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(ColoredFormatter())
    logger.addHandler(console_handler)
    
    # Prevent propagation to root logger
    logger.propagate = False
    
    return logger


# Default logger instance
default_logger = setup_logger('dr_manhattan')

