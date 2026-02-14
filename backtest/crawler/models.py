import asyncio
import time
from dataclasses import dataclass, field
from typing import Dict, List, Set

# ========== EVENT TYPE CONSTANTS ==========

EVENT_BOOK = "book"
EVENT_PRICE_CHANGE = "price_change"
EVENT_TICK_SIZE_CHANGE = "tick_size_change"
EVENT_LAST_TRADE_PRICE = "last_trade_price"

EVENT_TYPES = [
    EVENT_BOOK,
    EVENT_PRICE_CHANGE,
    EVENT_TICK_SIZE_CHANGE,
    EVENT_LAST_TRADE_PRICE,
]


# ========== DATA CLASSES ==========


@dataclass
class MarketConfig:
    name: str
    slug: str
    keywords: List[str]
    rule: str
    window_minutes: int
    prefix: str
    freq: str | None = None


@dataclass
class AssetMeta:
    asset_id: str
    market_id: str
    question: str
    close_time_str: str
    outcome: str
    freq: str
    prefix: str


# ========== TTL DEDUP (Fix #1) ==========


class TTLDedup:
    """TTL-based deduplication replacing unbounded set growth."""

    def __init__(self, ttl_seconds: float = 300):
        self._seen: Dict[str, float] = {}
        self._ttl = ttl_seconds

    def mark_seen(self, key: str) -> bool:
        """Returns True if key is new (not seen), False if duplicate."""
        now = time.monotonic()
        if key in self._seen:
            return False
        self._seen[key] = now
        return True

    def cleanup(self):
        """Remove entries older than TTL."""
        cutoff = time.monotonic() - self._ttl
        self._seen = {k: v for k, v in self._seen.items() if v > cutoff}

    def __len__(self):
        return len(self._seen)


# ========== SHARED STATE ==========


@dataclass
class SharedState:
    desired_asset_ids: Set[str] = field(default_factory=set)
    subscribed_asset_ids: Set[str] = field(default_factory=set)
    asset_meta: Dict[str, AssetMeta] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # Fix #4: asyncio.Event instead of bool flag
    resubscribe_event: asyncio.Event = field(default_factory=asyncio.Event)
    # Fix #1: TTL dedup per event type
    seen_event_hashes: Dict[str, TTLDedup] = field(default_factory=dict)

    def mark_event_seen(self, event_type: str, asset_id: str, event_hash: str) -> bool:
        key = f"{asset_id}:{event_hash}"
        dedup = self.seen_event_hashes.setdefault(event_type, TTLDedup())
        return dedup.mark_seen(key)
