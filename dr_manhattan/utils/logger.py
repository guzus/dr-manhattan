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


# Color utility functions for application code
class Colors:
    """ANSI color codes for terminal output"""
    # Basic colors
    RESET = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'

    # Foreground colors
    BLACK = '\033[30m'
    RED = '\033[31m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    BLUE = '\033[34m'
    MAGENTA = '\033[35m'
    CYAN = '\033[36m'
    WHITE = '\033[37m'
    GRAY = '\033[90m'

    # Bright foreground colors
    BRIGHT_RED = '\033[91m'
    BRIGHT_GREEN = '\033[92m'
    BRIGHT_YELLOW = '\033[93m'
    BRIGHT_BLUE = '\033[94m'
    BRIGHT_MAGENTA = '\033[95m'
    BRIGHT_CYAN = '\033[96m'

    @staticmethod
    def colorize(text: str, color: str) -> str:
        """Wrap text with color codes"""
        return f"{color}{text}{Colors.RESET}"

    @staticmethod
    def green(text: str) -> str:
        """Green text (for BUY, positive)"""
        return Colors.colorize(text, Colors.BRIGHT_GREEN)

    @staticmethod
    def red(text: str) -> str:
        """Red text (for SELL, negative)"""
        return Colors.colorize(text, Colors.BRIGHT_RED)

    @staticmethod
    def yellow(text: str) -> str:
        """Yellow text (for warnings, prices)"""
        return Colors.colorize(text, Colors.BRIGHT_YELLOW)

    @staticmethod
    def blue(text: str) -> str:
        """Blue text (for positions, info)"""
        return Colors.colorize(text, Colors.BRIGHT_BLUE)

    @staticmethod
    def cyan(text: str) -> str:
        """Cyan text (for market data)"""
        return Colors.colorize(text, Colors.BRIGHT_CYAN)

    @staticmethod
    def magenta(text: str) -> str:
        """Magenta text (for outcomes)"""
        return Colors.colorize(text, Colors.BRIGHT_MAGENTA)

    @staticmethod
    def gray(text: str) -> str:
        """Gray text (for secondary info)"""
        return Colors.colorize(text, Colors.GRAY)

    @staticmethod
    def bold(text: str) -> str:
        """Bold text"""
        return f"{Colors.BOLD}{text}{Colors.RESET}"


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

