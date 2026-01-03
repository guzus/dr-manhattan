"""
Cross-exchange market comparison using outcome mapping.

Usage:
    uv run python examples/cross_exchange_simple.py
"""

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from dr_manhattan import (
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
    "fed-jan-2026": {
        "no-change": {
            POLYMARKET: ExchangeOutcomeRef(
                POLYMARKET, ["fed-decision-in-january", "No change"], "Yes"
            ),
            OPINION: ExchangeOutcomeRef(OPINION, ["61"], "No change"),
        },
        "cut-25bps": {
            POLYMARKET: ExchangeOutcomeRef(
                POLYMARKET, ["fed-decision-in-january", "25 bps decrease"], "Yes"
            ),
            OPINION: ExchangeOutcomeRef(OPINION, ["61"], "25 bps decrease"),
        },
        "cut-50bps": {
            POLYMARKET: ExchangeOutcomeRef(
                POLYMARKET, ["fed-decision-in-january", "50+ bps decrease"], "Yes"
            ),
            OPINION: ExchangeOutcomeRef(OPINION, ["61"], "50+ bps decrease"),
        },
        "increase": {
            POLYMARKET: ExchangeOutcomeRef(
                POLYMARKET, ["fed-decision-in-january", "25+ bps increase"], "Yes"
            ),
            OPINION: ExchangeOutcomeRef(OPINION, ["61"], "Increase"),
        },
    },
}


def main():
    console.print("[bold]Cross-Exchange Market Comparison[/bold]\n")

    manager = CrossExchangeManager(MAPPING)

    for slug in manager.slugs:
        fetched = manager.fetch(slug)

        # Build matched outcomes table
        matched = fetched.get_matched_outcomes()
        if matched:
            table = Table(title=f"[bold]{slug}[/bold]", show_header=True)
            table.add_column("Outcome", style="cyan")
            table.add_column("Polymarket", justify="right")
            table.add_column("Opinion", justify="right")
            table.add_column("Spread", justify="right")

            for m in matched:
                poly_price = m.prices.get(POLYMARKET)
                opinion_price = m.prices.get(OPINION)

                poly_str = f"{poly_price.price * 100:.2f}%" if poly_price else "-"
                opinion_str = f"{opinion_price.price * 100:.2f}%" if opinion_price else "-"

                spread = m.spread * 100
                if spread > 1:
                    spread_str = f"[red]{spread:.2f}%[/red]"
                elif spread > 0.5:
                    spread_str = f"[yellow]{spread:.2f}%[/yellow]"
                else:
                    spread_str = f"[green]{spread:.2f}%[/green]"

                table.add_row(m.outcome_key, poly_str, opinion_str, spread_str)

            console.print(table)


if __name__ == "__main__":
    main()
