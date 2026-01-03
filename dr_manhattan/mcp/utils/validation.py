"""Input validation utilities for MCP tools."""

import re
from typing import List, Optional

from dr_manhattan.utils import setup_logger

logger = setup_logger(__name__)

# Supported exchanges (validated against this list)
SUPPORTED_EXCHANGES = ["polymarket", "opinion", "limitless"]

# Regex patterns for validation
HEX_ADDRESS_PATTERN = re.compile(r"^0x[a-fA-F0-9]{40}$")
HEX_ID_PATTERN = re.compile(r"^0x[a-fA-F0-9]+$")
UUID_PATTERN = re.compile(
    r"^[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}$"
)
# Market IDs can be hex, UUID, or alphanumeric with dashes/underscores
MARKET_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_\-]+$")


def validate_exchange(exchange: str) -> str:
    """
    Validate exchange name.

    Args:
        exchange: Exchange name to validate

    Returns:
        Lowercase exchange name

    Raises:
        ValueError: If exchange is invalid
    """
    if not exchange or not isinstance(exchange, str):
        raise ValueError(
            f"Exchange name is required. Supported exchanges: {', '.join(SUPPORTED_EXCHANGES)}"
        )

    exchange_lower = exchange.lower().strip()
    if exchange_lower not in SUPPORTED_EXCHANGES:
        raise ValueError(
            f"Unknown exchange: {exchange}. Supported: {', '.join(SUPPORTED_EXCHANGES)}"
        )
    return exchange_lower


def validate_market_id(market_id: str) -> str:
    """
    Validate market ID format.

    Args:
        market_id: Market identifier to validate

    Returns:
        Sanitized market ID

    Raises:
        ValueError: If market ID is invalid
    """
    if not market_id or not isinstance(market_id, str):
        raise ValueError("Market ID is required. Expected: hex (0x...), UUID, or alphanumeric ID")

    market_id = market_id.strip()
    if len(market_id) > 256:
        raise ValueError("Market ID too long (max 256 characters)")

    # Allow hex IDs (0x...), UUIDs, and alphanumeric with dashes/underscores
    if not (
        HEX_ID_PATTERN.match(market_id)
        or UUID_PATTERN.match(market_id)
        or MARKET_ID_PATTERN.match(market_id)
    ):
        # Log full ID to stderr for debugging, truncate in user-facing message
        logger.warning(f"Invalid market ID format: {market_id}")
        raise ValueError(
            f"Invalid market ID format: {market_id[:50]}... "
            "Expected hex (0x...), UUID, or alphanumeric identifier."
        )
    return market_id


def validate_token_id(token_id: str) -> str:
    """
    Validate token ID format.

    Args:
        token_id: Token identifier to validate

    Returns:
        Sanitized token ID

    Raises:
        ValueError: If token ID is invalid
    """
    if not token_id or not isinstance(token_id, str):
        raise ValueError("Token ID is required. Expected: numeric or hex (0x...) identifier")

    token_id = token_id.strip()
    if len(token_id) > 256:
        raise ValueError("Token ID too long (max 256 characters)")

    # Token IDs are typically large integers or hex strings
    if not (token_id.isdigit() or HEX_ID_PATTERN.match(token_id)):
        # Log full ID to stderr for debugging, truncate in user-facing message
        logger.warning(f"Invalid token ID format: {token_id}")
        raise ValueError(
            f"Invalid token ID format: {token_id[:50]}... "
            "Expected numeric or hex (0x...) identifier."
        )
    return token_id


def validate_order_id(order_id: str) -> str:
    """
    Validate order ID format.

    Args:
        order_id: Order identifier to validate

    Returns:
        Sanitized order ID

    Raises:
        ValueError: If order ID is invalid
    """
    if not order_id or not isinstance(order_id, str):
        raise ValueError("Order ID is required. Expected: hex (0x...), UUID, or alphanumeric ID")

    order_id = order_id.strip()
    if len(order_id) > 256:
        raise ValueError("Order ID too long (max 256 characters)")

    # Order IDs can be hex, UUID, or alphanumeric
    if not (
        HEX_ID_PATTERN.match(order_id)
        or UUID_PATTERN.match(order_id)
        or MARKET_ID_PATTERN.match(order_id)
    ):
        # Log full ID to stderr for debugging, truncate in user-facing message
        logger.warning(f"Invalid order ID format: {order_id}")
        raise ValueError(
            f"Invalid order ID format: {order_id[:50]}... "
            "Expected hex (0x...), UUID, or alphanumeric identifier."
        )
    return order_id


def validate_session_id(session_id: str) -> str:
    """
    Validate strategy session ID (UUID format).

    Args:
        session_id: Session identifier to validate

    Returns:
        Sanitized session ID

    Raises:
        ValueError: If session ID is invalid
    """
    if not session_id or not isinstance(session_id, str):
        raise ValueError("Session ID is required. Expected: UUID format")

    session_id = session_id.strip()
    if not UUID_PATTERN.match(session_id):
        # Log full ID to stderr for debugging, truncate in user-facing message
        logger.warning(f"Invalid session ID format: {session_id}")
        raise ValueError(f"Invalid session ID format: {session_id[:50]}... Expected UUID format.")
    return session_id


def validate_side(side: str) -> str:
    """
    Validate order side.

    Args:
        side: Order side ("buy" or "sell")

    Returns:
        Lowercase side

    Raises:
        ValueError: If side is invalid
    """
    if not side or not isinstance(side, str):
        raise ValueError("Order side is required. Expected: 'buy' or 'sell'")

    side_lower = side.lower().strip()
    if side_lower not in ["buy", "sell"]:
        raise ValueError(f"Invalid order side: {side}. Must be 'buy' or 'sell'.")
    return side_lower


def validate_outcome(outcome: str) -> str:
    """
    Validate outcome name.

    Args:
        outcome: Outcome name (e.g., "Yes", "No")

    Returns:
        Sanitized outcome

    Raises:
        ValueError: If outcome is invalid
    """
    if not outcome or not isinstance(outcome, str):
        raise ValueError("Outcome is required. Expected: outcome name (e.g., 'Yes', 'No')")

    outcome = outcome.strip()
    if len(outcome) > 100:
        raise ValueError("Outcome name too long (max 100 characters)")

    # Basic sanitization - alphanumeric, spaces, and common punctuation
    if not re.match(r"^[a-zA-Z0-9\s\-_.,()]+$", outcome):
        raise ValueError(
            f"Invalid outcome format: {outcome[:50]}. "
            "Use alphanumeric characters and basic punctuation only."
        )
    return outcome


def validate_slug(slug: str) -> str:
    """
    Validate market slug.

    Args:
        slug: Market slug or URL

    Returns:
        Sanitized slug

    Raises:
        ValueError: If slug is invalid
    """
    if not slug or not isinstance(slug, str):
        raise ValueError("Slug is required. Expected: market slug or URL")

    slug = slug.strip()
    if len(slug) > 500:
        raise ValueError("Slug too long (max 500 characters)")

    # Allow URLs and slugs with alphanumeric, dashes, underscores, slashes, dots
    if not re.match(r"^[a-zA-Z0-9\-_./:%?&=]+$", slug):
        raise ValueError(
            f"Invalid slug format: {slug[:50]}. "
            "Use alphanumeric characters, dashes, and URL characters only."
        )
    return slug


def validate_positive_float(value: float, name: str) -> float:
    """
    Validate positive float value.

    Args:
        value: Value to validate
        name: Parameter name for error message

    Returns:
        Validated value

    Raises:
        ValueError: If value is not positive
    """
    if not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {value}")
    return float(value)


def validate_positive_int(value: int, name: str) -> int:
    """
    Validate positive integer value.

    Args:
        value: Value to validate
        name: Parameter name for error message

    Returns:
        Validated value

    Raises:
        ValueError: If value is not positive integer
    """
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {value}")
    return value


def validate_optional_market_id(market_id: Optional[str]) -> Optional[str]:
    """Validate optional market ID."""
    if market_id is None:
        return None
    return validate_market_id(market_id)


def validate_list_of_strings(items: List[str], name: str) -> List[str]:
    """
    Validate list of strings.

    Args:
        items: List to validate
        name: Parameter name for error message

    Returns:
        Validated list

    Raises:
        ValueError: If items is not a valid list of strings
    """
    if not isinstance(items, list):
        raise ValueError(f"{name} must be a list")
    for i, item in enumerate(items):
        if not isinstance(item, str):
            raise ValueError(f"{name}[{i}] must be a string")
    return items
