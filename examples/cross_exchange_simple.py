"""
Cross-exchange market comparison using outcome mapping.

Usage:
    uv run python examples/cross_exchange_simple.py
"""

from dotenv import load_dotenv

from dr_manhattan import (
    OPINION,
    POLYMARKET,
    CrossExchangeManager,
    ExchangeOutcomeRef,
    OutcomeMapping,
)

load_dotenv()

# Outcome mapping: slug -> outcome_key -> {exchange_id: ExchangeOutcomeRef}
MAPPING: OutcomeMapping = {
    "fed-jan-2026": {
        "no-change": {
            POLYMARKET: ExchangeOutcomeRef(POLYMARKET, "fed-decision-in-january", "Yes"),
            OPINION: ExchangeOutcomeRef(OPINION, "61", "450-475"),
        },
        "cut-25bps": {
            POLYMARKET: ExchangeOutcomeRef(POLYMARKET, "fed-decision-in-january", "Yes"),
            OPINION: ExchangeOutcomeRef(OPINION, "61", "425-450"),
        },
    },
}


def main():
    print("Cross-Exchange Market Comparison")
    print("=" * 60)

    manager = CrossExchangeManager(MAPPING)

    for slug in manager.slugs:
        fetched = manager.fetch(slug)

        print(f"\nSlug: {slug}")
        print("-" * 40)

        # Show raw markets
        for exchange_id in fetched.exchanges:
            markets = fetched.get(exchange_id)
            print(f"\n[{exchange_id.upper()}] {len(markets)} market(s)")
            for m in markets:
                q = m.question[:50] + "..." if len(m.question) > 50 else m.question
                print(f"  {q}")
                print(f"    Prices: {m.prices}")

        # Show matched outcomes
        matched = fetched.get_matched_outcomes()
        if matched:
            print(f"\nMatched Outcomes ({len(matched)}):")
            print("-" * 40)
            for m in matched:
                print(f"\n  {m.outcome_key}:")
                for ex_id, tp in m.prices.items():
                    print(f"    {ex_id}: {tp.price:.4f} ({tp.outcome})")
                print(f"    Spread: {m.spread:.4f}")


if __name__ == "__main__":
    main()
