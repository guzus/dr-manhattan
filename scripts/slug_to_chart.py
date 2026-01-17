#!/usr/bin/env python3
"""
Polymarket Slug to Chart

Fetches historical prices from Polymarket API for a given event slug
and generates a chart as an image file.

Usage:
    uv run python scripts/slug_to_chart.py <slug_or_url> [--output chart.png] [--interval 1h]

Examples:
    uv run python scripts/slug_to_chart.py will-donald-trumps-fed-chair-nominee-be
    uv run python scripts/slug_to_chart.py https://polymarket.com/event/fed-chair --output fed_chair.png
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Literal

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

import dr_manhattan

INTERVAL_TYPE = Literal["1m", "1h", "6h", "1d", "1w", "max"]
DEFAULT_COLORS = [
    "#FF8C00",  # Dark orange
    "#000000",  # Black
    "#1E90FF",  # Dodger blue
    "#32CD32",  # Lime green
    "#DC143C",  # Crimson
    "#9370DB",  # Medium purple
    "#20B2AA",  # Light sea green
    "#FF69B4",  # Hot pink
]


def fetch_event_price_history(
    slug: str,
    interval: INTERVAL_TYPE = "1h",
    fidelity: int = 60,
    top_n: int | None = None,
) -> tuple[str, dict[str, pd.DataFrame]]:
    """
    Fetch price history for all markets in an event.

    Args:
        slug: Event slug or URL
        interval: Price history interval (1m, 1h, 6h, 1d, 1w, max)
        fidelity: Number of data points
        top_n: Only include top N outcomes by current price

    Returns:
        Tuple of (event_title, dict mapping outcome names to price DataFrames)
    """
    exchange = dr_manhattan.Polymarket()

    markets = exchange.fetch_markets_by_slug(slug)
    if not markets:
        raise ValueError(f"No markets found for slug: {slug}")

    event_title = markets[0].metadata.get("event_title", slug)

    # Collect all outcomes with their current prices for sorting
    outcomes_with_prices: list[tuple[str, float, object, int]] = []

    for market in markets:
        outcomes = market.outcomes
        prices = market.prices

        for i, outcome in enumerate(outcomes):
            label = market.question if len(outcomes) <= 2 else outcome
            if len(markets) > 1:
                label = f"{market.question}"

            current_price = prices.get(outcome, 0.0)
            outcomes_with_prices.append((label, current_price, market, i))

    # Sort by current price descending and take top N
    outcomes_with_prices.sort(key=lambda x: x[1], reverse=True)

    if top_n is not None:
        outcomes_with_prices = outcomes_with_prices[:top_n]

    price_data: dict[str, pd.DataFrame] = {}

    for label, current_price, market, outcome_idx in outcomes_with_prices:
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


def generate_chart(
    title: str,
    price_data: dict[str, pd.DataFrame],
    output_path: Path,
    subtitle: str | None = None,
) -> None:
    """
    Generate a professional-looking price chart.

    Args:
        title: Chart title
        price_data: Dict mapping outcome names to price DataFrames
        output_path: Path to save the chart image
        subtitle: Optional subtitle for the chart
    """
    fig, ax = plt.subplots(figsize=(12, 7), facecolor="white")
    ax.set_facecolor("white")

    for i, (label, df) in enumerate(price_data.items()):
        color = DEFAULT_COLORS[i % len(DEFAULT_COLORS)]

        prices_pct = df["price"] * 100

        ax.plot(
            df["timestamp"],
            prices_pct,
            label=label,
            color=color,
            linewidth=2.0,
        )

    ax.set_ylabel("")
    ax.set_xlabel("")

    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{int(x)}%"))
    ax.set_ylim(0, 105)

    ax.yaxis.tick_right()
    ax.yaxis.set_label_position("right")

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
    ax.xaxis.set_major_locator(mdates.MonthLocator())

    ax.grid(True, axis="y", linestyle="-", alpha=0.3, color="#cccccc")
    ax.grid(False, axis="x")

    ax.spines["top"].set_visible(False)
    ax.spines["left"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["bottom"].set_color("#cccccc")

    ax.tick_params(axis="both", which="both", length=0)
    ax.tick_params(axis="x", colors="#666666")
    ax.tick_params(axis="y", colors="#666666")

    fig.text(0.02, 0.95, title, fontsize=16, fontweight="bold", va="top", ha="left")

    if subtitle:
        fig.text(0.02, 0.90, subtitle, fontsize=11, color="#666666", va="top", ha="left")

    if len(price_data) > 1:
        ax.legend(
            loc="upper left",
            frameon=False,
            fontsize=10,
            ncol=min(3, len(price_data)),
        )

    fig.text(0.02, 0.02, "Source: Polymarket", fontsize=9, color="#666666")

    current_time = datetime.now().strftime("%Y-%m-%d %H:%M")
    fig.text(0.98, 0.02, f"Generated: {current_time}", fontsize=9, color="#666666", ha="right")

    plt.tight_layout()
    plt.subplots_adjust(top=0.85, bottom=0.1, left=0.05, right=0.92)

    plt.savefig(output_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close()

    print(f"Chart saved to: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Generate price chart from Polymarket event slug",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    uv run python scripts/slug_to_chart.py will-donald-trumps-fed-chair-nominee-be
    uv run python scripts/slug_to_chart.py fed-chair-nominee --output fed_chair.png --interval 1d
        """,
    )
    parser.add_argument(
        "slug",
        help="Polymarket event slug or full URL",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Output image path (default: <slug>.png)",
    )
    parser.add_argument(
        "--interval",
        "-i",
        type=str,
        default="1h",
        choices=["1m", "1h", "6h", "1d", "1w", "max"],
        help="Price history interval (default: 1h)",
    )
    parser.add_argument(
        "--fidelity",
        "-f",
        type=int,
        default=60,
        help="Number of data points (default: 60)",
    )
    parser.add_argument(
        "--subtitle",
        "-s",
        type=str,
        default=None,
        help="Optional subtitle for the chart",
    )
    parser.add_argument(
        "--top",
        "-t",
        type=int,
        default=None,
        help="Only show top N outcomes by current price",
    )

    args = parser.parse_args()

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
            slug,
            interval=args.interval,
            fidelity=args.fidelity,
            top_n=args.top,
        )

        if not price_data:
            print("Error: No price data available for this event")
            sys.exit(1)

        print(f"Found {len(price_data)} outcome(s)")

        generate_chart(
            title=title,
            price_data=price_data,
            output_path=output_path,
            subtitle=args.subtitle,
        )

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
