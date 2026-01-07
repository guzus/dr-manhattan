"""Market discovery and data tools."""

from typing import Any, Dict, List, Optional

from ..session import ExchangeSessionManager
from ..utils import (
    serialize_model,
    translate_error,
    validate_exchange,
    validate_market_id,
    validate_slug,
    validate_token_id,
)

exchange_manager = ExchangeSessionManager()


# Default pagination settings (per CLAUDE.md Rule #4: config in code)
DEFAULT_PAGE_LIMIT = 100  # Default number of markets per page
MAX_PAGE_LIMIT = 500  # Maximum allowed limit
SEARCH_RESULT_LIMIT = 20  # Max results for search


def search_markets(
    exchange: str,
    query: str,
    limit: int = SEARCH_RESULT_LIMIT,
) -> Dict[str, Any]:
    """
    Search markets by keyword in title/question.

    Args:
        exchange: Exchange name (polymarket, opinion, limitless)
        query: Search keyword (case-insensitive)
        limit: Max results to return (default: 20)

    Returns:
        Dict with matching markets:
        {
            "markets": [...],
            "query": "elon musk",
            "count": 5
        }

    Example:
        >>> result = search_markets("polymarket", "elon musk")
        >>> for m in result["markets"]:
        ...     print(m["question"])
    """
    try:
        exchange = validate_exchange(exchange)

        if not query or not isinstance(query, str):
            raise ValueError("query must be a non-empty string")

        query = query.strip().lower()

        if limit <= 0:
            limit = SEARCH_RESULT_LIMIT
        elif limit > 100:
            limit = 100

        exch = exchange_manager.get_exchange(exchange)
        all_markets = exch.fetch_markets({})

        # Filter markets by keyword in question or slug (from metadata)
        matching = []
        for market in all_markets:
            question = (market.question or "").lower()
            slug = (market.metadata.get("slug") or "").lower()
            if query in question or query in slug:
                matching.append(serialize_model(market))
                if len(matching) >= limit:
                    break

        return {
            "markets": matching,
            "query": query,
            "count": len(matching),
        }

    except Exception as e:
        raise translate_error(e, {"exchange": exchange, "query": query}) from e


def fetch_markets(
    exchange: str,
    params: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = None,
    offset: int = 0,
) -> Dict[str, Any]:
    """
    Fetch markets from an exchange with pagination support.

    Mirrors: Exchange.fetch_markets()

    Args:
        exchange: Exchange name (polymarket, opinion, limitless)
        params: Optional filters passed to exchange
            - closed: bool (include closed markets)
            - active: bool (only active markets)
        limit: Max markets to return (default: 100, max: 500)
        offset: Pagination offset (default: 0)

    Returns:
        Dict with markets and pagination info:
        {
            "markets": [...],
            "pagination": {
                "limit": 100,
                "offset": 0,
                "count": 100,
                "has_more": true
            }
        }

    Example:
        >>> result = fetch_markets("polymarket", limit=50)
        >>> markets = result["markets"]
        >>> if result["pagination"]["has_more"]:
        ...     next_page = fetch_markets("polymarket", limit=50, offset=50)
    """
    try:
        exchange = validate_exchange(exchange)

        # Validate and apply pagination defaults
        if limit is None:
            limit = DEFAULT_PAGE_LIMIT
        elif not isinstance(limit, int) or limit <= 0:
            raise ValueError("limit must be a positive integer")
        elif limit > MAX_PAGE_LIMIT:
            limit = MAX_PAGE_LIMIT

        if not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a non-negative integer")

        exch = exchange_manager.get_exchange(exchange)

        # Merge pagination into params
        merged_params = dict(params or {})
        merged_params["limit"] = limit
        merged_params["offset"] = offset

        markets = exch.fetch_markets(merged_params)
        serialized = [serialize_model(m) for m in markets]

        # Determine if there are more results
        # If we got exactly limit results, there might be more
        has_more = len(serialized) >= limit

        return {
            "markets": serialized,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "count": len(serialized),
                "has_more": has_more,
            },
        }

    except Exception as e:
        raise translate_error(e, {"exchange": exchange}) from e


def fetch_markets_list(exchange: str, params: Optional[Dict[str, Any]] = None) -> List[Dict]:
    """
    Fetch all available markets from an exchange (simple list, no pagination).

    This is the legacy interface. Use fetch_markets() for pagination support.

    Args:
        exchange: Exchange name (polymarket, opinion, limitless)
        params: Optional filters

    Returns:
        List of Market objects as dicts
    """
    try:
        exchange = validate_exchange(exchange)
        exch = exchange_manager.get_exchange(exchange)
        markets = exch.fetch_markets(params or {})
        return [serialize_model(m) for m in markets]

    except Exception as e:
        raise translate_error(e, {"exchange": exchange}) from e


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
        exchange = validate_exchange(exchange)
        market_id = validate_market_id(market_id)

        exch = exchange_manager.get_exchange(exchange)
        market = exch.fetch_market(market_id)
        return serialize_model(market)

    except Exception as e:
        raise translate_error(e, {"exchange": exchange, "market_id": market_id}) from e


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
        exchange = validate_exchange(exchange)
        slug = validate_slug(slug)

        exch = exchange_manager.get_exchange(exchange)

        if not hasattr(exch, "fetch_markets_by_slug"):
            raise ValueError(f"{exchange} does not support fetch_markets_by_slug")

        markets = exch.fetch_markets_by_slug(slug)
        return [serialize_model(m) for m in markets]

    except Exception as e:
        raise translate_error(e, {"exchange": exchange, "slug": slug}) from e


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
        exchange = validate_exchange(exchange)

        # Validate limit and min_liquidity
        if not isinstance(limit, int) or limit <= 0:
            raise ValueError("limit must be a positive integer")
        if not isinstance(min_liquidity, (int, float)) or min_liquidity < 0:
            raise ValueError("min_liquidity must be a non-negative number")

        exch = exchange_manager.get_exchange(exchange)
        market = exch.find_tradeable_market(binary=binary, limit=limit, min_liquidity=min_liquidity)

        if market:
            return serialize_model(market)
        return None

    except Exception as e:
        raise translate_error(e, {"exchange": exchange}) from e


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
        exchange = validate_exchange(exchange)

        # Validate token_symbol if provided
        if token_symbol is not None:
            if not isinstance(token_symbol, str) or not token_symbol.strip():
                raise ValueError("token_symbol must be a non-empty string")
            token_symbol = token_symbol.strip().upper()

        if not isinstance(min_liquidity, (int, float)) or min_liquidity < 0:
            raise ValueError("min_liquidity must be a non-negative number")

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
        raise translate_error(e, {"exchange": exchange, "token_symbol": token_symbol}) from e


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
        identifier = validate_slug(identifier)

        from dr_manhattan.exchanges.polymarket import Polymarket

        return Polymarket.parse_market_identifier(identifier)

    except Exception as e:
        raise translate_error(e, {"identifier": identifier}) from e


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
        slug = validate_slug(slug)

        exch = exchange_manager.get_exchange("polymarket")

        if not hasattr(exch, "get_tag_by_slug"):
            raise ValueError("Only Polymarket supports tags")

        tag = exch.get_tag_by_slug(slug)
        return serialize_model(tag)

    except Exception as e:
        raise translate_error(e, {"slug": slug}) from e


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
        exchange = validate_exchange(exchange)
        market_id = validate_market_id(market_id)

        exch = exchange_manager.get_exchange(exchange)

        if hasattr(exch, "fetch_token_ids"):
            return exch.fetch_token_ids(market_id)
        else:
            # Fallback: get from market metadata
            market = exch.fetch_market(market_id)
            return market.metadata.get("clobTokenIds", [])

    except Exception as e:
        raise translate_error(e, {"exchange": exchange, "market_id": market_id}) from e


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
        exchange = validate_exchange(exchange)
        token_id = validate_token_id(token_id)

        exch = exchange_manager.get_exchange(exchange)
        orderbook = exch.get_orderbook(token_id)
        return serialize_model(orderbook)

    except Exception as e:
        raise translate_error(e, {"exchange": exchange, "token_id": token_id}) from e


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
        exchange = validate_exchange(exchange)
        token_id = validate_token_id(token_id)

        client = exchange_manager.get_client(exchange)
        best_bid, best_ask = client.get_best_bid_ask(token_id)

        return {"best_bid": best_bid, "best_ask": best_ask}

    except Exception as e:
        raise translate_error(e, {"exchange": exchange, "token_id": token_id}) from e
