"""Top-of-book primitives for cross-venue market data."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping

BPS = Decimal("10000")


@dataclass(frozen=True)
class Level:
    """One positive price/size orderbook level."""

    price: Decimal
    size: Decimal

    @property
    def notional(self) -> Decimal:
        return self.price * self.size


@dataclass(frozen=True)
class TopBook:
    """Normalized top-of-book depth with Decimal prices and sizes."""

    bids: tuple[Level, ...] = ()
    asks: tuple[Level, ...] = ()
    source_ts_ms: int | None = None
    asset_id: str = ""
    market_id: str = ""

    @classmethod
    def from_raw(
        cls,
        payload: Mapping[str, Any],
        *,
        asset_id: str = "",
        market_id: str = "",
        depth: int | None = None,
    ) -> "TopBook":
        """Parse common REST/WebSocket orderbook shapes.

        Levels may be dicts like ``{"price": "0.5", "size": "10"}`` or
        tuple/list pairs like ``["0.5", "10"]``. Invalid and non-positive
        levels are ignored. Bids are sorted descending and asks ascending.
        """

        bids = levels(payload.get("bids", ()), reverse=True, depth=depth)
        asks = levels(payload.get("asks", ()), reverse=False, depth=depth)
        return cls(
            bids=tuple(bids),
            asks=tuple(asks),
            source_ts_ms=source_ts_ms(payload),
            asset_id=asset_id or str(payload.get("asset_id") or payload.get("assetId") or ""),
            market_id=market_id or str(payload.get("market_id") or payload.get("market") or ""),
        )

    @property
    def bid(self) -> Level | None:
        return self.bids[0] if self.bids else None

    @property
    def ask(self) -> Level | None:
        return self.asks[0] if self.asks else None

    @property
    def best_bid(self) -> Decimal | None:
        return self.bid.price if self.bid else None

    @property
    def best_ask(self) -> Decimal | None:
        return self.ask.price if self.ask else None

    @property
    def bid_size(self) -> Decimal | None:
        return self.bid.size if self.bid else None

    @property
    def ask_size(self) -> Decimal | None:
        return self.ask.size if self.ask else None

    @property
    def mid_price(self) -> Decimal | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return (self.best_bid + self.best_ask) / 2

    @property
    def fair(self) -> Decimal | None:
        return self.mid_price

    @property
    def spread(self) -> Decimal | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return self.best_ask - self.best_bid

    def to_dict(self) -> dict[str, Any]:
        return {
            "bids": [level_to_dict(level) for level in self.bids],
            "asks": [level_to_dict(level) for level in self.asks],
            "source_ts_ms": self.source_ts_ms,
            "asset_id": self.asset_id,
            "market_id": self.market_id,
        }


@dataclass(frozen=True)
class Quote:
    """A venue/outcome quote backed by a normalized top book."""

    venue: str
    market_id: str
    outcome: str
    token_id: str
    book: TopBook
    observed_ms: int
    key: str = ""
    question: str = ""

    @property
    def bid(self) -> Decimal | None:
        return self.book.best_bid

    @property
    def ask(self) -> Decimal | None:
        return self.book.best_ask

    @property
    def bid_size(self) -> Decimal | None:
        return self.book.bid_size

    @property
    def ask_size(self) -> Decimal | None:
        return self.book.ask_size

    @property
    def fair(self) -> Decimal | None:
        return self.book.fair


def levels(raw_levels: Iterable[Any], *, reverse: bool, depth: int | None = None) -> list[Level]:
    parsed: list[Level] = []
    for raw in raw_levels or ():
        price, size = raw_level(raw)
        if price is not None and size is not None:
            parsed.append(Level(price, size))
    parsed.sort(key=lambda level: level.price, reverse=reverse)
    return parsed[:depth] if depth is not None and depth >= 0 else parsed


def raw_level(raw: Any) -> tuple[Decimal | None, Decimal | None]:
    if isinstance(raw, Mapping):
        return positive_decimal(raw.get("price")), positive_decimal(raw.get("size"))
    if isinstance(raw, (list, tuple)) and len(raw) >= 2:
        return positive_decimal(raw[0]), positive_decimal(raw[1])
    return None, None


def positive_decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed > 0 else None


def source_ts_ms(payload: Mapping[str, Any]) -> int | None:
    raw = (
        payload.get("source_ts_ms")
        or payload.get("sourceTsMs")
        or payload.get("updateTimestampMs")
        or payload.get("timestamp")
    )
    if isinstance(raw, bool):
        return None
    try:
        value = int(Decimal(str(raw)))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return value * 1000 if value < 10_000_000_000 else value


def edge(left: Decimal | None, *subtract: Decimal | None) -> Decimal | None:
    """Return ``left - subtract...`` when every term is present."""

    if left is None or any(value is None for value in subtract):
        return None
    value = left
    for term in subtract:
        if term is None:
            return None
        value -= term
    return value


def edge_bps(value: Decimal | None) -> int | None:
    return int(value * BPS) if value is not None else None


def min_size(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    if left is None or right is None:
        return left or right
    return min(left, right)


def level_to_dict(level: Level) -> dict[str, str]:
    return {"price": str(level.price), "size": str(level.size)}
