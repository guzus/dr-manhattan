"""Exchange session manager."""

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any, Dict

from dr_manhattan.base import Exchange, ExchangeClient, create_exchange
from dr_manhattan.utils import setup_logger

logger = setup_logger(__name__)

# Configurable timeout values (in seconds)
EXCHANGE_INIT_TIMEOUT = float(os.getenv("MCP_EXCHANGE_INIT_TIMEOUT", "10.0"))
CLIENT_INIT_TIMEOUT = float(os.getenv("MCP_CLIENT_INIT_TIMEOUT", "5.0"))


# Configuration defaults (per CLAUDE.md Rule #4: non-sensitive config in code)
DEFAULT_SIGNATURE_TYPE = 0  # EOA (normal MetaMask accounts)
DEFAULT_VERBOSE = True


def _get_polymarket_signature_type() -> int:
    """Get signature type. Default 0 (EOA) is in code per CLAUDE.md Rule #4."""
    sig_type = os.getenv("POLYMARKET_SIGNATURE_TYPE")
    if sig_type is None:
        return DEFAULT_SIGNATURE_TYPE
    try:
        return int(sig_type)
    except ValueError:
        logger.warning(
            f"Invalid POLYMARKET_SIGNATURE_TYPE '{sig_type}', using default {DEFAULT_SIGNATURE_TYPE}"
        )
        return DEFAULT_SIGNATURE_TYPE


def _get_mcp_credentials() -> Dict[str, Dict[str, Any]]:
    """
    Get MCP credentials from environment variables.

    Per CLAUDE.md Rule #4: Only sensitive data (private_key, funder) from .env.
    Non-sensitive config (signature_type, verbose) use code defaults.

    Returns credentials dict. Empty strings indicate missing required credentials.
    """
    return {
        "polymarket": {
            # Required: Must be in .env (sensitive)
            "private_key": os.getenv("POLYMARKET_PRIVATE_KEY") or "",
            "funder": os.getenv("POLYMARKET_FUNDER") or "",
            # Optional: For display only (not used for trading)
            "proxy_wallet": os.getenv("POLYMARKET_PROXY_WALLET") or "",
            # Defaults in code per CLAUDE.md Rule #4
            "signature_type": _get_polymarket_signature_type(),
            "verbose": os.getenv("MCP_VERBOSE", "").lower() != "false",
        }
    }


# MCP-specific credentials (Single Source of Truth as per CLAUDE.md)
# Note: Loaded at module import time. Restart server if environment changes.
MCP_CREDENTIALS: Dict[str, Dict[str, Any]] = _get_mcp_credentials()


class ExchangeSessionManager:
    """
    Manages exchange instances and their state.

    Singleton pattern - maintains one Exchange/ExchangeClient per exchange.
    Thread-safe for concurrent MCP requests.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """Ensure singleton instance with thread-safe initialization."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                # Initialize within the lock to prevent race condition
                cls._instance._exchanges: Dict[str, Exchange] = {}
                cls._instance._clients: Dict[str, ExchangeClient] = {}
                cls._instance._instance_lock = threading.RLock()
                logger.info("ExchangeSessionManager initialized")
        return cls._instance

    def __init__(self):
        """No-op: initialization done in __new__ to prevent race conditions."""
        pass

    def get_exchange(
        self, exchange_name: str, use_env: bool = True, validate: bool = True
    ) -> Exchange:
        """
        Get or create exchange instance.

        Args:
            exchange_name: Exchange name (polymarket, opinion, limitless)
            use_env: Load credentials from environment
            validate: Validate required credentials

        Returns:
            Exchange instance

        Raises:
            ValueError: If exchange unknown or credentials invalid
        """
        with self._instance_lock:
            if exchange_name not in self._exchanges:
                logger.info(f"Creating new exchange instance: {exchange_name}")

                # Use MCP credentials if available (Single Source of Truth)
                config_dict = MCP_CREDENTIALS.get(exchange_name.lower())
                if config_dict:
                    # Validate required credentials for Polymarket
                    if exchange_name.lower() == "polymarket":
                        if not config_dict.get("private_key"):
                            raise ValueError(
                                "POLYMARKET_PRIVATE_KEY environment variable is required. "
                                "Please set it in your .env file or environment."
                            )
                        if not config_dict.get("funder"):
                            raise ValueError(
                                "POLYMARKET_FUNDER environment variable is required. "
                                "Please set it in your .env file or environment."
                            )
                    logger.info(f"Using MCP credentials for {exchange_name}")
                    # Create exchange directly with dict config (MCP-specific)
                    from ...exchanges.limitless import Limitless
                    from ...exchanges.opinion import Opinion
                    from ...exchanges.polymarket import Polymarket

                    exchange_classes = {
                        "polymarket": Polymarket,
                        "opinion": Opinion,
                        "limitless": Limitless,
                    }

                    exchange_class = exchange_classes.get(exchange_name.lower())
                    if not exchange_class:
                        raise ValueError(f"Unknown exchange: {exchange_name}")

                    # Initialize with timeout to avoid blocking
                    logger.info(f"Initializing {exchange_name} (this may take a moment)...")
                    with ThreadPoolExecutor(max_workers=1) as executor:
                        future = executor.submit(exchange_class, config_dict)
                        try:
                            exchange = future.result(timeout=EXCHANGE_INIT_TIMEOUT)
                            logger.info(f"{exchange_name} initialized successfully")
                        except FutureTimeoutError:
                            logger.error(
                                f"{exchange_name} initialization timed out "
                                f"(>{EXCHANGE_INIT_TIMEOUT}s)"
                            )
                            raise TimeoutError(
                                f"{exchange_name} initialization timed out. "
                                "This may be due to network issues or API problems."
                            )
                else:
                    exchange = create_exchange(exchange_name, use_env=use_env, validate=validate)

                self._exchanges[exchange_name] = exchange
            return self._exchanges[exchange_name]

    def get_client(self, exchange_name: str) -> ExchangeClient:
        """
        Get or create ExchangeClient with state management.

        Args:
            exchange_name: Exchange name

        Returns:
            ExchangeClient instance with caching and WebSocket support
        """
        with self._instance_lock:
            if exchange_name not in self._clients:
                logger.info(f"Creating new ExchangeClient: {exchange_name}")
                exchange = self.get_exchange(exchange_name)
                logger.info(f"Creating client wrapper for {exchange_name}...")

                # Create client with timeout
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(ExchangeClient, exchange, 2.0, False)
                    try:
                        client = future.result(timeout=CLIENT_INIT_TIMEOUT)
                        logger.info(f"Client created for {exchange_name}")
                        self._clients[exchange_name] = client
                    except FutureTimeoutError:
                        logger.error(f"Client creation timed out for {exchange_name}")
                        raise TimeoutError(f"Client creation timed out for {exchange_name}")

            return self._clients[exchange_name]

    def has_exchange(self, exchange_name: str) -> bool:
        """Check if exchange instance exists."""
        return exchange_name in self._exchanges

    def cleanup(self):
        """Cleanup all exchange sessions (WebSocket, threads)."""
        logger.info("Cleaning up exchange sessions...")
        with self._instance_lock:
            failed_clients = []
            for name, client in list(self._clients.items()):
                try:
                    logger.info(f"Stopping client: {name}")
                    client.stop()
                except Exception as e:
                    logger.error(f"Error stopping client {name}: {e}")
                    failed_clients.append(name)

            # Only remove successfully cleaned items
            for name in list(self._clients.keys()):
                if name not in failed_clients:
                    del self._clients[name]
                    if name in self._exchanges:
                        del self._exchanges[name]

        logger.info("Exchange sessions cleaned up")
