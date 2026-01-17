"""Data fetching utilities for price history from multiple exchanges."""

from typing import Literal

import pandas as pd

import dr_manhattan

EXCHANGE_TYPE = Literal["polymarket", "limitless", "opinion"]
INTERVAL_TYPE = Literal["1m", "1h", "6h", "1d", "1w", "max"]

# Supported intervals per exchange
EXCHANGE_INTERVALS = {
    "polymarket": ["1m", "1h", "6h", "1d", "1w", "max"],
    "limitless": ["1m", "1h", "1d", "1w"],
    "opinion": ["1m", "1h", "1d", "1w", "max"],
}


def _get_exchange(exchange_name: EXCHANGE_TYPE):
    """Get exchange instance by name."""
    exchanges = {
        "polymarket": dr_manhattan.Polymarket,
        "limitless": dr_manhattan.Limitless,
        "opinion": dr_manhattan.Opinion,
    }
    return exchanges[exchange_name]()


def _normalize_interval(interval: INTERVAL_TYPE, exchange_name: EXCHANGE_TYPE) -> str:
    """Normalize interval for exchange compatibility."""
    supported = EXCHANGE_INTERVALS[exchange_name]
    if interval in supported:
        return interval
    # Fallback mappings
    if interval == "6h" and "1d" in supported:
        return "1d"
    if interval == "max" and "1w" in supported:
        return "1w"
    return supported[-1]  # Use longest available


def _fetch_markets(exchange, exchange_name: EXCHANGE_TYPE, slug: str):
    """Fetch markets using exchange-specific method."""
    if exchange_name == "opinion":
        # Opinion uses search_markets instead of fetch_markets_by_slug
        markets = exchange.search_markets(query=slug, limit=50)
        if not markets:
            # Try fetching as market ID
            try:
                market = exchange.fetch_market(slug)
                markets = [market]
            except Exception:
                pass
        return markets
    return exchange.fetch_markets_by_slug(slug)


def _fetch_price_history(
    exchange, exchange_name: EXCHANGE_TYPE, market, outcome_idx, interval, fidelity
):
    """Fetch price history using exchange-specific parameters."""
    if exchange_name == "polymarket":
        return exchange.fetch_price_history(
            market,
            outcome=outcome_idx,
            interval=interval,
            fidelity=fidelity,
            as_dataframe=True,
        )
    # Limitless and Opinion don't support fidelity parameter
    return exchange.fetch_price_history(
        market,
        outcome=outcome_idx,
        interval=interval,
        as_dataframe=True,
    )


def fetch_event_price_history(
    slug: str,
    exchange_name: EXCHANGE_TYPE = "polymarket",
    interval: INTERVAL_TYPE = "max",
    fidelity: int = 300,
    top_n: int | None = None,
    min_price: float = 0.001,
) -> tuple[str, dict[str, pd.DataFrame]]:
    """
    Fetch price history for all markets in an event.

    Args:
        slug: Event slug, URL, or market ID
        exchange_name: Exchange to use (polymarket, limitless, opinion)
        interval: Price history interval (1m, 1h, 6h, 1d, 1w, max)
        fidelity: Number of data points (Polymarket only)
        top_n: Only include top N outcomes by current price
        min_price: Minimum price threshold (0-1) to include outcome

    Returns:
        Tuple of (event_title, dict mapping labels to price DataFrames)
    """
    exchange = _get_exchange(exchange_name)
    interval = _normalize_interval(interval, exchange_name)

    markets = _fetch_markets(exchange, exchange_name, slug)
    if not markets:
        raise ValueError(f"No markets found for: {slug}")

    event_title = markets[0].metadata.get("event_title") or markets[0].question or slug

    # Collect outcomes with prices for sorting
    outcomes_with_prices: list[tuple[str, float, object, int]] = []

    for market in markets:
        # Fetch token IDs if not present (Polymarket specific)
        if exchange_name == "polymarket" and not market.metadata.get("clobTokenIds"):
            try:
                token_ids = exchange.fetch_token_ids(market.id)
                if token_ids:
                    market.metadata["clobTokenIds"] = token_ids
            except Exception:
                pass

        outcomes = market.outcomes
        prices = market.prices

        # For binary Yes/No markets, only show "Yes" outcome
        is_binary = len(outcomes) == 2 and outcomes[0] == "Yes" and outcomes[1] == "No"

        if is_binary:
            label = market.question
            current_price = prices.get("Yes", 0.0)
            outcomes_with_prices.append((label, current_price, market, 0))
        else:
            for i, outcome in enumerate(outcomes):
                label = outcome if len(markets) == 1 else f"{market.question} - {outcome}"
                current_price = prices.get(outcome, 0.0)
                outcomes_with_prices.append((label, current_price, market, i))

    # Sort by price descending, filter by min_price, and take top N
    outcomes_with_prices.sort(key=lambda x: x[1], reverse=True)
    outcomes_with_prices = [o for o in outcomes_with_prices if o[1] >= min_price]
    if top_n is not None:
        outcomes_with_prices = outcomes_with_prices[:top_n]

    # Fetch price history for each outcome
    price_data: dict[str, pd.DataFrame] = {}

    for label, _, market, outcome_idx in outcomes_with_prices:
        try:
            df = _fetch_price_history(
                exchange, exchange_name, market, outcome_idx, interval, fidelity
            )
            if df is not None and not df.empty:
                final_label = label
                if final_label in price_data:
                    final_label = f"{label} ({market.outcomes[outcome_idx]})"
                price_data[final_label] = df
        except Exception as e:
            print(f"Warning: Could not fetch history for {label}: {e}")

    return event_title, price_data
