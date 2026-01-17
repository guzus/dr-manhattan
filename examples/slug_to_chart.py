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
    Generate a Bloomberg-style price chart.

    Args:
        title: Chart title
        price_data: Dict mapping outcome names to price DataFrames
        output_path: Path to save the chart image
        subtitle: Optional subtitle for the chart
    """
    plt.rcParams["font.family"] = ["Arial", "Helvetica", "DejaVu Sans", "sans-serif"]

    fig = plt.figure(figsize=(10, 8), facecolor="white")

    # Create axes with specific position [left, bottom, width, height]
    ax = fig.add_axes([0.08, 0.12, 0.82, 0.58])
    ax.set_facecolor("white")

    labels_list = []
    colors_list = []

    for i, (label, df) in enumerate(price_data.items()):
        color = DEFAULT_COLORS[i % len(DEFAULT_COLORS)]
        prices_pct = df["price"] * 100

        ax.plot(
            df["timestamp"],
            prices_pct,
            color=color,
            linewidth=2.5,
            solid_capstyle="round",
        )

        # Extract short label from question
        short_label = label
        if "?" in label:
            q = label.replace("?", "")
            # Common patterns to extract key info
            # "Will X nominate Y as..." -> "Y"
            # "Fed decreases/increases by X bps..." -> "Decrease X bps" / "Increase X bps"
            # "Will X win..." -> "X"
            if "decreases" in q.lower() or "decrease" in q.lower():
                if "50+" in q:
                    short_label = "Decrease 50+ bps"
                elif "25 bps" in q:
                    short_label = "Decrease 25 bps"
                elif "bps" in q.lower():
                    short_label = "Decrease"
            elif "increases" in q.lower() or "increase" in q.lower():
                if "25+" in q:
                    short_label = "Increase 25+ bps"
                elif "bps" in q.lower():
                    short_label = "Increase"
            elif "nominate" in q.lower():
                # Extract name after "nominate"
                parts = q.split("nominate")[-1].split()
                names = [
                    p
                    for p in parts
                    if p and p[0].isupper() and p.lower() not in ["as", "the", "next", "for"]
                ]
                if names:
                    short_label = " ".join(names[:2])
            elif "win" in q.lower() or "elected" in q.lower():
                # Extract name before "win/elected"
                parts = q.split()
                names = [
                    p
                    for p in parts
                    if p and p[0].isupper() and p.lower() not in ["will", "the", "be"]
                ]
                if names:
                    short_label = " ".join(names[:2])
            else:
                # Fallback: take first few capitalized words
                parts = q.split()
                names = [
                    p
                    for p in parts
                    if p
                    and len(p) > 1
                    and p[0].isupper()
                    and p.lower() not in ["will", "the", "be", "in", "on", "by"]
                ]
                if names:
                    short_label = " ".join(names[:3])

        labels_list.append(short_label)
        colors_list.append(color)

    # Y-axis formatting
    ax.set_ylim(-2, 102)
    ax.set_yticks([0, 20, 40, 60, 80, 100])
    ax.yaxis.tick_right()
    ax.yaxis.set_label_position("right")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{int(x)}%"))

    # X-axis formatting
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
    ax.xaxis.set_major_locator(mdates.MonthLocator())

    # Grid - horizontal only, light gray
    ax.grid(True, axis="y", linestyle="-", linewidth=0.8, color="#e0e0e0", zorder=0)
    ax.grid(False, axis="x")

    # Remove all spines
    for spine in ax.spines.values():
        spine.set_visible(False)

    # Tick styling
    ax.tick_params(axis="both", which="both", length=0)
    ax.tick_params(axis="x", colors="#333333", labelsize=12)
    ax.tick_params(axis="y", colors="#333333", labelsize=12)

    # Title - bold, top left
    fig.text(
        0.08, 0.92, title, fontsize=22, fontweight="bold", color="#000000", va="top", ha="left"
    )

    # Subtitle
    if subtitle:
        fig.text(0.08, 0.86, subtitle, fontsize=14, color="#666666", va="top", ha="left")
        legend_y = 0.79
    else:
        legend_y = 0.84

    # Custom legend with diagonal line markers (Bloomberg style)
    legend_x = 0.08
    for i, (label, color) in enumerate(zip(labels_list, colors_list)):
        # Draw diagonal line marker
        line_ax = fig.add_axes([legend_x, legend_y - 0.01, 0.02, 0.025])
        line_ax.plot([0, 1], [0, 1], color=color, linewidth=3, solid_capstyle="round")
        line_ax.set_xlim(0, 1)
        line_ax.set_ylim(0, 1)
        line_ax.axis("off")

        # Label text
        fig.text(
            legend_x + 0.025, legend_y, label, fontsize=12, color="#333333", va="center", ha="left"
        )

        legend_x += 0.025 + len(label) * 0.008 + 0.03

    # Source attribution
    fig.text(0.08, 0.03, "Source: Polymarket", fontsize=11, color="#666666", va="bottom", ha="left")

    # Made with dr-manhattan watermark
    fig.text(
        0.92,
        0.03,
        "dr-manhattan",
        fontsize=11,
        fontweight="bold",
        color="#333333",
        va="bottom",
        ha="right",
    )

    plt.savefig(output_path, dpi=150, bbox_inches="tight", facecolor="white", pad_inches=0.3)
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
