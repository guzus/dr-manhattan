"""Error handling and translation for MCP server."""

from typing import Any, Dict, Optional

from dr_manhattan.base.errors import (
    AuthenticationError,
    DrManhattanError,
    ExchangeError,
    InsufficientFunds,
    InvalidOrder,
    MarketNotFound,
    NetworkError,
    RateLimitError,
)


class McpError(Exception):
    """MCP protocol error."""

    def __init__(self, code: int, message: str, data: Optional[Dict[str, Any]] = None):
        self.code = code
        self.message = message
        self.data = data or {}
        super().__init__(message)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to MCP error response format."""
        return {"code": self.code, "message": self.message, "data": self.data}


# Dr-Manhattan Error -> MCP Error Code mapping
ERROR_MAP = {
    DrManhattanError: -32000,  # Generic error
    ExchangeError: -32001,  # Exchange-specific error
    NetworkError: -32002,  # Network/connection error
    RateLimitError: -32003,  # Rate limit exceeded
    AuthenticationError: -32004,  # Auth failed
    InsufficientFunds: -32005,  # Not enough balance
    InvalidOrder: -32006,  # Invalid order params
    MarketNotFound: -32007,  # Market doesn't exist
}


# Allowlist of safe context fields to include in error responses.
# Never include sensitive data like private_key, funder, password, token, secret.
SAFE_CONTEXT_FIELDS = frozenset(
    {
        "exchange",
        "market_id",
        "order_id",
        "session_id",
        "token_id",
        "side",
        "outcome",
        "slug",
        "identifier",
        "token_symbol",
    }
)


def translate_error(e: Exception, context: Optional[Dict[str, Any]] = None) -> McpError:
    """
    Translate dr-manhattan exception to MCP error.

    Args:
        e: Exception to translate
        context: Additional context (exchange, market_id, etc.)
                 Only allowlisted fields are included in error response.

    Returns:
        McpError instance
    """
    # Get error code from mapping
    error_code = ERROR_MAP.get(type(e), -32000)

    # Build error data
    error_data = {
        "type": type(e).__name__,
        "exchange": getattr(e, "exchange", None),
        "details": getattr(e, "details", None),
    }

    # Add only safe context fields (prevent leaking sensitive data)
    if context:
        for key, value in context.items():
            if key in SAFE_CONTEXT_FIELDS and value is not None:
                error_data[key] = value

    # Remove None values
    error_data = {k: v for k, v in error_data.items() if v is not None}

    return McpError(code=error_code, message=str(e), data=error_data)
