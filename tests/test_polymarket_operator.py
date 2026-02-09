"""Tests for PolymarketOperator exchange class."""

import os
from unittest.mock import patch

import pytest

from dr_manhattan.base.errors import AuthenticationError
from dr_manhattan.exchanges.polymarket_operator import PolymarketOperator


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
