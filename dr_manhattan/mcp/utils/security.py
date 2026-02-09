"""Security utilities for MCP server.

Provides functions for handling sensitive data safely in remote MCP environments.
"""

import re
import time
from typing import Any, Dict, List, Optional

from eth_account.messages import encode_defunct
from web3 import Web3

# Sensitive header names that should never be logged
SENSITIVE_HEADERS: List[str] = [
    # Polymarket (Builder profile - no private key needed)
    "x-polymarket-api-key",
    "x-polymarket-api-secret",
    "x-polymarket-passphrase",
    # Operator mode authentication
    "x-polymarket-auth-signature",
    # Generic
    "authorization",
    "x-api-key",
]

# Header to credential mapping for each exchange
# SSE server supports Polymarket via:
# 1. Operator mode: user provides wallet address + signature, server signs on behalf
# 2. Builder profile: user provides api_key, api_secret, api_passphrase
HEADER_CREDENTIAL_MAP: Dict[str, Dict[str, str]] = {
    "polymarket": {
        # Operator mode (preferred for SSE) - requires signature for security
        "x-polymarket-wallet-address": "user_address",
        "x-polymarket-auth-signature": "auth_signature",
        "x-polymarket-auth-timestamp": "auth_timestamp",
        "x-polymarket-auth-expiry": "auth_expiry",
        # Builder profile (alternative)
        "x-polymarket-api-key": "api_key",
        "x-polymarket-api-secret": "api_secret",
        "x-polymarket-passphrase": "api_passphrase",
    },
}

# Authentication message prefix (must match frontend)
AUTH_MESSAGE_PREFIX = "I authorize Dr. Manhattan to trade on Polymarket on my behalf."

# Default signature validity (24 hours) - can be overridden by user
DEFAULT_SIGNATURE_VALIDITY_SECONDS = 86400

# Maximum allowed expiry (90 days) - security limit
MAX_SIGNATURE_VALIDITY_SECONDS = 7776000

# Allowed expiry options (must match frontend)
ALLOWED_EXPIRY_OPTIONS = [86400, 604800, 2592000, 7776000]  # 24h, 7d, 30d, 90d

# Write operations that modify state (require credentials)
WRITE_OPERATIONS: List[str] = [
    "create_order",
    "cancel_order",
    "cancel_all_orders",
    "create_strategy_session",
    "stop_strategy",
    "pause_strategy",
    "resume_strategy",
]

# Exchanges that support write operations via SSE (Builder profile)
SSE_WRITE_ENABLED_EXCHANGES: List[str] = ["polymarket"]

# Patterns that look like private keys or sensitive data
SENSITIVE_PATTERNS = [
    re.compile(r"0x[a-fA-F0-9]{64}"),  # Ethereum private key
    re.compile(r"[a-fA-F0-9]{64}"),  # Raw hex key
    re.compile(r"-----BEGIN.*PRIVATE KEY-----"),  # RSA/EC private key
]


def is_sensitive_header(header_name: str) -> bool:
    """Check if a header name is sensitive."""
    return header_name.lower() in SENSITIVE_HEADERS


def sanitize_headers_for_logging(headers: Dict[str, str]) -> Dict[str, str]:
    """
    Sanitize headers for safe logging.

    Replaces sensitive header values with fully masked placeholders.
    Does NOT expose any characters to prevent brute force hints.

    Args:
        headers: Original headers dict

    Returns:
        Headers dict with sensitive values fully masked
    """
    sanitized = {}
    for key, value in headers.items():
        if is_sensitive_header(key):
            # Fully mask - do not expose any characters (security best practice)
            sanitized[key] = "[REDACTED]" if value else "[EMPTY]"
        else:
            sanitized[key] = value
    return sanitized


def sanitize_error_message(message: str) -> str:
    """
    Remove sensitive data from error messages.

    Args:
        message: Original error message

    Returns:
        Message with sensitive patterns replaced
    """
    result = message
    for pattern in SENSITIVE_PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    return result


def get_credentials_from_headers(headers: Dict[str, str]) -> Dict[str, Dict[str, Any]]:
    """
    Extract exchange credentials from HTTP headers.

    Headers are expected in format: X-{Exchange}-{Credential}
    e.g., X-Polymarket-Private-Key, X-Limitless-Private-Key

    Args:
        headers: HTTP headers dict (case-insensitive keys)

    Returns:
        Credentials dict keyed by exchange name
    """
    # Normalize header keys to lowercase
    normalized_headers = {k.lower(): v for k, v in headers.items()}

    credentials: Dict[str, Dict[str, Any]] = {}

    for exchange, header_map in HEADER_CREDENTIAL_MAP.items():
        exchange_creds: Dict[str, Any] = {}

        for header_name, cred_key in header_map.items():
            value = normalized_headers.get(header_name)
            if value:
                # Handle type conversion for specific fields
                if cred_key == "signature_type":
                    try:
                        exchange_creds[cred_key] = int(value)
                    except ValueError:
                        exchange_creds[cred_key] = 0  # Default EOA
                else:
                    exchange_creds[cred_key] = value

        # Only include exchange if it has at least one credential
        if exchange_creds:
            credentials[exchange] = exchange_creds

    return credentials


def validate_credentials_present(
    credentials: Dict[str, Any], exchange: str
) -> tuple[bool, Optional[str]]:
    """
    Validate that required credentials are present for an exchange.

    Returns transport-agnostic error messages. The transport layer (SSE, stdio)
    should add transport-specific hints if needed.

    Args:
        credentials: Credentials dict for the exchange
        exchange: Exchange name

    Returns:
        Tuple of (is_valid, error_message)
    """
    # SSE server only supports Polymarket via Builder profile
    required_fields = {
        "polymarket": ["api_key", "api_secret", "api_passphrase"],
    }

    required = required_fields.get(exchange.lower(), [])
    missing = [field for field in required if not credentials.get(field)]

    if missing:
        # Transport-agnostic message (no HTTP header references)
        return False, f"Missing required credentials for {exchange}: {', '.join(missing)}"

    return True, None


def is_write_operation(tool_name: str) -> bool:
    """Check if a tool is a write operation."""
    return tool_name in WRITE_OPERATIONS


def is_write_allowed_for_exchange(exchange: str) -> bool:
    """Check if write operations are allowed for an exchange via SSE."""
    return exchange.lower() in SSE_WRITE_ENABLED_EXCHANGES


def validate_write_operation(tool_name: str, exchange: Optional[str]) -> tuple[bool, Optional[str]]:
    """
    Validate that a write operation is allowed.

    SSE server only allows write operations for Polymarket (via Builder profile).
    Other exchanges are read-only for security (no private keys on server).

    Args:
        tool_name: The MCP tool being called
        exchange: The target exchange (if applicable)

    Returns:
        Tuple of (is_allowed, error_message)
    """
    if not is_write_operation(tool_name):
        return True, None

    if not exchange:
        return False, f"Write operation '{tool_name}' requires an exchange parameter"

    if not is_write_allowed_for_exchange(exchange):
        return (
            False,
            f"Write operations are not supported for '{exchange}' via remote server. "
            f"Only Polymarket is supported (via Builder profile). "
            f"For other exchanges, use the local MCP server.",
        )

    return True, None


def get_header_hint_for_credential(exchange: str, credential: str) -> Optional[str]:
    """
    Get the HTTP header name hint for a credential.

    This is a helper for SSE transport to provide user-friendly error messages.

    Args:
        exchange: Exchange name
        credential: Credential field name (e.g., 'private_key')

    Returns:
        Header name (e.g., 'X-Polymarket-Private-Key') or None
    """
    header_map = HEADER_CREDENTIAL_MAP.get(exchange.lower(), {})
    for header, cred_key in header_map.items():
        if cred_key == credential:
            # Convert to title case for display (x-polymarket-private-key -> X-Polymarket-Private-Key)
            return "-".join(word.title() for word in header.split("-"))
    return None


def has_any_credentials(headers: Dict[str, str]) -> bool:
    """Check if headers contain any exchange credentials."""
    normalized = {k.lower() for k in headers.keys()}
    return any(h in normalized for h in SENSITIVE_HEADERS if h != "authorization")


def verify_wallet_signature(
    wallet_address: str, signature: str, timestamp: str, expiry: Optional[str] = None
) -> tuple[bool, Optional[str]]:
    """
    Verify that a signature proves ownership of a wallet address.

    The user must sign a message containing their wallet address, timestamp, and expiry.
    This prevents replay attacks and proves wallet ownership.

    Args:
        wallet_address: The claimed wallet address
        signature: The signature of the auth message
        timestamp: Unix timestamp when the message was signed
        expiry: Expiry duration in seconds (optional, defaults to 24 hours)

    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        # Parse and validate timestamp
        ts = int(timestamp)
        current_time = int(time.time())

        # Parse and validate expiry
        if expiry:
            try:
                expiry_seconds = int(expiry)
                # Validate expiry is one of the allowed options
                if expiry_seconds not in ALLOWED_EXPIRY_OPTIONS:
                    return False, f"Invalid expiry duration. Allowed: {ALLOWED_EXPIRY_OPTIONS}"
                # Cap at maximum for security
                expiry_seconds = min(expiry_seconds, MAX_SIGNATURE_VALIDITY_SECONDS)
            except ValueError:
                return False, "Invalid expiry format."
        else:
            expiry_seconds = DEFAULT_SIGNATURE_VALIDITY_SECONDS

        # Check if signature has expired
        if current_time - ts > expiry_seconds:
            return False, "Signature has expired. Please re-authenticate."

        # Check if timestamp is in the future (clock skew tolerance: 5 minutes)
        if ts > current_time + 300:
            return False, "Invalid timestamp (in future)."

        # Reconstruct the message that was signed (must match frontend format)
        if expiry:
            message = f"{AUTH_MESSAGE_PREFIX}\n\nWallet: {wallet_address}\nTimestamp: {timestamp}\nExpiry: {expiry}"
        else:
            # Legacy format without expiry (for backwards compatibility)
            message = f"{AUTH_MESSAGE_PREFIX}\n\nWallet: {wallet_address}\nTimestamp: {timestamp}"

        # Verify the signature
        w3 = Web3()
        message_hash = encode_defunct(text=message)
        recovered_address = w3.eth.account.recover_message(message_hash, signature=signature)

        # Compare addresses (case-insensitive)
        if recovered_address.lower() != wallet_address.lower():
            return False, "Signature does not match wallet address."

        return True, None

    except ValueError as e:
        return False, f"Invalid timestamp format: {e}"
    except Exception as e:
        return False, f"Signature verification failed: {e}"


def validate_operator_credentials(credentials: Dict[str, Any]) -> tuple[bool, Optional[str]]:
    """
    Validate operator mode credentials (wallet address + signature).

    Args:
        credentials: Credentials dict containing user_address, auth_signature, auth_timestamp, auth_expiry

    Returns:
        Tuple of (is_valid, error_message)
    """
    user_address = credentials.get("user_address")
    signature = credentials.get("auth_signature")
    timestamp = credentials.get("auth_timestamp")
    expiry = credentials.get("auth_expiry")

    if not user_address:
        return False, "Missing wallet address."

    if not signature or not timestamp:
        return (
            False,
            "Missing authentication signature. Please authenticate at dr-manhattan.io/approve",
        )

    return verify_wallet_signature(user_address, signature, timestamp, expiry)
