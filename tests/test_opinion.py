"""Tests for Opinion exchange implementation."""

from unittest.mock import MagicMock

import pytest

from dr_manhattan import Opinion, OrderSide, OrderStatus
from dr_manhattan.base.errors import AuthenticationError, MarketNotFound


class TestOpinionBasic:
    """Basic Opinion exchange tests."""

    def test_exchange_properties(self):
        """Test exchange id and name properties."""
        # Create without credentials (won't initialize client)
        exchange = Opinion({"api_key": "", "private_key": "", "multi_sig_addr": ""})
        assert exchange.id == "opinion"
        assert exchange.name == "Opinion"

    def test_describe(self):
        """Test describe method returns correct capabilities."""
        exchange = Opinion({})
        info = exchange.describe()

        assert info["id"] == "opinion"
        assert info["name"] == "Opinion"
        assert info["chain_id"] == 56
        assert info["has"]["fetch_markets"] is True
        assert info["has"]["create_order"] is True
        assert info["has"]["cancel_order"] is True
        assert info["has"]["fetch_positions"] is True
        assert info["has"]["fetch_balance"] is True

    def test_client_not_initialized_without_credentials(self):
        """Test that client is not initialized without proper credentials."""
        exchange = Opinion({})
        assert exchange._client is None

    def test_ensure_client_raises_without_credentials(self):
        """Test that operations requiring client raise AuthenticationError."""
        exchange = Opinion({})

        with pytest.raises(AuthenticationError):
            exchange.fetch_markets()

        with pytest.raises(AuthenticationError):
            exchange.fetch_market("123")

        with pytest.raises(AuthenticationError):
            exchange.fetch_balance()


class TestOpinionMarketParsing:
    """Test market parsing logic."""

    def test_parse_market_basic(self):
        """Test parsing basic market data."""
        exchange = Opinion({})

        # Create mock market data matching actual API structure
        mock_data = MagicMock(spec=[])
        mock_data.market_id = 123
        mock_data.market_title = "Will BTC reach $100k?"
        mock_data.yes_token_id = "token_yes"
        mock_data.no_token_id = "token_no"
        mock_data.yes_label = "Yes"
        mock_data.no_label = "No"
        mock_data.child_markets = None
        mock_data.cutoff_time = 1735689600
        mock_data.volume = "10000.0"
        mock_data.liquidity = "5000.0"
        mock_data.status = 2  # ACTIVATED
        mock_data.condition_id = "0xabc123"
        mock_data.chain_id = 56
        mock_data.quote_token = "0xusdc"
        mock_data.description = "Test market"
        mock_data.category = "Crypto"
        mock_data.image_url = ""

        market = exchange._parse_market(mock_data, fetch_prices=False)

        assert market.id == "123"
        assert market.question == "Will BTC reach $100k?"
        assert market.volume == 10000.0
        assert market.liquidity == 5000.0
        assert market.metadata["condition_id"] == "0xabc123"

    def test_parse_market_with_tokens(self):
        """Test parsing market with outcome tokens."""
        exchange = Opinion({})

        # Create mock data matching actual API structure
        mock_data = MagicMock(spec=[])  # spec=[] prevents auto-creating attributes
        mock_data.market_id = 456
        mock_data.market_title = "Test Market"
        mock_data.yes_token_id = "token_yes_123"
        mock_data.no_token_id = "token_no_456"
        mock_data.yes_label = "Yes"
        mock_data.no_label = "No"
        mock_data.child_markets = None
        mock_data.cutoff_time = None
        mock_data.volume = "0"
        mock_data.liquidity = "0"
        mock_data.status = 2
        mock_data.condition_id = ""
        mock_data.chain_id = 56
        mock_data.quote_token = ""
        mock_data.description = ""
        mock_data.category = ""
        mock_data.image_url = ""

        market = exchange._parse_market(mock_data, fetch_prices=False)

        assert market.id == "456"
        assert market.outcomes == ["Yes", "No"]
        assert market.metadata["token_ids"] == ["token_yes_123", "token_no_456"]
        assert market.metadata["tokens"]["Yes"] == "token_yes_123"
        assert market.metadata["tokens"]["No"] == "token_no_456"


class TestOpinionOrderParsing:
    """Test order parsing logic."""

    def test_parse_order_buy(self):
        """Test parsing buy order."""
        exchange = Opinion({})

        mock_data = MagicMock()
        mock_data.order_id = "order_123"
        mock_data.topic_id = 456
        mock_data.side = 0  # BUY
        mock_data.status = 1  # OPEN
        mock_data.price = 0.55
        mock_data.maker_amount = 100.0
        mock_data.matched_amount = 25.0
        mock_data.outcome = "Yes"
        mock_data.created_at = 1735689600

        order = exchange._parse_order(mock_data)

        assert order.id == "order_123"
        assert order.market_id == "456"
        assert order.side == OrderSide.BUY
        assert order.status == OrderStatus.OPEN
        assert order.price == 0.55
        assert order.size == 100.0
        assert order.filled == 25.0

    def test_parse_order_sell(self):
        """Test parsing sell order."""
        exchange = Opinion({})

        mock_data = MagicMock()
        mock_data.order_id = "order_456"
        mock_data.topic_id = 789
        mock_data.side = 1  # SELL
        mock_data.status = 2  # FILLED
        mock_data.price = 0.45
        mock_data.maker_amount = 50.0
        mock_data.matched_amount = 50.0
        mock_data.outcome = "No"
        mock_data.created_at = None

        order = exchange._parse_order(mock_data)

        assert order.id == "order_456"
        assert order.side == OrderSide.SELL
        assert order.status == OrderStatus.FILLED


class TestOpinionPositionParsing:
    """Test position parsing logic."""

    def test_parse_position(self):
        """Test parsing position data."""
        exchange = Opinion({})

        mock_data = MagicMock()
        mock_data.topic_id = 123
        mock_data.outcome = "Yes"
        mock_data.size = 100.0
        mock_data.average_price = 0.50
        mock_data.current_price = 0.65

        position = exchange._parse_position(mock_data)

        assert position.market_id == "123"
        assert position.outcome == "Yes"
        assert position.size == 100.0
        assert position.average_price == 0.50
        assert position.current_price == 0.65
        assert position.unrealized_pnl == 15.0  # (0.65 - 0.50) * 100


class TestOpinionWithMockedClient:
    """Tests with mocked Opinion client."""

    @pytest.fixture
    def mock_client(self):
        """Create a mocked Opinion client."""
        return MagicMock()

    @pytest.fixture
    def exchange_with_mock(self, mock_client):
        """Create exchange with mocked client."""
        exchange = Opinion({})
        exchange._client = mock_client
        return exchange

    def test_fetch_markets_success(self, exchange_with_mock, mock_client):
        """Test successful fetch_markets."""
        # Setup mock response matching actual API structure
        mock_market = MagicMock(spec=[])
        mock_market.market_id = 1
        mock_market.market_title = "Test Market"
        mock_market.yes_token_id = "token_yes"
        mock_market.no_token_id = "token_no"
        mock_market.yes_label = "Yes"
        mock_market.no_label = "No"
        mock_market.child_markets = None
        mock_market.cutoff_time = None
        mock_market.volume = "1000"
        mock_market.liquidity = "500"
        mock_market.status = 2
        mock_market.condition_id = "0x123"
        mock_market.chain_id = 56
        mock_market.quote_token = ""
        mock_market.description = ""
        mock_market.category = ""
        mock_market.image_url = ""

        mock_response = MagicMock()
        mock_response.errno = 0
        mock_response.result = MagicMock()
        mock_response.result.list = [mock_market]

        mock_client.get_markets.return_value = mock_response

        markets = exchange_with_mock.fetch_markets()

        assert len(markets) == 1
        assert markets[0].id == "1"
        assert markets[0].question == "Test Market"

    def test_fetch_market_not_found(self, exchange_with_mock, mock_client):
        """Test fetch_market when market not found."""
        mock_response = MagicMock()
        mock_response.errno = 404

        mock_client.get_market.return_value = mock_response

        with pytest.raises(MarketNotFound):
            exchange_with_mock.fetch_market("99999")

    def test_get_orderbook_success(self, exchange_with_mock, mock_client):
        """Test successful orderbook fetch."""
        mock_bid = MagicMock()
        mock_bid.price = 0.50
        mock_bid.size = 100

        mock_ask = MagicMock()
        mock_ask.price = 0.52
        mock_ask.size = 150

        mock_response = MagicMock()
        mock_response.errno = 0
        mock_response.result = MagicMock()
        mock_response.result.bids = [mock_bid]
        mock_response.result.asks = [mock_ask]

        mock_client.get_orderbook.return_value = mock_response

        orderbook = exchange_with_mock.get_orderbook("token_123")

        assert len(orderbook["bids"]) == 1
        assert len(orderbook["asks"]) == 1
        assert float(orderbook["bids"][0]["price"]) == 0.50
        assert float(orderbook["asks"][0]["price"]) == 0.52

    def test_cancel_order_success(self, exchange_with_mock, mock_client):
        """Test successful order cancellation."""
        mock_response = MagicMock()
        mock_response.errno = 0

        mock_client.cancel_order.return_value = mock_response

        order = exchange_with_mock.cancel_order("order_123")

        assert order.id == "order_123"
        assert order.status == OrderStatus.CANCELLED
        mock_client.cancel_order.assert_called_once_with("order_123")

    def test_fetch_balance_success(self, exchange_with_mock, mock_client):
        """Test successful balance fetch."""
        mock_item = MagicMock()
        mock_item.symbol = "USDC"
        mock_item.balance = 1000.0

        mock_response = MagicMock()
        mock_response.errno = 0
        mock_response.result = MagicMock()
        mock_response.result.list = [mock_item]

        mock_client.get_my_balances.return_value = mock_response

        balance = exchange_with_mock.fetch_balance()

        assert "USDC" in balance
        assert balance["USDC"] == 1000.0
