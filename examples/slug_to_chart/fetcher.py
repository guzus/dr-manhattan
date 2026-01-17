"""Data fetching utilities for Polymarket price history."""

from typing import Literal

import pandas as pd

import dr_manhattan

INTERVAL_TYPE = Literal["1m", "1h", "6h", "1d", "1w", "max"]


def fetch_event_price_history(
    slug: str,
    interval: INTERVAL_TYPE = "max",
    fidelity: int = 300,
    top_n: int | None = None,
    min_price: float = 0.001,
) -> tuple[str, dict[str, pd.DataFrame]]:
    """
    Fetch price history for all markets in an event.

    Args:
        slug: Event slug or URL
        interval: Price history interval (1m, 1h, 6h, 1d, 1w, max)
        fidelity: Number of data points
        top_n: Only include top N outcomes by current price
        min_price: Minimum price threshold (0-1) to include outcome (default: 0.1%)

    Returns:
        Tuple of (event_title, dict mapping labels to price DataFrames)
    """
    exchange = dr_manhattan.Polymarket()

    markets = exchange.fetch_markets_by_slug(slug)
    if not markets:
        raise ValueError(f"No markets found for slug: {slug}")

    event_title = markets[0].metadata.get("event_title", slug)

    # Collect outcomes with prices for sorting
    outcomes_with_prices: list[tuple[str, float, object, int]] = []

    for market in markets:
        # Fetch token IDs if not present
        if not market.metadata.get("clobTokenIds"):
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
            df = exchange.fetch_price_history(
                market,
                outcome=outcome_idx,
                interval=interval,
                fidelity=fidelity,
                as_dataframe=True,
            )
            if df is not None and not df.empty:
                final_label = label
                if final_label in price_data:
                    final_label = f"{label} ({market.outcomes[outcome_idx]})"
                price_data[final_label] = df
        except Exception as e:
            print(f"Warning: Could not fetch history for {label}: {e}")

    return event_title, price_data
