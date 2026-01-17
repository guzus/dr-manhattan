"""
Slug to Chart

Generates Bloomberg-style price charts from prediction market data.
Supports Polymarket, Limitless, and Opinion exchanges.

Usage:
    uv run python -m examples.slug_to_chart <slug> [options]

Example:
    uv run python -m examples.slug_to_chart fed-decision-in-january --top 4
    uv run python -m examples.slug_to_chart --exchange limitless will-trump-fire-jerome-powell
"""

from .chart import generate_chart
from .fetcher import EXCHANGE_INTERVALS, EXCHANGE_TYPE, fetch_event_price_history
from .labels import extract_short_label

__all__ = [
    "fetch_event_price_history",
    "generate_chart",
    "extract_short_label",
    "EXCHANGE_TYPE",
    "EXCHANGE_INTERVALS",
]
