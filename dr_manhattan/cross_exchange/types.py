"""Types for cross-exchange operations."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from ..models.market import ExchangeOutcomeRef, Market, ReadableMarketId

# slug -> outcome_key -> {exchange_id: ExchangeOutcomeRef}
OutcomeMapping = Dict[str, Dict[str, Dict[str, ExchangeOutcomeRef]]]


def _market_matches(market: Market, ref: ExchangeOutcomeRef) -> bool:
    """Check if a market matches the reference (last element is match_id or market.id)."""
    ref_id = ref.market_id[-1]
    market_id = market.metadata.get("match_id", market.id)
    return str(market_id).lower() == ref_id.lower()


def _get_fetch_slug(market_id: ReadableMarketId) -> str:
    """Extract the fetch slug from a market ID (first element)."""
    return market_id[0]


def _extract_fetch_slugs(mapping: OutcomeMapping, slug: str) -> Dict[str, Set[str]]:
    """Extract unique fetch slugs per exchange from outcome mapping."""
    result: Dict[str, Set[str]] = {}
    if slug not in mapping:
        return result

    for exchange_refs in mapping[slug].values():
        for exchange_id, ref in exchange_refs.items():
            if exchange_id not in result:
                result[exchange_id] = set()
            result[exchange_id].add(_get_fetch_slug(ref.market_id))

    return result


@dataclass
class TokenPrice:
    """Price info for a single token/outcome on an exchange."""

    ref: ExchangeOutcomeRef
    price: float
    token_id: Optional[str] = None

    @property
    def exchange_id(self) -> str:
        return self.ref.exchange_id

    @property
    def market_id(self) -> str:
        return self.ref.market_id

    @property
    def outcome(self) -> str:
        return self.ref.outcome


@dataclass
class MatchedOutcome:
    """An outcome matched across exchanges with prices."""

    outcome_key: str
    prices: Dict[str, TokenPrice]  # exchange_id -> TokenPrice

    @property
    def spread(self) -> float:
        """Price spread across exchanges."""
        values = [p.price for p in self.prices.values() if p.price > 0]
        if len(values) < 2:
            return 0.0
        return max(values) - min(values)

    @property
    def exchanges(self) -> List[str]:
        return list(self.prices.keys())


@dataclass
class FetchedMarkets:
    """Markets fetched for comparison."""

    slug: str
    markets: Dict[str, List[Market]]  # exchange_id -> markets
    outcome_mapping: Dict[str, Dict[str, ExchangeOutcomeRef]] = field(default_factory=dict)

    @property
    def exchanges(self) -> List[str]:
        return list(self.markets.keys())

    def get(self, exchange_id: str) -> List[Market]:
        return self.markets.get(exchange_id, [])

    def get_matched_outcomes(self) -> List[MatchedOutcome]:
        """Get outcomes matched across exchanges."""
        if not self.outcome_mapping:
            return []

        result = []
        for outcome_key, exchange_refs in self.outcome_mapping.items():
            prices: Dict[str, TokenPrice] = {}

            for exchange_id, ref in exchange_refs.items():
                markets = self.get(exchange_id)
                for market in markets:
                    if _market_matches(market, ref) and ref.outcome in market.prices:
                        token_id = market.metadata.get("tokens", {}).get(ref.outcome)
                        prices[exchange_id] = TokenPrice(
                            ref=ref,
                            price=market.prices[ref.outcome],
                            token_id=token_id,
                        )
                        break

            if len(prices) >= 2:
                result.append(MatchedOutcome(outcome_key=outcome_key, prices=prices))

        return result
