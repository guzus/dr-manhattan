"""Utilities for MCP server."""

from .errors import McpError, translate_error
from .rate_limiter import RateLimiter, check_rate_limit, get_rate_limiter
from .security import (
    SENSITIVE_HEADERS,
    get_credentials_from_headers,
    has_any_credentials,
    sanitize_error_message,
    sanitize_headers_for_logging,
    validate_credentials_present,
)
from .serializers import serialize_model
from .validation import (
    SUPPORTED_EXCHANGES,
    validate_exchange,
    validate_market_id,
    validate_optional_market_id,
    validate_order_id,
    validate_outcome,
    validate_positive_float,
    validate_positive_int,
    validate_session_id,
    validate_side,
    validate_slug,
    validate_token_id,
)

__all__ = [
    "translate_error",
    "McpError",
    "serialize_model",
    "RateLimiter",
    "check_rate_limit",
    "get_rate_limiter",
    # Security
    "SENSITIVE_HEADERS",
    "get_credentials_from_headers",
    "has_any_credentials",
    "sanitize_error_message",
    "sanitize_headers_for_logging",
    "validate_credentials_present",
    # Validation
    "SUPPORTED_EXCHANGES",
    "validate_exchange",
    "validate_market_id",
    "validate_optional_market_id",
    "validate_order_id",
    "validate_outcome",
    "validate_positive_float",
    "validate_positive_int",
    "validate_session_id",
    "validate_side",
    "validate_slug",
    "validate_token_id",
]
