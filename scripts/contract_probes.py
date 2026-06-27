"""Public-data probes per exchange: how to fetch raw market data and parse it.

Shared by two consumers:
  - tests/test_fixtures.py    replays committed golden fixtures through the parsers
                              (hermetic, runs in normal CI)
  - scripts/contract_drift_check.py  hits the LIVE public APIs and flags when an
                              exchange changes its response shape (scheduled CI)

The parser seam is each exchange's ``_parse_market(dict) -> Market``. Market's
__post_init__ enforces price in [0, 1], so if an exchange silently switches units
(e.g. cents instead of a 0-1 probability) the parse raises - which is exactly the
drift signal we want.

Only exchanges with a reachable, no-auth public market endpoint are probed here.
Opinion uses the CLOB SDK (no simple public REST list) and is intentionally omitted;
add a probe when a public endpoint exists.
"""

from dataclasses import dataclass
from typing import Any, Callable, List, Optional

import requests

from dr_manhattan.exchanges.kalshi import Kalshi
from dr_manhattan.exchanges.limitless import Limitless
from dr_manhattan.exchanges.polymarket import Polymarket
from dr_manhattan.models.market import Market


@dataclass
class ExchangeProbe:
    id: str
    url: str
    make_exchange: Callable[[], Any]
    extract: Callable[[Any], List[dict]]  # response json -> list of raw market dicts
    parse_one: Callable[[Any, dict], Optional[Market]]  # (exchange, raw dict) -> Market

    def fetch_raw(self, timeout: float = 15.0) -> List[dict]:
        resp = requests.get(self.url, timeout=timeout)
        resp.raise_for_status()
        return self.extract(resp.json())

    def parse(self, raw_markets: List[dict]) -> List[Market]:
        exchange = self.make_exchange()
        parsed: List[Market] = []
        for raw in raw_markets:
            market = self.parse_one(exchange, raw)
            if market is not None:
                parsed.append(market)
        return parsed


PROBES: List[ExchangeProbe] = [
    ExchangeProbe(
        id="kalshi",
        url="https://api.elections.kalshi.com/trade-api/v2/markets?limit=20&status=open",
        make_exchange=Kalshi,
        extract=lambda j: j.get("markets", []),
        parse_one=lambda ex, d: ex._parse_market(d),
    ),
    ExchangeProbe(
        id="polymarket",
        url="https://gamma-api.polymarket.com/markets?limit=20&active=true&closed=false",
        make_exchange=Polymarket,
        extract=lambda j: j if isinstance(j, list) else j.get("data", []),
        parse_one=lambda ex, d: ex._parse_market(d),
    ),
    ExchangeProbe(
        id="limitless",
        url="https://api.limitless.exchange/markets/active?limit=20",
        make_exchange=Limitless,
        extract=lambda j: j.get("data", []) if isinstance(j, dict) else j,
        parse_one=lambda ex, d: ex._parse_market(d),
    ),
]

PROBES_BY_ID = {p.id: p for p in PROBES}


def assert_market_invariants(market: Market) -> None:
    """The unified contract every parsed Market must satisfy, regardless of source.

    Market.__post_init__ already enforces price in [0, 1]; this adds the rest of the
    cross-exchange shape so a regression in any single parser is caught uniformly.
    """
    assert market.id, "market id is empty"
    has_two_outcomes = isinstance(market.outcomes, list) and len(market.outcomes) >= 2
    assert has_two_outcomes, f"expected >= 2 outcomes, got {market.outcomes!r}"
    assert isinstance(market.prices, dict), f"prices is not a dict: {type(market.prices).__name__}"
    for outcome, price in market.prices.items():
        assert 0.0 <= price <= 1.0, f"price out of [0, 1]: {outcome}={price}"
