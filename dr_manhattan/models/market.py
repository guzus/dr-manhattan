from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Readable market ID as a path-like list:
# - ["61"] for simple ID (Opinion)
# - ["fed-decision-in-january", "No change"] for hierarchical (Polymarket)
ReadableMarketId = List[str]

START_TIME_METADATA_KEYS = (
    "start_time",
    "event_start_time",
    "eventStartTime",
    "game_start_time",
    "gameStartTime",
    "match_start_time",
    "matchStartTime",
    "startTime",
    "startAt",
    "start_at",
    "startsAt",
    "starts_at",
    "scheduledTime",
    "scheduled_time",
    "kickoff",
    "kickoffTime",
    "kickoff_time",
    "kickoffAt",
    "kickoff_at",
    "gameStart",
    "game_start",
)

END_TIME_METADATA_KEYS = (
    "end_time",
    "event_end_time",
    "eventEndTime",
    "endTime",
    "endAt",
    "end_at",
    "closeTime",
    "close_time",
    "expirationTimestamp",
    "expirationTime",
    "expiresAt",
    "expiry",
    "deadline",
    "endDate",
    "end_date",
    "endDateIso",
    "end_date_iso",
    "closedAt",
    "closed_at",
    "expirationDate",
    "resolvedAt",
    "resolutionTime",
)

DATE_FORMATS = (
    "%Y-%m-%d",
    "%b %d, %Y",
    "%B %d, %Y",
    "%b %d %Y",
    "%B %d %Y",
)

EPOCH_MILLISECONDS_THRESHOLD = 10_000_000_000


def _datetime_from_epoch(value: float) -> Optional[datetime]:
    if value <= 0:
        return None

    # Present-day exchange APIs use 13-digit millisecond epochs; a seconds epoch
    # above this threshold would be year 2286+, outside supported market windows.
    timestamp = value / 1000 if value > EPOCH_MILLISECONDS_THRESHOLD else value
    try:
        return datetime.fromtimestamp(timestamp, timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None


def _as_utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def parse_market_datetime(value: Any) -> Optional[datetime]:
    """Parse exchange timestamp shapes into a datetime."""
    if value is None or value == "":
        return None

    if isinstance(value, datetime):
        return _as_utc_datetime(value)

    if isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        return _datetime_from_epoch(value)

    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None

        try:
            timestamp = float(stripped)
        except ValueError:
            timestamp = None

        if timestamp is not None:
            return _datetime_from_epoch(timestamp)

        try:
            return _as_utc_datetime(datetime.fromisoformat(stripped.replace("Z", "+00:00")))
        except ValueError:
            pass

        for date_format in DATE_FORMATS:
            try:
                return _as_utc_datetime(datetime.strptime(stripped, date_format))
            except ValueError:
                continue

    return None


def _metadata_datetime(metadata: Dict[str, Any], keys: tuple[str, ...]) -> Optional[datetime]:
    for key in keys:
        parsed = parse_market_datetime(metadata.get(key))
        if parsed is not None:
            return parsed
    return None


@dataclass
class OutcomeRef:
    """Reference to locate an outcome (market_id + outcome name)."""

    market_id: str
    outcome: str


@dataclass
class OutcomeToken(OutcomeRef):
    """Tradeable outcome with token ID (extends OutcomeRef)."""

    token_id: str


@dataclass
class ExchangeOutcomeRef:
    """Full cross-exchange reference: exchange + market + outcome.

    market_path is a path-like list:
    - ["61"] for simple ID
    - ["fetch-slug", "match-id"] for hierarchical

    Properties:
    - fetch_slug: First element, used to fetch markets from exchange
    - match_id: Last element, used to match against Market.id or metadata["match_id"]
    """

    exchange_id: str
    market_path: ReadableMarketId
    outcome: str

    @property
    def fetch_slug(self) -> str:
        """First element of market_path, used to fetch markets."""
        return self.market_path[0]

    @property
    def match_id(self) -> str:
        """Last element of market_path, used to match against Market.id."""
        return self.market_path[-1]

    def to_outcome_ref(self) -> OutcomeRef:
        return OutcomeRef(market_id=self.market_path[0], outcome=self.outcome)


@dataclass
class Market:
    """Represents a prediction market"""

    id: str
    question: str
    outcomes: list[str]
    close_time: Optional[datetime]
    volume: float
    liquidity: float
    prices: Dict[str, float]  # outcome -> price (0-1)
    metadata: Dict[str, Any]
    tick_size: float
    description: str = ""  # Resolution criteria

    def __post_init__(self):
        for outcome, price in self.prices.items():
            if not (0 <= price <= 1):
                raise ValueError(f"Price for '{outcome}' must be between 0 and 1, got {price}")

    @property
    def readable_id(self) -> ReadableMarketId:
        """Get readable market ID as a path-like list.

        Returns metadata["readable_id"] if set by exchange,
        otherwise falls back to [self.id].
        """
        return self.metadata.get("readable_id", [self.id])

    @property
    def is_binary(self) -> bool:
        """Check if market is binary (Yes/No)"""
        return len(self.outcomes) == 2

    @property
    def start_time(self) -> Optional[datetime]:
        """Get normalized event start time from exchange metadata."""
        return _metadata_datetime(self.metadata, START_TIME_METADATA_KEYS)

    @property
    def end_time(self) -> Optional[datetime]:
        """Get normalized trading close or event end time."""
        if self.close_time is not None:
            return _as_utc_datetime(self.close_time)
        return _metadata_datetime(self.metadata, END_TIME_METADATA_KEYS)

    @property
    def event_time(self) -> Optional[datetime]:
        """Get the best available timestamp for scheduling around this market."""
        return self.start_time or self.end_time

    @property
    def is_open(self) -> bool:
        """Check if market is still open for trading"""
        # Check metadata for explicit closed status (e.g., Polymarket)
        if "closed" in self.metadata:
            closed = self.metadata["closed"]
            if isinstance(closed, str):
                closed_value = closed.strip().lower()
                if closed_value in ("true", "1", "yes", "closed", "resolved"):
                    return False
                if closed_value in ("false", "0", "no", "open", "active"):
                    pass
                elif closed_value:
                    return False
            elif closed:
                return False

        # Fallback to normalized end_time check
        end_time = self.end_time
        if not end_time:
            return True

        return datetime.now(timezone.utc) < end_time

    @property
    def spread(self) -> Optional[float]:
        """Get bid-ask spread for binary markets"""
        if not self.is_binary or len(self.outcomes) != 2:
            return None

        prices = list(self.prices.values())
        if len(prices) != 2:
            return None

        # For binary markets, spread is typically 1 - sum of probabilities
        # (when prices sum to exactly 1, spread is 0)
        return abs(1.0 - sum(prices))

    def get_outcome_ref(self, outcome: str) -> OutcomeRef:
        """Get reference to a specific outcome."""
        return OutcomeRef(market_id=self.id, outcome=outcome)

    def get_outcome_refs(self) -> List[OutcomeRef]:
        """Get references for all outcomes."""
        return [OutcomeRef(market_id=self.id, outcome=o) for o in self.outcomes]

    def get_outcome_tokens(self) -> List[OutcomeToken]:
        """Get all tradeable outcomes with their token IDs."""
        tokens = self.metadata.get("tokens", {})
        return [
            OutcomeToken(market_id=self.id, outcome=o, token_id=tokens.get(o, ""))
            for o in self.outcomes
            if o in tokens
        ]
