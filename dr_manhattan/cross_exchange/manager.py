"""Simple cross-exchange manager."""

from typing import Dict, List, Optional

from ..base.exchange import Exchange as BaseExchange
from ..base.exchange_factory import create_exchange
from ..models.market import Market
from .types import FetchedMarkets, OutcomeMapping, _extract_fetch_slugs


class CrossExchangeManager:
    """Manages market comparisons across exchanges using outcome mapping."""

    def __init__(
        self,
        mapping: OutcomeMapping,
        exchanges: Optional[Dict[str, BaseExchange]] = None,
    ):
        """
        Initialize manager with outcome mapping.

        Args:
            mapping: slug -> {exchange_id: OutcomeRef(market_id, outcome)}
            exchanges: Pre-initialized exchanges (created automatically if None)
        """
        self.mapping = mapping
        self._exchanges = exchanges or {}

    def _get_exchange(self, exchange_id: str) -> BaseExchange:
        """Get or create an exchange instance."""
        if exchange_id not in self._exchanges:
            self._exchanges[exchange_id] = create_exchange(
                exchange_id, verbose=False, validate=False
            )
        return self._exchanges[exchange_id]

    def _fetch_market(self, exchange_id: str, market_id: str) -> List[Market]:
        """Fetch market(s) from an exchange."""
        exchange = self._get_exchange(exchange_id)

        # Use fetch_markets_by_slug if available (e.g., polymarket)
        if hasattr(exchange, "fetch_markets_by_slug"):
            try:
                return exchange.fetch_markets_by_slug(market_id)
            except Exception:
                pass

        return [exchange.fetch_market(market_id)]

    def _get_fetch_ids(self, slug: str) -> Dict[str, set]:
        """Extract unique fetch IDs per exchange from outcome mapping."""
        return _extract_fetch_slugs(self.mapping, slug)

    def fetch(self, slug: str) -> FetchedMarkets:
        """
        Fetch markets for a given slug.

        Args:
            slug: Outcome mapping key

        Returns:
            FetchedMarkets with markets and outcome mapping
        """
        markets: Dict[str, List[Market]] = {}
        fetch_ids = self._get_fetch_ids(slug)

        for exchange_id, ids in fetch_ids.items():
            markets[exchange_id] = []
            for fetch_id in ids:
                try:
                    fetched = self._fetch_market(exchange_id, fetch_id)
                    markets[exchange_id].extend(fetched)
                except Exception as e:
                    print(f"[{exchange_id}] Error fetching {fetch_id}: {e}")

        outcome_mapping = self.mapping.get(slug, {})
        return FetchedMarkets(slug=slug, markets=markets, outcome_mapping=outcome_mapping)

    def fetch_all(self) -> List[FetchedMarkets]:
        """Fetch markets for all slugs."""
        return [self.fetch(slug) for slug in self.mapping]

    @property
    def slugs(self) -> List[str]:
        """List of configured slugs."""
        return list(self.mapping.keys())
