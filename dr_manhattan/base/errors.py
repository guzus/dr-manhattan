class DrManhattanError(Exception):
    """Base exception for all dr-manhattan errors"""
    pass


class ExchangeError(DrManhattanError):
    """Exchange-specific error"""
    pass


class NetworkError(DrManhattanError):
    """Network connectivity error"""
    pass


class RateLimitError(DrManhattanError):
    """Rate limit exceeded"""
    pass


class AuthenticationError(DrManhattanError):
    """Authentication failed"""
    pass


class InsufficientFunds(DrManhattanError):
    """Insufficient funds for operation"""
    pass


class InvalidOrder(DrManhattanError):
    """Invalid order parameters"""
    pass


class MarketNotFound(DrManhattanError):
    """Market does not exist"""
    pass
