"""
Cross-exchange market comparison using outcome mapping.

Usage:
    uv run python examples/cross_exchange_simple.py
"""

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from dr_manhattan import (
    KALSHI,
    LIMITLESS,
    OPINION,
    POLYMARKET,
    CrossExchangeManager,
    ExchangeOutcomeRef,
    OutcomeMapping,
)

console = Console()

load_dotenv()

# Outcome mapping: slug -> outcome_key -> exchange_id -> ExchangeOutcomeRef
# market_path: ["fetch_slug"] or ["fetch_slug", "match_id"]
MAPPING: OutcomeMapping = {
    "Fed decision in January?": {
        "no-change": {
            POLYMARKET: ExchangeOutcomeRef(
                POLYMARKET, ["fed-decision-in-january", "No change"], "Yes"
            ),
            OPINION: ExchangeOutcomeRef(OPINION, ["61"], "No change"),
            LIMITLESS: ExchangeOutcomeRef(
                LIMITLESS, ["fed-decision-in-january-1764672402681", "No change"], "Yes"
            ),
            KALSHI: ExchangeOutcomeRef(KALSHI, ["KXFEDDECISION-26JAN-H0"], "Yes"),
        },
        "cut-25": {
            POLYMARKET: ExchangeOutcomeRef(
                POLYMARKET, ["fed-decision-in-january", "25 bps decrease"], "Yes"
            ),
            OPINION: ExchangeOutcomeRef(OPINION, ["61"], "25 bps decrease"),
            LIMITLESS: ExchangeOutcomeRef(
                LIMITLESS, ["fed-decision-in-january-1764672402681", "25 bps decrease"], "Yes"
            ),
            KALSHI: ExchangeOutcomeRef(KALSHI, ["KXFEDDECISION-26JAN-C25"], "Yes"),
        },
        "cut-50+": {
            POLYMARKET: ExchangeOutcomeRef(
                POLYMARKET, ["fed-decision-in-january", "50+ bps decrease"], "Yes"
            ),
            OPINION: ExchangeOutcomeRef(OPINION, ["61"], "50+ bps decrease"),
            LIMITLESS: ExchangeOutcomeRef(
                LIMITLESS, ["fed-decision-in-january-1764672402681", "50+ bps decrease"], "Yes"
            ),
            KALSHI: ExchangeOutcomeRef(KALSHI, ["KXFEDDECISION-26JAN-C26"], "Yes"),
        },
        "hike": {
            # Polymarket and Opinion only - generic hike
            POLYMARKET: ExchangeOutcomeRef(
                POLYMARKET, ["fed-decision-in-january", "25+ bps increase"], "Yes"
            ),
            OPINION: ExchangeOutcomeRef(OPINION, ["61"], "Increase"),
        },
        "hike-25": {
            # Kalshi only
            KALSHI: ExchangeOutcomeRef(KALSHI, ["KXFEDDECISION-26JAN-H25"], "Yes"),
        },
        "hike-50+": {
            # Kalshi and Limitless
            LIMITLESS: ExchangeOutcomeRef(
                LIMITLESS, ["fed-decision-in-january-1764672402681", "25+ bps increase"], "Yes"
            ),
            KALSHI: ExchangeOutcomeRef(KALSHI, ["KXFEDDECISION-26JAN-H26"], "Yes"),
        },
    },
}


def main():
    console.print("[bold]Cross-Exchange Market Comparison[/bold]\n")

    manager = CrossExchangeManager(MAPPING)

    for slug in manager.slugs:
        fetched = manager.fetch(slug)

        # Build matched outcomes table (min_exchanges=1 to show single-exchange outcomes)
        matched = fetched.get_matched_outcomes(min_exchanges=1)
        if matched:
            table = Table(title=f"[bold]{slug}[/bold]", show_header=True)
            table.add_column("Outcome", style="cyan")
            table.add_column("Polymarket", justify="right")
            table.add_column("Opinion", justify="right")
            table.add_column("Limitless", justify="right")
            table.add_column("Kalshi", justify="right")
            table.add_column("Spread", justify="right")

            for m in matched:
                poly_price = m.prices.get(POLYMARKET)
                opinion_price = m.prices.get(OPINION)
                limitless_price = m.prices.get(LIMITLESS)
                kalshi_price = m.prices.get(KALSHI)

                poly_str = f"{poly_price.price * 100:.1f}%" if poly_price else "-"
                opinion_str = f"{opinion_price.price * 100:.1f}%" if opinion_price else "-"
                limitless_str = f"{limitless_price.price * 100:.1f}%" if limitless_price else "-"
                kalshi_str = f"{kalshi_price.price * 100:.1f}%" if kalshi_price else "-"

                spread = m.spread * 100
                if spread > 1:
                    spread_str = f"[red]{spread:.1f}%[/red]"
                elif spread > 0.5:
                    spread_str = f"[yellow]{spread:.1f}%[/yellow]"
                else:
                    spread_str = f"[green]{spread:.1f}%[/green]"

                table.add_row(
                    m.outcome_key, poly_str, opinion_str, limitless_str, kalshi_str, spread_str
                )

            console.print(table)


if __name__ == "__main__":
    main()
