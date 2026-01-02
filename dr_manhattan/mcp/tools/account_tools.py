"""Account management tools."""

from typing import Any, Dict, List, Optional

import requests

from dr_manhattan.utils import setup_logger

from ..session import ExchangeSessionManager
from ..utils import serialize_model, translate_error

logger = setup_logger(__name__)

exchange_manager = ExchangeSessionManager()

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

    # Try each RPC endpoint until one succeeds
    last_error = None
    for rpc_url in POLYGON_RPC_URLS:
        try:
            response = requests.post(rpc_url, json=payload, timeout=10)
            result = response.json()

            if "result" in result and result["result"] != "0x":
                # Convert hex to int and divide by 1e6 (USDC has 6 decimals)
                balance_wei = int(result["result"], 16)
                return balance_wei / 1e6
            elif "error" in result:
                last_error = result["error"]
                logger.warning(f"RPC error from {rpc_url}: {last_error}")
                continue
            else:
                return 0.0

        except requests.RequestException as e:
            last_error = str(e)
            logger.warning(f"RPC request failed for {rpc_url}: {e}")
            continue
        except (ValueError, KeyError) as e:
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
        # For Polymarket: Show both wallet balances and calculate NAV from funder wallet
        if exchange.lower() == "polymarket":
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
