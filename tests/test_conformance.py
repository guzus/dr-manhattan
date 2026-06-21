"""Cross-exchange conformance: the unified contract every adapter must honor.

These assert behavior that should be identical across exchanges, and document
the one place the contract is intentionally NOT uniform - the per-exchange
balance currency key (USDC / USD / USDT), which the NAV layer reconciles.
"""

import pytest

from dr_manhattan.base.exchange_client import ExchangeClient
from dr_manhattan.exchanges.kalshi import Kalshi
from dr_manhattan.exchanges.limitless import Limitless
from dr_manhattan.exchanges.opinion import Opinion
from dr_manhattan.exchanges.polymarket import Polymarket
from dr_manhattan.exchanges.predictfun import PredictFun
from dr_manhattan.models.market import Market

ADAPTERS = [Kalshi, Polymarket, Opinion, Limitless, PredictFun]

UNIFIED_METHODS = [
    "fetch_markets",
    "fetch_market",
    "create_order",
    "cancel_order",
    "fetch_order",
    "fetch_open_orders",
    "fetch_positions",
    "fetch_balance",
]


@pytest.mark.parametrize("adapter_cls", ADAPTERS)
def test_adapter_implements_unified_contract(adapter_cls):
    """Every adapter constructs without credentials and exposes the contract."""
    exchange = adapter_cls()

    for method in UNIFIED_METHODS:
        impl = getattr(exchange, method, None)
        assert callable(impl), f"{adapter_cls.__name__}.{method} is missing"

    desc = exchange.describe()
    assert desc["id"]
    assert desc["name"]
    assert isinstance(desc["has"], dict)


@pytest.mark.parametrize("currency", ["USDC", "USD", "USDT"])
def test_nav_cash_handles_each_exchange_currency_key(currency):
    """fetch_balance is keyed by collateral currency, which differs per exchange
    (USDC on Polymarket, USD on Kalshi, USDT on Predict.fun). The unified NAV
    layer must value all of them as cash so consumers stay exchange-agnostic."""
    client = ExchangeClient(Kalshi())

    nav = client._calculate_nav_internal(positions=[], prices=None, balance={currency: 100.0})

    assert nav.cash == 100.0
    assert nav.nav == 100.0


def test_market_enforces_price_normalization():
    """The Market boundary is the one place prices are guaranteed to be in [0, 1];
    a cents-denominated price (65) must be rejected, not silently accepted."""
    with pytest.raises(ValueError):
        Market(
            id="m",
            question="?",
            outcomes=["Yes", "No"],
            close_time=None,
            volume=0.0,
            liquidity=0.0,
            prices={"Yes": 65, "No": 35},
            metadata={},
            tick_size=0.01,
        )
