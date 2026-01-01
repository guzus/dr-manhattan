"""Exchange session manager."""

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Any, Dict, Optional

from dr_manhattan.base import Exchange, ExchangeClient, create_exchange
from dr_manhattan.utils import setup_logger

logger = setup_logger(__name__)

# MCP-specific credentials (Single Source of Truth as per CLAUDE.md)
# Using dict format to include MCP-specific settings like signature_type
# Read from environment variables for security
MCP_CREDENTIALS: Dict[str, Dict[str, Any]] = {
    "polymarket": {
        "private_key": os.getenv("POLYMARKET_PRIVATE_KEY", ""),
        "funder": os.getenv("POLYMARKET_FUNDER", ""),
        "proxy_wallet": os.getenv("POLYMARKET_PROXY_WALLET", ""),
        "signature_type": int(os.getenv("POLYMARKET_SIGNATURE_TYPE", "0")),
        "verbose": True,
    }
}


class ExchangeSessionManager:
    """
    Manages exchange instances and their state.

    Singleton pattern - maintains one Exchange/ExchangeClient per exchange.
    Thread-safe for concurrent MCP requests.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """Ensure singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """Initialize session manager."""
        if self._initialized:
            return

        self._exchanges: Dict[str, Exchange] = {}
        self._clients: Dict[str, ExchangeClient] = {}
        # Use RLock (reentrant lock) to allow nested locking
        self._instance_lock = threading.RLock()
        self._initialized = True

        logger.info("ExchangeSessionManager initialized")

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
                    logger.info(f"Using MCP credentials for {exchange_name}")
                    # Create exchange directly with dict config (MCP-specific)
                    from ...exchanges.polymarket import Polymarket
                    from ...exchanges.opinion import Opinion
                    from ...exchanges.limitless import Limitless

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
                            exchange = future.result(timeout=10.0)  # 10 second timeout
                            logger.info(f"✓ {exchange_name} initialized successfully")
                        except FutureTimeoutError:
                            logger.error(f"✗ {exchange_name} initialization timed out (>10s)")
                            raise TimeoutError(
                                f"{exchange_name} initialization timed out. "
                                "This may be due to network issues or API problems."
                            )
                else:
                    exchange = create_exchange(
                        exchange_name, use_env=use_env, validate=validate
                    )

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
                        client = future.result(timeout=5.0)
                        logger.info(f"✓ Client created for {exchange_name}")
                        self._clients[exchange_name] = client
                    except FutureTimeoutError:
                        logger.error(f"✗ Client creation timed out for {exchange_name}")
                        raise TimeoutError(f"Client creation timed out for {exchange_name}")

            return self._clients[exchange_name]

    def has_exchange(self, exchange_name: str) -> bool:
        """Check if exchange instance exists."""
        return exchange_name in self._exchanges

    def cleanup(self):
        """Cleanup all exchange sessions (WebSocket, threads)."""
        logger.info("Cleaning up exchange sessions...")
        with self._instance_lock:
            for name, client in self._clients.items():
                try:
                    logger.info(f"Stopping client: {name}")
                    client.stop()
                except Exception as e:
                    logger.error(f"Error stopping client {name}: {e}")

            self._exchanges.clear()
            self._clients.clear()

        logger.info("Exchange sessions cleaned up")
