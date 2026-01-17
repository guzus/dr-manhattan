#!/usr/bin/env python3
"""
Slug to Chart - CLI Entry Point

Usage:
    uv run python -m examples.slug_to_chart <slug> [options]

Examples:
    uv run python -m examples.slug_to_chart fed-decision-in-january --top 4
    uv run python -m examples.slug_to_chart --exchange limitless will-trump-fire-jerome-powell
    uv run python -m examples.slug_to_chart --exchange opinion "fed rate"
"""

import argparse
import sys
from pathlib import Path

from .chart import generate_chart
from .fetcher import EXCHANGE_INTERVALS, fetch_event_price_history


def parse_slug(slug: str, exchange: str) -> str:
    """Parse slug from URL based on exchange."""
    url_patterns = {
        "polymarket": "polymarket.com",
        "limitless": "limitless.exchange",
        "opinion": "opinion.xyz",
    }
    pattern = url_patterns.get(exchange, "")
    if pattern and pattern in slug:
        slug = slug.split("/")[-1].split("?")[0]
    return slug


def main():
    parser = argparse.ArgumentParser(
        description="Generate Bloomberg-style price chart from prediction market data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("slug", help="Event slug, URL, or search query")
    parser.add_argument("--output", "-o", type=Path, default=None, help="Output image path")
    parser.add_argument(
        "--exchange",
        "-e",
        type=str,
        default="polymarket",
        choices=["polymarket", "limitless", "opinion"],
        help="Exchange to use (default: polymarket)",
    )
    parser.add_argument(
        "--interval",
        "-i",
        type=str,
        default="max",
        choices=["1m", "1h", "6h", "1d", "1w", "max"],
        help="Price history interval (default: max)",
    )
    parser.add_argument(
        "--fidelity",
        "-f",
        type=int,
        default=300,
        help="Data points (default: 300, Polymarket only)",
    )
    parser.add_argument("--subtitle", "-s", type=str, default=None, help="Chart subtitle")
    parser.add_argument("--top", "-t", type=int, default=None, help="Top N outcomes by price")
    parser.add_argument(
        "--min-price",
        "-m",
        type=float,
        default=0.001,
        help="Min price threshold 0-1 (default: 0.001 = 0.1%%)",
    )

    args = parser.parse_args()

    slug = parse_slug(args.slug, args.exchange)
    output_path = args.output or Path(f"{slug.replace('/', '_').replace(' ', '_')}.png")

    # Validate interval for exchange
    supported = EXCHANGE_INTERVALS[args.exchange]
    interval = args.interval if args.interval in supported else supported[-1]
    if interval != args.interval:
        print(f"Note: {args.exchange} doesn't support '{args.interval}', using '{interval}'")

    print(f"Exchange: {args.exchange}")
    print(f"Fetching price history for: {slug}")
    print(f"Interval: {interval}")
    if args.top:
        print(f"Showing top {args.top} outcomes")

    try:
        title, price_data = fetch_event_price_history(
            slug,
            exchange_name=args.exchange,
            interval=interval,
            fidelity=args.fidelity,
            top_n=args.top,
            min_price=args.min_price,
        )

        if not price_data:
            print("Error: No price data available for this event")
            sys.exit(1)

        print(f"Found {len(price_data)} outcome(s)")
        generate_chart(title, price_data, output_path, subtitle=args.subtitle)

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
