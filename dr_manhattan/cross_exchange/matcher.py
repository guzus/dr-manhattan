"""Market matching strategies for cross-exchange comparison."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..models.market import ExchangeOutcomeRef, Market


@dataclass
class MatchCandidate:
    """A potential match between markets on different exchanges."""

    market_a: ExchangeOutcomeRef
    market_b: ExchangeOutcomeRef
    score: float  # 0-1 confidence
    signals: Dict[str, float] = field(default_factory=dict)

    @property
    def is_strong_match(self) -> bool:
        return self.score >= 0.8

    @property
    def is_weak_match(self) -> bool:
        return 0.5 <= self.score < 0.8


class MatchStrategy(ABC):
    """Base class for matching strategies."""

    name: str = "base"

    @abstractmethod
    def score(self, market_a: Market, market_b: Market) -> float:
        """
        Return match score between 0-1.

        Args:
            market_a: First market to compare
            market_b: Second market to compare

        Returns:
            Score from 0 (no match) to 1 (perfect match)
        """
        pass


class CategoryMatchStrategy(MatchStrategy):
    """Base class for category-specific matchers."""

    name = "category"
    category: str = "generic"

    def score(self, market_a: Market, market_b: Market) -> float:
        # Subclasses implement category-specific matching
        return 0.0


class FedDecisionMatcher(CategoryMatchStrategy):
    """Match Fed rate decision markets."""

    name = "fed_decision"
    category = "fed"

    def score(self, market_a: Market, market_b: Market) -> float:
        # TODO: Match Fed decision markets by date and outcome structure
        # Known patterns: rate changes, FOMC meetings
        return 0.0


class ElectionMatcher(CategoryMatchStrategy):
    """Match political election markets."""

    name = "election"
    category = "politics"

    def score(self, market_a: Market, market_b: Market) -> float:
        # TODO: Match by election type, candidates, date
        return 0.0


class CryptoHourlyMatcher(CategoryMatchStrategy):
    """Match crypto hourly price prediction markets."""

    name = "crypto_hourly"
    category = "crypto"

    def score(self, market_a: Market, market_b: Market) -> float:
        # TODO: Match by asset, time window, price target
        return 0.0


class LLMMatchStrategy(MatchStrategy):
    """LLM-based semantic matching via OpenRouter."""

    name = "llm"

    def __init__(
        self,
        provider: str = "openrouter",
        model: str = "meta-llama/llama-3-8b-instruct:free",
        api_key: Optional[str] = None,
    ):
        self.provider = provider
        self.model = model
        self.api_key = api_key

    def score(self, market_a: Market, market_b: Market) -> float:
        # TODO: Implement LLM-based matching
        # 1. Format prompt with market questions/outcomes
        # 2. Call OpenRouter API
        # 3. Parse response for match score
        return 0.0


class MarketMatcher:
    """Finds matching markets across exchanges."""

    def __init__(
        self,
        strategies: Optional[List[MatchStrategy]] = None,
        weights: Optional[Dict[str, float]] = None,
    ):
        self.strategies = strategies or []
        self.weights = weights or {s.name: 1.0 for s in self.strategies}

    def _compute_score(self, market_a: Market, market_b: Market) -> tuple:
        """Compute weighted score and signal breakdown."""
        signals: Dict[str, float] = {}
        total_weight = 0.0
        weighted_sum = 0.0

        for strategy in self.strategies:
            signal = strategy.score(market_a, market_b)
            signals[strategy.name] = signal
            weight = self.weights.get(strategy.name, 1.0)
            weighted_sum += signal * weight
            total_weight += weight

        score = weighted_sum / total_weight if total_weight > 0 else 0.0
        return score, signals

    def find_matches(
        self,
        source_markets: List[Market],
        target_markets: List[Market],
        source_exchange: str,
        target_exchange: str,
        threshold: float = 0.7,
    ) -> List[MatchCandidate]:
        """
        Find matching markets above threshold.

        Args:
            source_markets: Markets from source exchange
            target_markets: Markets from target exchange
            source_exchange: Source exchange ID
            target_exchange: Target exchange ID
            threshold: Minimum score to consider a match

        Returns:
            List of match candidates sorted by score descending
        """
        candidates: List[MatchCandidate] = []

        for src in source_markets:
            for tgt in target_markets:
                score, signals = self._compute_score(src, tgt)

                if score >= threshold:
                    candidates.append(
                        MatchCandidate(
                            market_a=ExchangeOutcomeRef(
                                exchange_id=source_exchange,
                                market_id=src.id,
                                outcome="",  # Outcome alignment is separate step
                            ),
                            market_b=ExchangeOutcomeRef(
                                exchange_id=target_exchange,
                                market_id=tgt.id,
                                outcome="",
                            ),
                            score=score,
                            signals=signals,
                        )
                    )

        return sorted(candidates, key=lambda c: c.score, reverse=True)

    def find_best_match(
        self,
        source_market: Market,
        target_markets: List[Market],
        source_exchange: str,
        target_exchange: str,
        threshold: float = 0.7,
    ) -> Optional[MatchCandidate]:
        """Find the best matching market for a single source market."""
        matches = self.find_matches(
            [source_market],
            target_markets,
            source_exchange,
            target_exchange,
            threshold,
        )
        return matches[0] if matches else None
