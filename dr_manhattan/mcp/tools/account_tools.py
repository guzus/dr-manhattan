"""Account management tools."""

import threading
from typing import Any, Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from dr_manhattan.utils import setup_logger

from ..session import ExchangeSessionManager
from ..utils import (
    serialize_model,
    translate_error,
    validate_exchange,
    validate_market_id,
    validate_optional_market_id,
)

logger = setup_logger(__name__)

exchange_manager = ExchangeSessionManager()

# Lock for RPC session creation (prevents race condition)
_RPC_SESSION_LOCK = threading.Lock()

# Polygon USDC contract address (bridged USDC on Polygon PoS)
POLYGON_USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"

# ERC20 balanceOf(address) function selector (keccak256("balanceOf(address)")[:4])
ERC20_BALANCE_OF_SELECTOR = "0x70a08231"

# Polygon RPC endpoints for balance queries (per CLAUDE.md Rule #4: config in code)
# Primary endpoint first, fallbacks follow. All are public endpoints.
POLYGON_RPC_URLS = [
    "https://polygon-rpc.com",
    "https://rpc-mainnet.matic.quiknode.pro",
    "https://polygon.llamarpc.com",
]

# Connection pool configuration (per CLAUDE.md Rule #4: config in code)
RPC_POOL_CONNECTIONS = 10  # Number of connection pools to cache
RPC_POOL_MAXSIZE = 20  # Max connections per pool
RPC_RETRY_COUNT = 3  # Number of retries on failure
RPC_RETRY_BACKOFF = 0.5  # Backoff factor between retries

# Reusable session for connection pooling (improves performance)
_RPC_SESSION: Optional[requests.Session] = None


def _get_rpc_session() -> requests.Session:
    """
    Get or create reusable HTTP session with connection pooling and retry.

    Features:
    - Connection pooling for better performance
    - Automatic retry on transient failures
    - Exponential backoff between retries
    Thread-safe: protected by _RPC_SESSION_LOCK.
    """
    global _RPC_SESSION
    # Double-checked locking pattern for thread safety
    if _RPC_SESSION is None:
        with _RPC_SESSION_LOCK:
            # Re-check inside lock (another thread may have created it)
            if _RPC_SESSION is None:
                session = requests.Session()

                # Configure retry strategy
                retry_strategy = Retry(
                    total=RPC_RETRY_COUNT,
                    backoff_factor=RPC_RETRY_BACKOFF,
                    status_forcelist=[429, 500, 502, 503, 504],
                    allowed_methods=["POST"],  # RPC uses POST
                )

                # Configure adapter with connection pooling
                adapter = HTTPAdapter(
                    pool_connections=RPC_POOL_CONNECTIONS,
                    pool_maxsize=RPC_POOL_MAXSIZE,
                    max_retries=retry_strategy,
                )

                session.mount("https://", adapter)
                session.mount("http://", adapter)
                logger.info(
                    f"RPC session created: pool_size={RPC_POOL_MAXSIZE}, retries={RPC_RETRY_COUNT}"
                )
                _RPC_SESSION = session

    return _RPC_SESSION


def cleanup_rpc_session() -> None:
    """
    Cleanup global RPC session.

    Called by ExchangeSessionManager.cleanup() to release HTTP connections.
    Thread-safe: protected by _RPC_SESSION_LOCK.
    """
    global _RPC_SESSION
    with _RPC_SESSION_LOCK:
        if _RPC_SESSION is not None:
            try:
                _RPC_SESSION.close()
                logger.info("RPC session closed")
            except Exception as e:
                logger.warning(f"Error closing RPC session: {e}")
            finally:
                _RPC_SESSION = None


def _validate_rpc_response(result: str, address: str) -> bool:
    """
    Validate RPC response is a valid hex balance.

    Args:
        result: Hex string from RPC (e.g., "0x1234...")
        address: Original address for context in error messages

    Returns:
        True if valid, False otherwise
    """
    if not result or not isinstance(result, str):
        return False
    # Must be hex string starting with 0x
    if not result.startswith("0x"):
        logger.warning(f"Invalid RPC response format for {address}: {result[:50]}")
        return False
    # Must contain only valid hex characters after 0x
    try:
        int(result, 16)
        return True
    except ValueError:
        logger.warning(f"Invalid hex in RPC response for {address}: {result[:50]}")
        return False


def get_usdc_balance_polygon(address: str) -> Optional[float]:
    """
    Query USDC balance on Polygon for a specific address.

    Args:
        address: Ethereum address to query

    Returns:
        USDC balance as float, or None if query failed
    """
    if not address or not address.startswith("0x"):
        logger.warning(f"Invalid address format: {address}")
        return None

    # Build ERC20 balanceOf call data
    padded_address = address[2:].zfill(64)  # Remove 0x and pad to 32 bytes
    data = ERC20_BALANCE_OF_SELECTOR + padded_address

    payload = {
        "jsonrpc": "2.0",
        "method": "eth_call",
        "params": [
            {
                "to": POLYGON_USDC_ADDRESS,
                "data": data,
            },
            "latest",
        ],
        "id": 1,
    }

    # Try each RPC endpoint until one succeeds (with connection pooling)
    session = _get_rpc_session()
    last_error = None
    for rpc_url in POLYGON_RPC_URLS:
        try:
            response = session.post(rpc_url, json=payload, timeout=10)

            # Parse JSON response with explicit error handling
            try:
                result = response.json()
            except ValueError as e:
                last_error = f"Invalid JSON response: {e}"
                logger.warning(f"RPC returned invalid JSON from {rpc_url}: {e}")
                continue

            # Validate response structure (must be a dict)
            if not isinstance(result, dict):
                last_error = f"Unexpected response type: {type(result).__name__}"
                logger.warning(f"RPC returned non-dict from {rpc_url}: {type(result)}")
                continue

            if "result" in result:
                rpc_result = result["result"]
                # Validate RPC response format
                if rpc_result == "0x" or rpc_result == "0x0":
                    return 0.0
                if not _validate_rpc_response(rpc_result, address):
                    last_error = f"Invalid response format: {str(rpc_result)[:50]}"
                    continue
                # Convert hex to int and divide by 1e6 (USDC has 6 decimals)
                balance_wei = int(rpc_result, 16)
                return balance_wei / 1e6
            elif "error" in result:
                last_error = result["error"]
                logger.warning(f"RPC error from {rpc_url}: {last_error}")
                continue
            else:
                last_error = f"Unexpected response format: {result}"
                continue

        except requests.RequestException as e:
            last_error = str(e)
            logger.warning(f"RPC request failed for {rpc_url}: {e}")
            continue
        except (ValueError, KeyError, TypeError) as e:
            last_error = str(e)
            logger.warning(f"Failed to parse RPC response from {rpc_url}: {e}")
            continue

    # All RPCs failed
    logger.error(f"All RPC endpoints failed for balance query. Last error: {last_error}")
    return None


def fetch_balance(exchange: str) -> Dict[str, Any]:
    """
    Fetch account balance.

    Mirrors: Exchange.fetch_balance()

    Args:
        exchange: Exchange name

    Returns:
        Balance dictionary with wallet info (e.g., {"USDC": 1000.0, "wallet_address": "0x..."})
        For Polymarket: Shows both funder and proxy wallet balances, with clear indication
        that trading uses the funder wallet.

    Example:
        >>> balance = fetch_balance("polymarket")
        >>> print(f"Trading balance: ${balance['funder_balance']:.2f}")
    """
    try:
        exchange = validate_exchange(exchange)
        exch = exchange_manager.get_exchange(exchange)

        # For Polymarket: Show both funder and proxy wallet balances
        if exchange.lower() == "polymarket":
            from ..session.exchange_manager import MCP_CREDENTIALS

            proxy_wallet = MCP_CREDENTIALS.get("polymarket", {}).get("proxy_wallet", "")
            funder_wallet = exch.funder if hasattr(exch, "funder") else ""

            # Query both wallet balances (None means query failed)
            funder_balance = get_usdc_balance_polygon(funder_wallet) if funder_wallet else None
            proxy_balance = get_usdc_balance_polygon(proxy_wallet) if proxy_wallet else None

            # Fail fast: if funder balance query failed, raise error
            if funder_balance is None:
                raise ValueError(
                    f"Failed to query funder wallet balance from all RPC endpoints. "
                    f"Wallet: {funder_wallet}. Check network connectivity."
                )

            result = {
                "funder_balance": funder_balance,
                "funder_wallet": funder_wallet,
            }

            # Add proxy wallet info if configured (proxy failure is non-fatal)
            if proxy_wallet:
                result["proxy_balance"] = proxy_balance
                result["proxy_wallet"] = proxy_wallet
                if proxy_balance is None:
                    result["proxy_balance_error"] = "Failed to query proxy balance from RPC"

            # Add clear message about which wallet is used for trading
            result["trading_wallet"] = "funder"
            result["note"] = (
                "Trading uses funder wallet balance. Ensure funder wallet has sufficient USDC."
            )

            return result

        # Default: Use base project's fetch_balance
        client = exchange_manager.get_client(exchange)
        balance = client.fetch_balance()
        result = serialize_model(balance)

        # Add wallet address info for Polymarket
        if exchange.lower() == "polymarket":
            if hasattr(exch, "_clob_client") and exch._clob_client:
                try:
                    derived_address = exch._clob_client.get_address()
                    result["derived_address"] = derived_address
                except Exception:
                    pass

            if hasattr(exch, "funder") and exch.funder:
                result["funder"] = exch.funder

        return result

    except Exception as e:
        raise translate_error(e, {"exchange": exchange}) from e


def fetch_positions(exchange: str, market_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Fetch current positions.

    Mirrors: Exchange.fetch_positions()

    Args:
        exchange: Exchange name
        market_id: Optional market filter

    Returns:
        List of Position objects

    Example:
        >>> positions = fetch_positions("polymarket")
        >>> for pos in positions:
        ...     print(f"{pos['outcome']}: {pos['size']} @ {pos['average_price']}")
    """
    try:
        exchange = validate_exchange(exchange)
        market_id = validate_optional_market_id(market_id)
        client = exchange_manager.get_client(exchange)
        positions = client.fetch_positions(market_id=market_id)
        return [serialize_model(p) for p in positions]

    except Exception as e:
        raise translate_error(e, {"exchange": exchange, "market_id": market_id}) from e


def fetch_positions_for_market(exchange: str, market_id: str) -> List[Dict[str, Any]]:
    """
    Fetch positions for specific market (with token IDs).

    Mirrors: ExchangeClient.fetch_positions_for_market()

    Args:
        exchange: Exchange name
        market_id: Market identifier

    Returns:
        List of Position objects for this market
    """
    try:
        exchange = validate_exchange(exchange)
        market_id = validate_market_id(market_id)
        client = exchange_manager.get_client(exchange)

        # Need market object
        exch = exchange_manager.get_exchange(exchange)
        market = exch.fetch_market(market_id)

        positions = client.fetch_positions_for_market(market)
        return [serialize_model(p) for p in positions]

    except Exception as e:
        raise translate_error(e, {"exchange": exchange, "market_id": market_id}) from e


def calculate_nav(exchange: str, market_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Calculate Net Asset Value.

    Mirrors: ExchangeClient.calculate_nav()

    Args:
        exchange: Exchange name
        market_id: Optional market filter for positions

    Returns:
        NAV object with breakdown
        For Polymarket: Shows both funder and proxy wallet balances, with NAV based on funder wallet

    Example:
        >>> nav = calculate_nav("polymarket")
        >>> print(f"NAV: ${nav['nav']:.2f}")
        >>> print(f"Funder Cash: ${nav['funder_balance']:.2f}")
        >>> print(f"Positions: ${nav['positions_value']:.2f}")
    """
    try:
        exchange = validate_exchange(exchange)
        market_id = validate_optional_market_id(market_id)

        # For Polymarket: Show both wallet balances and calculate NAV from funder wallet
        if exchange == "polymarket":
            from ..session.exchange_manager import MCP_CREDENTIALS

            exch = exchange_manager.get_exchange(exchange)
            proxy_wallet = MCP_CREDENTIALS.get("polymarket", {}).get("proxy_wallet", "")
            funder_wallet = exch.funder if hasattr(exch, "funder") else ""

            # Query both wallet balances (None means query failed)
            funder_balance = get_usdc_balance_polygon(funder_wallet) if funder_wallet else None
            proxy_balance = get_usdc_balance_polygon(proxy_wallet) if proxy_wallet else None

            # Get positions (still use base client for this)
            client = exchange_manager.get_client(exchange)
            positions = client.fetch_positions(market_id=None if not market_id else market_id)

            # Calculate positions value
            positions_value = sum(getattr(p, "value", 0.0) for p in positions)

            # Fail fast: if funder balance query failed, raise error
            if funder_balance is None:
                raise ValueError(
                    f"Failed to query funder wallet balance from all RPC endpoints. "
                    f"Wallet: {funder_wallet}. Cannot calculate NAV."
                )

            # NAV is based on funder wallet (trading wallet)
            nav = funder_balance + positions_value

            result = {
                "nav": nav,
                "funder_balance": funder_balance,
                "funder_wallet": funder_wallet,
                "positions_value": positions_value,
                "positions": [serialize_model(p) for p in positions],
                "trading_wallet": "funder",
                "note": "NAV calculated using funder wallet balance (trading wallet)",
            }

            # Add proxy wallet info if configured (proxy failure is non-fatal)
            if proxy_wallet:
                result["proxy_balance"] = proxy_balance
                result["proxy_wallet"] = proxy_wallet
                if proxy_balance is None:
                    result["proxy_balance_error"] = "Failed to query proxy balance from RPC"

            return result

        # Default: Use base project's calculate_nav
        client = exchange_manager.get_client(exchange)

        # Get market if specified
        market = None
        if market_id:
            exch = exchange_manager.get_exchange(exchange)
            market = exch.fetch_market(market_id)

        nav = client.calculate_nav(market)
        return serialize_model(nav)

    except Exception as e:
        raise translate_error(e, {"exchange": exchange, "market_id": market_id}) from e
