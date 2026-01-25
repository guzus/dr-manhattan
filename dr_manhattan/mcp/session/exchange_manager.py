"""Exchange session manager."""

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any, Callable, Dict, Optional

from dr_manhattan.base import Exchange, ExchangeClient, create_exchange
from dr_manhattan.utils import setup_logger

logger = setup_logger(__name__)

# Callback to get credentials from request context (set by SSE server)
_context_credentials_getter: Optional[Callable[[], Optional[Dict[str, Any]]]] = None


def set_context_credentials_getter(getter: Optional[Callable[[], Optional[Dict[str, Any]]]]):
    """
    Set the callback function for getting credentials from request context.

    Used by SSE server to provide per-request credentials.

    Args:
        getter: Function that returns credentials dict or None
    """
    global _context_credentials_getter
    _context_credentials_getter = getter


def get_context_credentials() -> Optional[Dict[str, Any]]:
    """
    Get credentials from current request context if available.

    Returns:
        Credentials dict or None if not in SSE context
    """
    if _context_credentials_getter is not None:
        return _context_credentials_getter()
    return None


# Lock for credential operations (thread-safe access to MCP_CREDENTIALS)
_CREDENTIALS_LOCK = threading.Lock()

# Configuration constants (per CLAUDE.md Rule #4: non-sensitive config in code, not .env)
EXCHANGE_INIT_TIMEOUT = 10.0  # seconds - timeout for exchange initialization
CLIENT_INIT_TIMEOUT = 5.0  # seconds - timeout for client wrapper creation
DEFAULT_SIGNATURE_TYPE = 0  # EOA (normal MetaMask accounts)
# MCP requires verbose=False because verbose mode uses print() to stdout,
# which corrupts the JSON-RPC protocol. The checkmarks (✓) and debug info
# from polymarket.py would break Claude Desktop's message parsing.
DEFAULT_VERBOSE = False


def _run_with_timeout(func, args=(), kwargs=None, timeout=10.0, description="operation"):
    """
    Run a function with timeout using ThreadPoolExecutor.

    Provides consistent timeout handling with proper cleanup.

    Args:
        func: Function to execute
        args: Positional arguments
        kwargs: Keyword arguments
        timeout: Timeout in seconds
        description: Description for error messages

    Returns:
        Function result

    Raises:
        TimeoutError: If timeout exceeded
    """
    if kwargs is None:
        kwargs = {}

    executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(func, *args, **kwargs)
        return future.result(timeout=timeout)
    except FutureTimeoutError:
        logger.error(f"{description} timed out (>{timeout}s)")
        raise TimeoutError(f"{description} timed out. This may be due to network issues.")
    finally:
        # Always shutdown executor (wait=False for quick cleanup)
        executor.shutdown(wait=False, cancel_futures=True)


def _get_polymarket_signature_type() -> int:
    """Get signature type. Default 0 (EOA) is in code per CLAUDE.md Rule #4."""
    sig_type = os.getenv("POLYMARKET_SIGNATURE_TYPE")
    if sig_type is None:
        return DEFAULT_SIGNATURE_TYPE
    try:
        return int(sig_type)
    except ValueError:
        logger.warning(
            f"Invalid POLYMARKET_SIGNATURE_TYPE '{sig_type}', "
            f"using default {DEFAULT_SIGNATURE_TYPE}"
        )
        return DEFAULT_SIGNATURE_TYPE


def _get_mcp_credentials() -> Dict[str, Dict[str, Any]]:
    """
    Get MCP credentials from environment variables.

    Per CLAUDE.md Rule #4: Only sensitive data (private_key, funder) from .env.
    Non-sensitive config (signature_type, verbose) use code defaults.

    Note: Only Polymarket credentials are currently supported via MCP.
    Opinion and Limitless use the base project's environment variable loading
    via create_exchange() when MCP credentials are not configured.

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
            "verbose": DEFAULT_VERBOSE,
        }
        # Note: Opinion and Limitless are supported but use the base project's
        # credential loading (create_exchange with use_env=True) since they
        # have different credential requirements. See get_exchange() fallback.
    }


# MCP-specific credentials (Single Source of Truth as per CLAUDE.md)
# Note: Loaded at module import time. Restart server if environment changes.
#
# SECURITY WARNING: Private keys are stored in memory for the application lifetime.
# Best practices:
# - Use a dedicated wallet with limited funds for trading
# - Never share private keys or commit .env files
# - Consider using hardware wallets for large amounts
# - The cleanup() method should be called on shutdown to clear exchange instances
MCP_CREDENTIALS: Dict[str, Dict[str, Any]] = _get_mcp_credentials()


def _cleanup_rpc_session() -> None:
    """
    Cleanup global RPC session from account_tools.

    Called during ExchangeSessionManager cleanup to release HTTP connections.
    """
    try:
        from ..tools.account_tools import cleanup_rpc_session

        cleanup_rpc_session()
    except ImportError:
        pass  # Module not loaded yet


def _zeroize_credentials() -> None:
    """
    Clear sensitive credential data from memory.

    This provides defense-in-depth by clearing credentials on shutdown.
    Note: Python's garbage collection may not immediately free memory,
    but this reduces the window of exposure.
    Thread-safe: protected by _CREDENTIALS_LOCK.
    """
    global MCP_CREDENTIALS
    with _CREDENTIALS_LOCK:
        for exchange_creds in MCP_CREDENTIALS.values():
            if "private_key" in exchange_creds:
                exchange_creds["private_key"] = ""
            if "funder" in exchange_creds:
                exchange_creds["funder"] = ""
            if "proxy_wallet" in exchange_creds:
                exchange_creds["proxy_wallet"] = ""
        logger.info("Credentials zeroized")


def reload_credentials() -> Dict[str, Dict[str, Any]]:
    """
    Reload credentials from environment variables.

    This allows credential refresh without server restart.
    Note: Existing exchange instances must be recreated to use new credentials.
    Thread-safe: protected by _CREDENTIALS_LOCK.

    Returns:
        Updated credentials dictionary
    """
    global MCP_CREDENTIALS
    with _CREDENTIALS_LOCK:
        # Zeroize old credentials first (inline to avoid nested lock)
        for exchange_creds in MCP_CREDENTIALS.values():
            if "private_key" in exchange_creds:
                exchange_creds["private_key"] = ""
            if "funder" in exchange_creds:
                exchange_creds["funder"] = ""
            if "proxy_wallet" in exchange_creds:
                exchange_creds["proxy_wallet"] = ""
        # Load fresh credentials
        MCP_CREDENTIALS = _get_mcp_credentials()
        logger.info("Credentials reloaded from environment")
        return MCP_CREDENTIALS


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

    def _create_exchange_with_credentials(
        self, exchange_name: str, config_dict: Dict[str, Any]
    ) -> Exchange:
        """
        Create exchange instance with specific credentials.

        Internal method - does not cache the instance.

        Args:
            exchange_name: Exchange name
            config_dict: Credentials dictionary

        Returns:
            Exchange instance
        """
        from ...exchanges.limitless import Limitless
        from ...exchanges.opinion import Opinion
        from ...exchanges.polymarket import Polymarket
        from ...exchanges.polymarket_builder import PolymarketBuilder
        from ...exchanges.polymarket_operator import PolymarketOperator

        # For Polymarket, determine which mode to use:
        # 1. Operator mode (preferred): user provides wallet address, server signs
        # 2. Builder profile: user provides api_key, api_secret, api_passphrase
        # 3. Direct mode: user provides private_key (local server only)
        if exchange_name.lower() == "polymarket":
            has_user_address = config_dict.get("user_address")
            has_builder_creds = all(
                config_dict.get(k) for k in ("api_key", "api_secret", "api_passphrase")
            )
            has_private_key = config_dict.get("private_key")

            # Priority 1: Operator mode (user_address provided, server signs)
            if has_user_address and not has_private_key:
                logger.info(f"Using PolymarketOperator for {exchange_name} (Operator mode)")
                config_dict["verbose"] = DEFAULT_VERBOSE
                return _run_with_timeout(
                    PolymarketOperator,
                    args=(config_dict,),
                    timeout=EXCHANGE_INIT_TIMEOUT,
                    description=f"{exchange_name} Operator initialization",
                )

            # Priority 2: Builder profile (api credentials provided)
            if has_builder_creds and not has_private_key:
                logger.info(f"Using PolymarketBuilder for {exchange_name} (Builder profile)")
                config_dict["verbose"] = DEFAULT_VERBOSE
                return _run_with_timeout(
                    PolymarketBuilder,
                    args=(config_dict,),
                    timeout=EXCHANGE_INIT_TIMEOUT,
                    description=f"{exchange_name} Builder initialization",
                )

        exchange_classes = {
            "polymarket": Polymarket,
            "opinion": Opinion,
            "limitless": Limitless,
        }

        exchange_class = exchange_classes.get(exchange_name.lower())
        if not exchange_class:
            raise ValueError(f"Unknown exchange: {exchange_name}")

        # Ensure verbose is False for MCP
        config_dict["verbose"] = DEFAULT_VERBOSE

        logger.info(f"Initializing {exchange_name} with provided credentials...")
        exchange = _run_with_timeout(
            exchange_class,
            args=(config_dict,),
            timeout=EXCHANGE_INIT_TIMEOUT,
            description=f"{exchange_name} initialization",
        )
        logger.info(f"{exchange_name} initialized successfully")
        return exchange

    def get_exchange(
        self, exchange_name: str, use_env: bool = True, validate: bool = True
    ) -> Exchange:
        """
        Get or create exchange instance.

        Checks for context credentials first (SSE mode), then falls back
        to environment credentials (local mode).

        Args:
            exchange_name: Exchange name (polymarket, opinion, limitless)
            use_env: Load credentials from environment
            validate: Validate required credentials

        Returns:
            Exchange instance

        Raises:
            ValueError: If exchange unknown or credentials invalid
        """
        # Check for context credentials (SSE mode - per-request credentials)
        context_creds = get_context_credentials()
        if context_creds:
            exchange_creds = context_creds.get(exchange_name.lower())
            if exchange_creds:
                # Validate required credentials (transport-agnostic messages)
                if exchange_name.lower() == "polymarket":
                    # SSE mode supports two authentication methods:
                    # 1. Operator mode: user provides wallet address, server signs on behalf
                    # 2. Builder profile: user provides api_key, api_secret, api_passphrase
                    has_user_address = exchange_creds.get("user_address")
                    has_builder_creds = all(
                        exchange_creds.get(k) for k in ("api_key", "api_secret", "api_passphrase")
                    )
                    has_private_key = exchange_creds.get("private_key")

                    if not has_user_address and not has_builder_creds and not has_private_key:
                        raise ValueError(
                            f"Missing credentials for {exchange_name}. "
                            "Please provide either: "
                            "(1) your wallet address (X-Polymarket-Wallet-Address header), or "
                            "(2) Builder profile credentials (api_key, api_secret, api_passphrase)."
                        )
                elif exchange_name.lower() in ("limitless", "opinion"):
                    # Other exchanges still require private_key (not supported in SSE write mode)
                    if not exchange_creds.get("private_key"):
                        raise ValueError(
                            f"Missing private_key credential for {exchange_name}. "
                            "Please provide your private key."
                        )

                logger.info(f"Using context credentials for {exchange_name} (SSE mode)")
                # Create exchange without caching (each user has different credentials)
                return self._create_exchange_with_credentials(exchange_name, exchange_creds)

        # Fall back to cached exchange with environment credentials (local mode)
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
                    exchange = self._create_exchange_with_credentials(exchange_name, config_dict)
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

                # Create client with timeout using helper
                client = _run_with_timeout(
                    ExchangeClient,
                    args=(exchange, 2.0, False),
                    timeout=CLIENT_INIT_TIMEOUT,
                    description=f"Client creation for {exchange_name}",
                )
                logger.info(f"Client created for {exchange_name}")
                self._clients[exchange_name] = client

            return self._clients[exchange_name]

    def has_exchange(self, exchange_name: str) -> bool:
        """Check if exchange instance exists."""
        return exchange_name in self._exchanges

    def refresh_credentials(self, exchange_name: Optional[str] = None) -> bool:
        """
        Refresh credentials from environment and recreate exchange instances.

        This allows credential rotation without server restart.
        Thread-safe: entire operation is atomic to prevent race conditions.

        Args:
            exchange_name: Optional - refresh only this exchange.
                          If None, refresh all exchanges.

        Returns:
            True if refresh successful
        """
        logger.info(f"Refreshing credentials for: {exchange_name or 'all exchanges'}")

        with self._instance_lock:
            # Determine which exchanges to refresh
            exchanges_to_refresh = (
                [exchange_name] if exchange_name else list(self._exchanges.keys())
            )

            # Stop and remove affected clients/exchanges
            for name in exchanges_to_refresh:
                if name in self._clients:
                    try:
                        self._clients[name].stop()
                    except Exception as e:
                        logger.warning(f"Error stopping client {name} during refresh: {e}")
                    del self._clients[name]

                if name in self._exchanges:
                    del self._exchanges[name]

            # Reload credentials inside lock to prevent race condition
            # where another thread creates exchange with stale credentials
            reload_credentials()

            logger.info("Credentials refreshed. Exchanges will be recreated on next access.")
            return True

    def cleanup(self, zeroize: bool = True):
        """
        Cleanup all exchange sessions (WebSocket, threads, credentials).

        Args:
            zeroize: If True, also clear credential data from memory
        """
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

        # Cleanup global RPC session (connection pooling)
        _cleanup_rpc_session()

        # Zeroize credentials on shutdown (defense in depth)
        if zeroize:
            _zeroize_credentials()

        logger.info("Exchange sessions cleaned up")
