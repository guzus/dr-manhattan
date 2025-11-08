"""Base strategy classes for building trading bots"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
import time

from ..models import Market, Order
from ..base.exchange import Exchange
from ..utils import setup_logger

logger = setup_logger(__name__)


class BaseStrategy(ABC):
    """
    Base class for all trading strategies.
    Handles common setup, lifecycle, and state management.
    """

    def __init__(
        self,
        exchange: Exchange,
        max_exposure: float = 1000.0,
        check_interval: float = 2.0
    ):
        """
        Initialize strategy

        Args:
            exchange: Exchange instance to trade on
            max_exposure: Maximum capital exposure in USD
            check_interval: How often to check market in seconds
        """
        self.exchange = exchange
        self.max_exposure = max_exposure
        self.check_interval = check_interval
        self.target_market: Optional[Market] = None
        self.placed_orders = []
        self.is_running = False

    @abstractmethod
    def on_tick(self, market: Market) -> None:
        """
        Called every check_interval seconds with updated market data.
        Implement your strategy logic here.

        Args:
            market: Current market data
        """
        pass

    def on_start(self) -> None:
        """Called once when strategy starts. Override to add custom initialization."""
        pass

    def on_stop(self) -> None:
        """Called once when strategy stops. Override to add custom cleanup."""
        pass

    def run(
        self,
        market: Optional[Market] = None,
        duration_minutes: Optional[int] = None
    ):
        """
        Run the strategy

        Args:
            market: Market to trade on (if None, will auto-select)
            duration_minutes: How long to run (None = run forever)
        """
        logger.info(f"\n{'='*80}")
        logger.info(f"Starting {self.__class__.__name__}")
        logger.info(f"{'='*80}")
        logger.info(f"Max exposure: ${self.max_exposure:.2f}")
        logger.info(f"Check interval: {self.check_interval}s")
        if duration_minutes:
            logger.info(f"Duration: {duration_minutes} minutes")
        logger.info(f"{'='*80}\n")

        # Select market if not provided
        if market is None:
            logger.info("Finding suitable market...")
            market = self.exchange.find_tradeable_market(binary=True, limit=100)
            if not market:
                logger.error("No suitable market found. Exiting.")
                return

        self.target_market = market
        logger.info(f"Trading on: {market.question[:70]}...")
        logger.info(f"Market ID: {market.id[:16]}...\n")

        # Initialize account state
        logger.info("Initializing account state...")
        self.exchange.refresh_account_state(market_id=market.id)
        logger.info("Account state initialized\n")

        # Call user's on_start hook
        self.on_start()

        # Run strategy loop
        self.is_running = True
        start_time = time.time()
        end_time = start_time + (duration_minutes * 60) if duration_minutes else None
        iteration = 0

        try:
            while self.is_running:
                if end_time and time.time() >= end_time:
                    break

                iteration += 1
                logger.info(f"\n{'─'*80}")
                logger.info(f"Iteration #{iteration} - {time.strftime('%H:%M:%S')}")
                logger.info(f"{'─'*80}")

                # Call user's strategy logic
                try:
                    self.on_tick(self.target_market)
                except Exception as e:
                    logger.error(f"Error in strategy tick: {e}")

                # Wait for next iteration
                if end_time is None or time.time() < end_time:
                    time.sleep(self.check_interval)

        except KeyboardInterrupt:
            logger.info("\nStrategy interrupted by user")
        finally:
            self.is_running = False
            self.on_stop()
            logger.info(f"\n{'='*80}")
            logger.info("Strategy stopped")
            logger.info(f"Total iterations: {iteration}")
            logger.info(f"Total orders placed: {len(self.placed_orders)}")
            logger.info(f"{'='*80}\n")


class MarketMakingStrategy(BaseStrategy):
    """
    Base class for market making strategies.
    Provides helpers for common market making operations.
    """

    def get_account_state(self, market: Optional[Market] = None) -> Dict[str, Any]:
        """
        Get current account balance and positions

        Args:
            market: Optional market object for position fetching (some exchanges need market context)

        Returns:
            Dictionary with 'balance' and 'positions' keys
        """
        balance = self.exchange.get_balance()

        # Try to fetch positions with market context first (for Polymarket)
        if market and hasattr(self.exchange, 'fetch_positions_for_market'):
            positions = self.exchange.fetch_positions_for_market(market)
        else:
            positions = self.exchange.get_positions(
                market_id=self.target_market.id if self.target_market else None
            )

        logger.info(f"\n📊 Account State:")
        logger.info(f"  USDC Balance: ${balance.get('USDC', 0.0):,.2f}")

        if positions:
            logger.info(f"  Positions: {len(positions)} open")
            for pos in positions:
                logger.info(f"    {pos.outcome}: {pos.size} shares @ avg ${pos.average_price:.4f}")
        else:
            logger.info(f"  Positions: None")

        return {
            'balance': balance,
            'positions': positions
        }

    def calculate_order_size(
        self,
        market: Market,
        price: float,
        max_exposure: Optional[float] = None
    ) -> float:
        """
        Calculate appropriate order size based on liquidity and exposure limits

        Args:
            market: Market to trade on
            price: Price per share
            max_exposure: Maximum exposure (default: self.max_exposure)

        Returns:
            Order size in shares
        """
        if max_exposure is None:
            max_exposure = self.max_exposure

        # Base size on liquidity
        base_size = min(20.0, market.liquidity * 0.01) if market.liquidity > 0 else 5

        # Limit by exposure
        position_cost = base_size * price
        if position_cost > max_exposure:
            base_size *= max_exposure / position_cost

        return base_size
