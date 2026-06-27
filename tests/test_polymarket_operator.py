"""Tests for PolymarketOperator exchange class."""

import os
from unittest.mock import patch

import pytest

from dr_manhattan.base.errors import AuthenticationError
from dr_manhattan.exchanges.polymarket_operator import PolymarketOperator
from dr_manhattan.models.market import Market


class TestPolymarketOperatorInit:
    """Tests for PolymarketOperator initialization."""

    def test_requires_operator_key_env_var(self):
        """Test that POLYMARKET_OPERATOR_KEY is required."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(
                AuthenticationError,
                match="POLYMARKET_OPERATOR_KEY environment variable is required",
            ):
                PolymarketOperator({"user_address": "0x1234"})

    def test_requires_user_address(self):
        """Test that user_address is required in config."""
        with patch.dict(os.environ, {"POLYMARKET_OPERATOR_KEY": "0x" + "a" * 64}):
            with pytest.raises(AuthenticationError, match="user_address is required"):
                PolymarketOperator({})

    def test_requires_both_operator_key_and_user_address(self):
        """Test that both operator key and user address are needed."""
        # Missing operator key
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(AuthenticationError):
                PolymarketOperator({"user_address": "0x1234"})

        # Missing user address
        with patch.dict(os.environ, {"POLYMARKET_OPERATOR_KEY": "0x" + "a" * 64}):
            with pytest.raises(AuthenticationError):
                PolymarketOperator({})


class TestPolymarketOperatorProperties:
    """Tests for PolymarketOperator properties."""

    def test_user_address_property(self):
        """Test user_address property returns the configured address."""
        test_address = "0x1234567890abcdef1234567890abcdef12345678"
        with patch.dict(os.environ, {"POLYMARKET_OPERATOR_KEY": "0x" + "a" * 64}):
            with patch.object(PolymarketOperator, "_initialize_operator_client", return_value=None):
                operator = object.__new__(PolymarketOperator)
                operator._user_address = test_address
                assert operator.user_address == test_address

    def test_inherits_from_polymarket(self):
        """Test that PolymarketOperator inherits from Polymarket."""
        from dr_manhattan.exchanges.polymarket import Polymarket

        assert issubclass(PolymarketOperator, Polymarket)


class TestPolymarketOperatorMethods:
    """Tests for PolymarketOperator methods."""

    def test_has_trading_methods(self):
        """Test that trading methods are defined."""
        assert hasattr(PolymarketOperator, "create_order")
        assert hasattr(PolymarketOperator, "cancel_order")
        assert hasattr(PolymarketOperator, "fetch_balance")
        assert hasattr(PolymarketOperator, "fetch_open_orders")
        assert hasattr(PolymarketOperator, "fetch_positions")

    def test_has_operator_specific_methods(self):
        """Test that operator-specific methods exist."""
        assert hasattr(PolymarketOperator, "check_operator_approval")


class TestPolymarketOperatorPositions:
    """Operator reads positions from the public Data API (keyed by wallet address)."""

    def _operator(self, user_address="0xUser"):
        # Bypass __init__ (needs an operator key + live CLOB client); we only
        # exercise fetch_positions, which needs _user_address and the data mixin.
        operator = object.__new__(PolymarketOperator)
        operator._user_address = user_address
        return operator

    def test_fetch_positions_parses_data_api_response(self):
        operator = self._operator()
        raw = [
            {
                "conditionId": "0xcond1",
                "outcome": "Yes",
                "size": 12.0,
                "avgPrice": 0.4,
                "curPrice": 0.55,
            },
            {  # zero size must be filtered out
                "conditionId": "0xcond2",
                "outcome": "No",
                "size": 0,
                "avgPrice": 0.0,
                "curPrice": 0.0,
            },
        ]

        with patch.object(
            PolymarketOperator, "fetch_positions_data", return_value=raw
        ) as mock_data:
            positions = operator.fetch_positions()

        # #then the wallet's positions are returned (no longer an empty list)
        mock_data.assert_called_once_with("0xUser")
        assert len(positions) == 1
        assert positions[0].market_id == "0xcond1"
        assert positions[0].outcome == "Yes"
        assert positions[0].size == 12.0
        assert positions[0].average_price == 0.4
        assert positions[0].current_price == 0.55

    def test_fetch_positions_filters_by_resolved_condition_id(self):
        operator = self._operator()
        raw = [
            {
                "conditionId": "0xcond1",
                "outcome": "Yes",
                "size": 5.0,
                "avgPrice": 0.4,
                "curPrice": 0.5,
            },
            {
                "conditionId": "0xcond2",
                "outcome": "Yes",
                "size": 7.0,
                "avgPrice": 0.3,
                "curPrice": 0.6,
            },
        ]
        market = Market(
            id="0xcond2",
            question="?",
            outcomes=["Yes", "No"],
            close_time=None,
            volume=0.0,
            liquidity=0.0,
            prices={"Yes": 0.6, "No": 0.4},
            metadata={"conditionId": "0xcond2"},
            tick_size=0.01,
        )

        with patch.object(PolymarketOperator, "fetch_positions_data", return_value=raw):
            with patch.object(PolymarketOperator, "fetch_market", return_value=market):
                positions = operator.fetch_positions(market_id="0xcond2")

        assert len(positions) == 1
        assert positions[0].market_id == "0xcond2"
        assert positions[0].size == 7.0
