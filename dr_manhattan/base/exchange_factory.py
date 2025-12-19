"""
Exchange factory for creating exchange instances.
"""

import os
from typing import Any, Dict, Optional, Type

from .exchange import Exchange

# Type alias for exchange configuration
ExchangeConfig = Dict[str, Any]


def get_exchange_class(name: str) -> Type[Exchange]:
    """
    Get exchange class by name.

    Args:
        name: Exchange name (polymarket, opinion, limitless)

    Returns:
        Exchange class

    Raises:
        ValueError: If exchange name is unknown
    """
    # Import here to avoid circular imports
    from ..exchanges.limitless import Limitless
    from ..exchanges.opinion import Opinion
    from ..exchanges.polymarket import Polymarket

    exchanges: Dict[str, Type[Exchange]] = {
        "polymarket": Polymarket,
        "opinion": Opinion,
        "limitless": Limitless,
    }

    name_lower = name.lower()
    if name_lower not in exchanges:
        available = ", ".join(exchanges.keys())
        raise ValueError(f"Unknown exchange: {name}. Available: {available}")

    return exchanges[name_lower]


def create_exchange(
    name: str,
    config: Optional[ExchangeConfig] = None,
    *,
    use_env: bool = True,
    verbose: bool = True,
) -> Exchange:
    """
    Create an exchange instance by name.

    Automatically loads credentials from environment variables if use_env=True.

    Args:
        name: Exchange name (polymarket, opinion, limitless)
        config: Optional configuration dict to override env vars
        use_env: Whether to load credentials from environment
        verbose: Enable verbose logging

    Returns:
        Configured exchange instance

    Raises:
        ValueError: If required credentials are missing

    Example:
        >>> exchange = create_exchange("polymarket")
        >>> exchange = create_exchange("opinion", {"api_key": "..."})
    """
    name_lower = name.lower()
    exchange_class = get_exchange_class(name_lower)

    # Build config from env vars and overrides
    final_config: ExchangeConfig = {"verbose": verbose}

    if use_env:
        env_config = _load_env_config(name_lower)
        final_config.update(env_config)

    if config:
        final_config.update(config)

    # Validate required fields
    _validate_config(name_lower, final_config)

    return exchange_class(final_config)


def _load_env_config(name: str) -> ExchangeConfig:
    """Load exchange config from environment variables."""
    config: ExchangeConfig = {}

    if name == "polymarket":
        if private_key := os.getenv("POLYMARKET_PRIVATE_KEY"):
            config["private_key"] = private_key
        if funder := os.getenv("POLYMARKET_FUNDER"):
            config["funder"] = funder
        if api_key := os.getenv("POLYMARKET_API_KEY"):
            config["api_key"] = api_key
        config["cache_ttl"] = float(os.getenv("POLYMARKET_CACHE_TTL", "2.0"))

    elif name == "opinion":
        if api_key := os.getenv("OPINION_API_KEY"):
            config["api_key"] = api_key
        if private_key := os.getenv("OPINION_PRIVATE_KEY"):
            config["private_key"] = private_key
        if multi_sig := os.getenv("OPINION_MULTI_SIG_ADDR"):
            config["multi_sig_addr"] = multi_sig

    elif name == "limitless":
        if private_key := os.getenv("LIMITLESS_PRIVATE_KEY"):
            config["private_key"] = private_key

    return config


def _validate_private_key(key: str, name: str) -> bool:
    """
    Validate private key format.

    Args:
        key: Private key to validate
        name: Exchange name for context

    Returns:
        True if valid

    Raises:
        ValueError: If key format is invalid
    """
    if not key:
        return False

    # Strip 0x prefix if present
    clean_key = key[2:] if key.startswith("0x") else key

    # Check length (64 hex chars = 32 bytes)
    if len(clean_key) != 64:
        raise ValueError(
            f"Invalid private key length for {name}. " "Expected 64 hex characters (32 bytes)."
        )

    # Check valid hex
    try:
        int(clean_key, 16)
    except ValueError:
        raise ValueError(f"Invalid private key format for {name}. " "Must be valid hexadecimal.")

    return True


def _validate_config(name: str, config: ExchangeConfig) -> None:
    """Validate that required config fields are present and properly formatted."""
    required: Dict[str, list] = {
        "polymarket": ["private_key", "funder"],
        "opinion": ["api_key", "private_key", "multi_sig_addr"],
        "limitless": ["private_key"],
    }

    missing = [key for key in required.get(name, []) if not config.get(key)]

    if missing:
        env_prefix = name.upper()
        env_vars = [f"{env_prefix}_{key.upper()}" for key in missing]
        raise ValueError(f"Missing required config: {missing}. Set env vars: {env_vars}")

    # Validate private key format if present
    if private_key := config.get("private_key"):
        _validate_private_key(private_key, name)


def list_exchanges() -> list[str]:
    """Return list of available exchange names."""
    return ["polymarket", "opinion", "limitless"]
