"""Utilities for MCP server."""

from .errors import McpError, translate_error
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
