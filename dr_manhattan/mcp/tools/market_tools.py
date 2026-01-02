"""Market discovery and data tools."""

from typing import Any, Dict, List, Optional

from ..session import ExchangeSessionManager
from ..utils import serialize_model, translate_error

exchange_manager = ExchangeSessionManager()


def fetch_markets(exchange: str, params: Optional[Dict[str, Any]] = None) -> List[Dict]:
    """
    Fetch all available markets from an exchange.

    Mirrors: Exchange.fetch_markets()

    Args:
        exchange: Exchange name (polymarket, opinion, limitless)
        params: Optional filters
            - limit: int (max markets to return)
            - offset: int (pagination offset)
            - closed: bool (include closed markets)
            - active: bool (only active markets)

    Returns:
        List of Market objects as dicts

    Example:
        >>> markets = fetch_markets("polymarket", {"limit": 10})
    """
    try:
        exch = exchange_manager.get_exchange(exchange)
        markets = exch.fetch_markets(params or {})
        return [serialize_model(m) for m in markets]

    except Exception as e:
        raise translate_error(e, {"exchange": exchange})


def fetch_market(exchange: str, market_id: str) -> Dict[str, Any]:
    """
    Fetch a specific market by ID.

    Mirrors: Exchange.fetch_market()

    Args:
        exchange: Exchange name
        market_id: Market identifier

    Returns:
        Market object as dict
    """
    try:
        exch = exchange_manager.get_exchange(exchange)
        market = exch.fetch_market(market_id)
        return serialize_model(market)

    except Exception as e:
        raise translate_error(e, {"exchange": exchange, "market_id": market_id})


def fetch_markets_by_slug(exchange: str, slug: str) -> List[Dict]:
    """
    Fetch markets by slug or URL.

    Mirrors: Exchange.fetch_markets_by_slug()
    Supported: Polymarket, Limitless

    Args:
        exchange: Exchange name
        slug: Market slug or full URL

    Returns:
        List of Market objects

    Example:
        >>> markets = fetch_markets_by_slug("polymarket", "trump-2024")
        >>> markets = fetch_markets_by_slug("polymarket",
        ...     "https://polymarket.com/event/trump-2024")
    """
    try:
        exch = exchange_manager.get_exchange(exchange)

        if not hasattr(exch, "fetch_markets_by_slug"):
            raise ValueError(f"{exchange} does not support fetch_markets_by_slug")

        markets = exch.fetch_markets_by_slug(slug)
        return [serialize_model(m) for m in markets]

    except Exception as e:
        raise translate_error(e, {"exchange": exchange, "slug": slug})


def find_tradeable_market(
    exchange: str,
    binary: bool = True,
    limit: int = 100,
    min_liquidity: float = 0.0,
) -> Optional[Dict]:
    """
    Find a suitable market for trading.

    Mirrors: Exchange.find_tradeable_market()

    Args:
        exchange: Exchange name
        binary: Only return binary markets
        limit: Maximum markets to search
        min_liquidity: Minimum liquidity required

    Returns:
        Market object or None if no suitable market found
    """
    try:
        exch = exchange_manager.get_exchange(exchange)
        market = exch.find_tradeable_market(binary=binary, limit=limit, min_liquidity=min_liquidity)

        if market:
            return serialize_model(market)
        return None

    except Exception as e:
        raise translate_error(e, {"exchange": exchange})


def find_crypto_hourly_market(
    exchange: str,
    token_symbol: Optional[str] = None,
    min_liquidity: float = 0.0,
    is_active: bool = True,
) -> Optional[Dict]:
    """
    Find crypto hourly price market.

    Mirrors: Exchange.find_crypto_hourly_market()
    Best support: Polymarket (with TAG_1H)

    Args:
        exchange: Exchange name
        token_symbol: Filter by token (BTC, ETH, SOL, etc.)
        min_liquidity: Minimum liquidity
        is_active: Only markets currently active

    Returns:
        Tuple of (Market, CryptoHourlyMarket) as dict or None

    Example:
        >>> result = find_crypto_hourly_market("polymarket", token_symbol="BTC")
        >>> if result:
        ...     market = result["market"]
        ...     crypto_info = result["crypto_hourly"]
    """
    try:
        exch = exchange_manager.get_exchange(exchange)
        result = exch.find_crypto_hourly_market(
            token_symbol=token_symbol,
            min_liquidity=min_liquidity,
            is_active=is_active,
        )

        if result:
            market, crypto_hourly = result
            return {
                "market": serialize_model(market),
                "crypto_hourly": serialize_model(crypto_hourly),
            }
        return None

    except Exception as e:
        raise translate_error(e, {"exchange": exchange, "token_symbol": token_symbol})


def parse_market_identifier(identifier: str) -> str:
    """
    Parse market slug from URL.

    Mirrors: Polymarket.parse_market_identifier()

    Args:
        identifier: Market slug or full URL

    Returns:
        Market slug

    Example:
        >>> parse_market_identifier("https://polymarket.com/event/trump-2024")
        'trump-2024'
        >>> parse_market_identifier("trump-2024")
        'trump-2024'
    """
    try:
        from dr_manhattan.exchanges.polymarket import Polymarket

        return Polymarket.parse_market_identifier(identifier)

    except Exception as e:
        raise translate_error(e, {"identifier": identifier})


def get_tag_by_slug(slug: str) -> Dict[str, Any]:
    """
    Get Polymarket tag information.

    Mirrors: Polymarket.get_tag_by_slug()
    Polymarket only

    Args:
        slug: Tag slug

    Returns:
        Tag object as dict
    """
    try:
        exch = exchange_manager.get_exchange("polymarket")

        if not hasattr(exch, "get_tag_by_slug"):
            raise ValueError("Only Polymarket supports tags")

        tag = exch.get_tag_by_slug(slug)
        return serialize_model(tag)

    except Exception as e:
        raise translate_error(e, {"slug": slug})


def fetch_token_ids(exchange: str, market_id: str) -> List[str]:
    """
    Fetch token IDs for a market.

    Mirrors: Exchange.fetch_token_ids()

    Args:
        exchange: Exchange name
        market_id: Market ID or condition ID

    Returns:
        List of token IDs
    """
    try:
        exch = exchange_manager.get_exchange(exchange)

        if hasattr(exch, "fetch_token_ids"):
            return exch.fetch_token_ids(market_id)
        else:
            # Fallback: get from market metadata
            market = exch.fetch_market(market_id)
            return market.metadata.get("clobTokenIds", [])

    except Exception as e:
        raise translate_error(e, {"exchange": exchange, "market_id": market_id})


def get_orderbook(exchange: str, token_id: str) -> Dict[str, Any]:
    """
    Get orderbook for a token.

    Mirrors: Exchange.get_orderbook()

    Args:
        exchange: Exchange name
        token_id: Token ID

    Returns:
        Orderbook dict with bids, asks, timestamp

    Example:
        >>> orderbook = get_orderbook("polymarket", "123456")
        >>> print(orderbook["bids"][0])  # Best bid
        [0.52, 100]  # [price, size]
    """
    try:
        exch = exchange_manager.get_exchange(exchange)
        orderbook = exch.get_orderbook(token_id)
        return serialize_model(orderbook)

    except Exception as e:
        raise translate_error(e, {"exchange": exchange, "token_id": token_id})


def get_best_bid_ask(exchange: str, token_id: str) -> Dict[str, Any]:
    """
    Get best bid and ask prices.

    Mirrors: ExchangeClient.get_best_bid_ask()
    Uses WebSocket cache if available.

    Args:
        exchange: Exchange name
        token_id: Token ID

    Returns:
        Dict with best_bid and best_ask

    Example:
        >>> result = get_best_bid_ask("polymarket", "123456")
        >>> print(f"Spread: {result['best_ask'] - result['best_bid']}")
    """
    try:
        client = exchange_manager.get_client(exchange)
        best_bid, best_ask = client.get_best_bid_ask(token_id)

        return {"best_bid": best_bid, "best_ask": best_ask}

    except Exception as e:
        raise translate_error(e, {"exchange": exchange, "token_id": token_id})
