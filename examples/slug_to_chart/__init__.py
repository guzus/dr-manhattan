"""
Polymarket Slug to Chart

Generates Bloomberg-style price charts from Polymarket event data.

Usage:
    uv run python -m examples.slug_to_chart <slug> [options]

Example:
    uv run python -m examples.slug_to_chart fed-decision-in-january --top 4
"""

from .chart import generate_chart
from .fetcher import fetch_event_price_history
from .labels import extract_short_label

__all__ = ["fetch_event_price_history", "generate_chart", "extract_short_label"]
