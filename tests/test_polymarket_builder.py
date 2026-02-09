"""Tests for PolymarketBuilder exchange class."""

import pytest
from dr_manhattan.exchanges.polymarket_builder import PolymarketBuilder

from dr_manhattan.base.errors import AuthenticationError


class TestPolymarketBuilderInit:
    """Tests for PolymarketBuilder initialization."""

    def test_requires_all_credentials(self):
        """Test that all three credentials are required."""
        with pytest.raises(
            AuthenticationError, match="requires api_key, api_secret, and api_passphrase"
        ):
            PolymarketBuilder({"api_key": "test"})

        with pytest.raises(
            AuthenticationError, match="requires api_key, api_secret, and api_passphrase"
        ):
            PolymarketBuilder({"api_key": "test", "api_secret": "test"})

    def test_initializes_with_all_credentials(self):
        """Test that it initializes with all credentials."""
        exchange = PolymarketBuilder(
            {
                "api_key": "test_key",
                "api_secret": "test_secret",
                "api_passphrase": "test_pass",
            }
        )

        assert exchange.id == "polymarket"
        assert exchange.name == "Polymarket"
        assert exchange._clob_client is not None
        assert exchange._clob_client.can_builder_auth()

    def test_no_private_key_stored(self):
        """Test that no private key is stored."""
        exchange = PolymarketBuilder(
            {
                "api_key": "test_key",
                "api_secret": "test_secret",
                "api_passphrase": "test_pass",
            }
        )

        assert exchange.private_key is None
        assert exchange.funder is None


class TestPolymarketBuilderMethods:
    """Tests for PolymarketBuilder methods."""

    @pytest.fixture
    def builder_exchange(self):
        """Create a PolymarketBuilder instance for testing."""
        return PolymarketBuilder(
            {
                "api_key": "test_key",
                "api_secret": "test_secret",
                "api_passphrase": "test_pass",
            }
        )

    def test_inherits_from_polymarket(self, builder_exchange):
        """Test that PolymarketBuilder inherits from Polymarket."""
        from dr_manhattan.exchanges.polymarket import Polymarket

        assert isinstance(builder_exchange, Polymarket)

    def test_has_read_methods(self, builder_exchange):
        """Test that read methods are inherited."""
        assert hasattr(builder_exchange, "fetch_markets")
        assert hasattr(builder_exchange, "fetch_market")
        assert hasattr(builder_exchange, "get_orderbook")
        assert hasattr(builder_exchange, "search_markets")

    def test_has_write_methods(self, builder_exchange):
        """Test that write methods are available."""
        assert hasattr(builder_exchange, "create_order")
        assert hasattr(builder_exchange, "cancel_order")
        assert hasattr(builder_exchange, "fetch_balance")
        assert hasattr(builder_exchange, "fetch_open_orders")
