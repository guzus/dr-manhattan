"""Tests for data models"""

import pytest
from datetime import datetime
from dr_manhattan.models.market import Market
from dr_manhattan.models.order import Order, OrderSide, OrderStatus
from dr_manhattan.models.position import Position


class TestMarket:
    """Tests for Market model"""

    def test_market_creation(self):
        """Test creating a market"""
        market = Market(
            id="market_123",
            question="Will it rain tomorrow?",
            outcomes=["Yes", "No"],
            close_time=datetime(2025, 12, 31, 23, 59, 59),
            volume=10000.0,
            liquidity=5000.0,
            prices={"Yes": 0.6, "No": 0.4},
            metadata={"category": "weather"}
        )

        assert market.id == "market_123"
        assert market.question == "Will it rain tomorrow?"
        assert market.outcomes == ["Yes", "No"]
        assert market.volume == 10000.0
        assert market.liquidity == 5000.0
        assert market.prices == {"Yes": 0.6, "No": 0.4}
        assert market.metadata == {"category": "weather"}

    def test_market_is_binary(self):
        """Test is_binary property"""
        binary_market = Market(
            id="m1",
            question="Yes or No?",
            outcomes=["Yes", "No"],
            close_time=None,
            volume=0,
            liquidity=0,
            prices={},
            metadata={}
        )
        assert binary_market.is_binary is True

        multi_outcome_market = Market(
            id="m2",
            question="Who will win?",
            outcomes=["A", "B", "C"],
            close_time=None,
            volume=0,
            liquidity=0,
            prices={},
            metadata={}
        )
        assert multi_outcome_market.is_binary is False

    def test_market_is_open(self):
        """Test is_open property"""
        future_market = Market(
            id="m1",
            question="Future?",
            outcomes=["Yes", "No"],
            close_time=datetime(2099, 12, 31),
            volume=0,
            liquidity=0,
            prices={},
            metadata={}
        )
        assert future_market.is_open is True

        past_market = Market(
            id="m2",
            question="Past?",
            outcomes=["Yes", "No"],
            close_time=datetime(2020, 1, 1),
            volume=0,
            liquidity=0,
            prices={},
            metadata={}
        )
        assert past_market.is_open is False

        no_close_time_market = Market(
            id="m3",
            question="No close time?",
            outcomes=["Yes", "No"],
            close_time=None,
            volume=0,
            liquidity=0,
            prices={},
            metadata={}
        )
        assert no_close_time_market.is_open is True

    def test_market_spread(self):
        """Test spread property"""
        # Binary market with perfect prices (sum to 1.0)
        market = Market(
            id="m1",
            question="Test?",
            outcomes=["Yes", "No"],
            close_time=None,
            volume=0,
            liquidity=0,
            prices={"Yes": 0.6, "No": 0.4},
            metadata={}
        )
        assert market.spread is not None
        assert abs(market.spread) < 0.01  # Should be very close to 0

        # Binary market with spread
        market_with_spread = Market(
            id="m2",
            question="Binary?",
            outcomes=["Yes", "No"],
            close_time=None,
            volume=0,
            liquidity=0,
            prices={"Yes": 0.55, "No": 0.40},
            metadata={}
        )
        spread = market_with_spread.spread
        assert spread is not None
        assert abs(spread - 0.05) < 0.01  # Spread of 0.05

        # Non-binary market
        multi_market = Market(
            id="m3",
            question="Multi?",
            outcomes=["A", "B", "C"],
            close_time=None,
            volume=0,
            liquidity=0,
            prices={"A": 0.33, "B": 0.33, "C": 0.33},
            metadata={}
        )
        assert multi_market.spread is None


class TestOrder:
    """Tests for Order model"""

    def test_order_creation(self):
        """Test creating an order"""
        order = Order(
            id="order_123",
            market_id="market_123",
            outcome="Yes",
            side=OrderSide.BUY,
            price=0.65,
            size=100,
            filled=50,
            status=OrderStatus.PARTIALLY_FILLED,
            created_at=datetime(2025, 1, 1, 0, 0, 0),
            updated_at=datetime(2025, 1, 1, 0, 1, 0)
        )

        assert order.id == "order_123"
        assert order.market_id == "market_123"
        assert order.outcome == "Yes"
        assert order.side == OrderSide.BUY
        assert order.price == 0.65
        assert order.size == 100
        assert order.filled == 50
        assert order.status == OrderStatus.PARTIALLY_FILLED

    def test_order_remaining(self):
        """Test remaining property"""
        order = Order(
            id="o1",
            market_id="m1",
            outcome="Yes",
            side=OrderSide.BUY,
            price=0.65,
            size=100,
            filled=30,
            status=OrderStatus.PARTIALLY_FILLED,
            created_at=None,
            updated_at=None
        )
        assert order.remaining == 70

    def test_order_is_open(self):
        """Test is_open property"""
        open_order = Order(
            id="o1",
            market_id="m1",
            outcome="Yes",
            side=OrderSide.BUY,
            price=0.65,
            size=100,
            filled=0,
            status=OrderStatus.OPEN,
            created_at=None,
            updated_at=None
        )
        assert open_order.is_open is True

        filled_order = Order(
            id="o2",
            market_id="m1",
            outcome="Yes",
            side=OrderSide.BUY,
            price=0.65,
            size=100,
            filled=100,
            status=OrderStatus.FILLED,
            created_at=None,
            updated_at=None
        )
        assert filled_order.is_open is False

        cancelled_order = Order(
            id="o3",
            market_id="m1",
            outcome="Yes",
            side=OrderSide.BUY,
            price=0.65,
            size=100,
            filled=0,
            status=OrderStatus.CANCELLED,
            created_at=None,
            updated_at=None
        )
        assert cancelled_order.is_open is False

    def test_order_is_filled(self):
        """Test is_filled property"""
        filled_order = Order(
            id="o1",
            market_id="m1",
            outcome="Yes",
            side=OrderSide.BUY,
            price=0.65,
            size=100,
            filled=100,
            status=OrderStatus.FILLED,
            created_at=None,
            updated_at=None
        )
        assert filled_order.is_filled is True

        partial_order = Order(
            id="o2",
            market_id="m1",
            outcome="Yes",
            side=OrderSide.BUY,
            price=0.65,
            size=100,
            filled=50,
            status=OrderStatus.PARTIALLY_FILLED,
            created_at=None,
            updated_at=None
        )
        assert partial_order.is_filled is False

    def test_order_fill_percentage(self):
        """Test fill_percentage property"""
        order = Order(
            id="o1",
            market_id="m1",
            outcome="Yes",
            side=OrderSide.BUY,
            price=0.65,
            size=100,
            filled=75,
            status=OrderStatus.PARTIALLY_FILLED,
            created_at=None,
            updated_at=None
        )
        assert order.fill_percentage == 0.75


class TestPosition:
    """Tests for Position model"""

    def test_position_creation(self):
        """Test creating a position"""
        position = Position(
            market_id="market_123",
            outcome="Yes",
            size=100,
            average_price=0.60,
            current_price=0.65
        )

        assert position.market_id == "market_123"
        assert position.outcome == "Yes"
        assert position.size == 100
        assert position.average_price == 0.60
        assert position.current_price == 0.65

    def test_position_unrealized_pnl(self):
        """Test unrealized PnL calculation"""
        position = Position(
            market_id="m1",
            outcome="Yes",
            size=100,
            average_price=0.60,
            current_price=0.65
        )
        # (0.65 - 0.60) * 100 = 5.0
        assert position.unrealized_pnl == 5.0

    def test_position_unrealized_pnl_percent(self):
        """Test unrealized PnL percentage calculation"""
        position = Position(
            market_id="m1",
            outcome="Yes",
            size=100,
            average_price=0.60,
            current_price=0.65
        )
        # ((0.65 - 0.60) / 0.60) * 100 = 8.333...
        assert abs(position.unrealized_pnl_percent - 8.333) < 0.01

    def test_position_cost_basis(self):
        """Test cost basis calculation"""
        position = Position(
            market_id="m1",
            outcome="Yes",
            size=100,
            average_price=0.60,
            current_price=0.65
        )
        # 0.60 * 100 = 60.0
        assert position.cost_basis == 60.0

    def test_position_current_value(self):
        """Test current value calculation"""
        position = Position(
            market_id="m1",
            outcome="Yes",
            size=100,
            average_price=0.60,
            current_price=0.65
        )
        # 0.65 * 100 = 65.0
        assert position.current_value == 65.0

    def test_position_negative_pnl(self):
        """Test position with negative PnL"""
        position = Position(
            market_id="m1",
            outcome="Yes",
            size=100,
            average_price=0.70,
            current_price=0.60
        )
        # (0.60 - 0.70) * 100 = -10.0
        assert position.unrealized_pnl == -10.0
        # ((0.60 - 0.70) / 0.70) * 100 ≈ -14.29
        assert abs(position.unrealized_pnl_percent - (-14.285)) < 0.01


class TestOrderEnums:
    """Tests for Order enums"""

    def test_order_side_enum(self):
        """Test OrderSide enum"""
        assert OrderSide.BUY.value == "buy"
        assert OrderSide.SELL.value == "sell"

    def test_order_status_enum(self):
        """Test OrderStatus enum"""
        assert OrderStatus.PENDING.value == "pending"
        assert OrderStatus.OPEN.value == "open"
        assert OrderStatus.FILLED.value == "filled"
        assert OrderStatus.PARTIALLY_FILLED.value == "partially_filled"
        assert OrderStatus.CANCELLED.value == "cancelled"
        assert OrderStatus.REJECTED.value == "rejected"
