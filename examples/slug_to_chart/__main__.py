#!/usr/bin/env python3
"""
Polymarket Slug to Chart - CLI Entry Point

Usage:
    uv run python -m examples.slug_to_chart <slug> [options]

Examples:
    uv run python -m examples.slug_to_chart fed-decision-in-january --top 4
    uv run python -m examples.slug_to_chart democratic-presidential-nominee-2028 -o chart.png
"""

import argparse
import sys
from pathlib import Path

from .chart import generate_chart
from .fetcher import fetch_event_price_history


def main():
    parser = argparse.ArgumentParser(
        description="Generate Bloomberg-style price chart from Polymarket event",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("slug", help="Polymarket event slug or full URL")
    parser.add_argument("--output", "-o", type=Path, default=None, help="Output image path")
    parser.add_argument(
        "--interval",
        "-i",
        type=str,
        default="1d",
        choices=["1m", "1h", "6h", "1d", "1w", "max"],
        help="Price history interval (default: 1d)",
    )
    parser.add_argument("--fidelity", "-f", type=int, default=90, help="Data points (default: 90)")
    parser.add_argument("--subtitle", "-s", type=str, default=None, help="Chart subtitle")
    parser.add_argument("--top", "-t", type=int, default=None, help="Top N outcomes by price")

    args = parser.parse_args()

    # Parse slug from URL if needed
    slug = args.slug
    if "polymarket.com" in slug:
        slug = slug.split("/")[-1].split("?")[0]

    output_path = args.output or Path(f"{slug.replace('/', '_')}.png")

    print(f"Fetching price history for: {slug}")
    print(f"Interval: {args.interval}, Fidelity: {args.fidelity}")
    if args.top:
        print(f"Showing top {args.top} outcomes")

    try:
        title, price_data = fetch_event_price_history(
            slug, interval=args.interval, fidelity=args.fidelity, top_n=args.top
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
