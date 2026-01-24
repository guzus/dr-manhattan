"""Security utilities for MCP server.

Provides functions for handling sensitive data safely in remote MCP environments.
"""

import re
from typing import Any, Dict, List, Optional

# Sensitive header names that should never be logged
SENSITIVE_HEADERS: List[str] = [
    # Polymarket
    "x-polymarket-private-key",
    "x-polymarket-funder",
    "x-polymarket-proxy-wallet",
    # Limitless
    "x-limitless-private-key",
    # Opinion
    "x-opinion-private-key",
    "x-opinion-api-key",
    "x-opinion-multi-sig-addr",
    # Kalshi
    "x-kalshi-api-key",
    "x-kalshi-private-key",
    # Predict.fun
    "x-predictfun-private-key",
    "x-predictfun-api-key",
    # Generic
    "authorization",
    "x-api-key",
]

# Header to credential mapping for each exchange
HEADER_CREDENTIAL_MAP: Dict[str, Dict[str, str]] = {
    "polymarket": {
        "x-polymarket-private-key": "private_key",
        "x-polymarket-funder": "funder",
        "x-polymarket-proxy-wallet": "proxy_wallet",
        "x-polymarket-signature-type": "signature_type",
    },
    "limitless": {
        "x-limitless-private-key": "private_key",
    },
    "opinion": {
        "x-opinion-private-key": "private_key",
        "x-opinion-api-key": "api_key",
        "x-opinion-multi-sig-addr": "multi_sig_addr",
    },
    "kalshi": {
        "x-kalshi-api-key": "api_key_id",
        "x-kalshi-private-key": "private_key",
    },
    "predictfun": {
        "x-predictfun-private-key": "private_key",
        "x-predictfun-api-key": "api_key",
    },
}

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

    Replaces sensitive header values with masked placeholders.

    Args:
        headers: Original headers dict

    Returns:
        Headers dict with sensitive values masked
    """
    sanitized = {}
    for key, value in headers.items():
        if is_sensitive_header(key):
            # Show first 4 and last 4 chars for debugging, mask the rest
            if value and len(value) > 12:
                sanitized[key] = f"{value[:4]}...{value[-4:]} (masked)"
            else:
                sanitized[key] = "*** (masked)"
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

    Args:
        credentials: Credentials dict for the exchange
        exchange: Exchange name

    Returns:
        Tuple of (is_valid, error_message)
    """
    required_fields = {
        "polymarket": ["private_key", "funder"],
        "limitless": ["private_key"],
        "opinion": ["private_key"],
        "kalshi": ["api_key_id", "private_key"],
        "predictfun": ["private_key"],
    }

    required = required_fields.get(exchange.lower(), [])
    missing = [field for field in required if not credentials.get(field)]

    if missing:
        header_hints = []
        header_map = HEADER_CREDENTIAL_MAP.get(exchange.lower(), {})
        for field in missing:
            for header, cred_key in header_map.items():
                if cred_key == field:
                    header_hints.append(header.upper().replace("-", "_"))
                    break

        return False, f"Missing required credentials for {exchange}: {', '.join(header_hints)}"

    return True, None


def has_any_credentials(headers: Dict[str, str]) -> bool:
    """Check if headers contain any exchange credentials."""
    normalized = {k.lower() for k in headers.keys()}
    return any(h in normalized for h in SENSITIVE_HEADERS if h != "authorization")
