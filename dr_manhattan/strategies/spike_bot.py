"""
Spike Bot Strategy

A momentum trading strategy that exploits short-term price spikes on Polymarket.

The bot:
1. Monitors price movements every second
2. Detects sharp price spikes (1-4% movement in short timeframes)
3. Takes small positions to capture mean reversion
4. Implements tight profit targets (2-4%) and stop losses

Based on the concept from https://x.com/gusik4ever/status/2003103062546657636
"""

import time
from collections import deque
from typing import Dict, List, Optional

from ..base.strategy import Strategy
from ..models.order import OrderSide
from ..utils import setup_logger
from ..utils.logger import Colors

logger = setup_logger(__name__)


class SpikeBot(Strategy):
    """
    Spike detection and trading bot for Polymarket.

    Monitors price movements and trades on sharp spikes with tight exits.
    """

    def __init__(
        self,
        exchange,
        market_id: str,
        spike_threshold: float = 0.015,
        profit_target: float = 0.03,
        stop_loss: float = 0.02,
        position_size: float = 5.0,
        max_position: float = 20.0,
        history_size: int = 60,
        check_interval: float = 1.0,
    ):
        """
        Initialize Spike Bot.

        Args:
            exchange: Exchange instance (Polymarket)
            market_id: Market ID to trade
            spike_threshold: Minimum price change to trigger (e.g., 0.015 = 1.5%)
            profit_target: Target profit percentage (e.g., 0.03 = 3%)
            stop_loss: Maximum loss before exit (e.g., 0.02 = 2%)
            position_size: Size of each trade
            max_position: Maximum position size per outcome
            history_size: Number of price points to store (at 1s interval)
            check_interval: Seconds between checks (1s recommended)
        """
        super().__init__(
            exchange=exchange,
            market_id=market_id,
            max_position=max_position,
            order_size=position_size,
            max_delta=max_position * 2,
            check_interval=check_interval,
            track_fills=True,
        )

        self.spike_threshold = spike_threshold
        self.profit_target = profit_target
        self.stop_loss = stop_loss
        self.history_size = history_size

        self.price_history: Dict[str, deque] = {}
        self.entry_prices: Dict[str, float] = {}
        self.spike_detected: Dict[str, bool] = {}

    def setup(self) -> bool:
        """Initialize strategy and price history tracking"""
        if not super().setup():
            return False

        for outcome in self.outcomes:
            self.price_history[outcome] = deque(maxlen=self.history_size)
            self.entry_prices[outcome] = 0.0
            self.spike_detected[outcome] = False

        logger.info(
            f"\n{Colors.bold('Spike Bot Configuration:')}\n"
            f"  Spike Threshold: {Colors.yellow(f'{self.spike_threshold*100:.1f}%')}\n"
            f"  Profit Target: {Colors.green(f'{self.profit_target*100:.1f}%')}\n"
            f"  Stop Loss: {Colors.red(f'{self.stop_loss*100:.1f}%')}\n"
            f"  Position Size: {Colors.cyan(f'${self.order_size:.0f}')}\n"
            f"  Max Position: {Colors.cyan(f'${self.max_position:.0f}')}\n"
            f"  History Window: {Colors.gray(f'{self.history_size}s')}"
        )

        return True

    def on_tick(self):
        """Main trading logic called every tick"""
        self.refresh_state()
        self.update_price_history()

        for outcome in self.outcomes:
            token_id = self.get_token_id(outcome)
            if not token_id:
                continue

            current_price = self.get_current_price(outcome)
            if current_price is None or current_price <= 0:
                continue

            position = self._positions.get(outcome, 0)

            if position > 0:
                self.manage_position(outcome, current_price, position)
            else:
                self.detect_and_trade_spike(outcome, current_price, token_id)

        if self._positions:
            self.log_spike_status()

    def update_price_history(self):
        """Update price history for all outcomes"""
        for outcome in self.outcomes:
            price = self.get_current_price(outcome)
            if price and price > 0:
                self.price_history[outcome].append(price)

    def get_current_price(self, outcome: str) -> Optional[float]:
        """Get current mid price for an outcome"""
        token_id = self.get_token_id(outcome)
        if not token_id:
            return None

        best_bid, best_ask = self.get_best_bid_ask(token_id)

        if best_bid is None or best_ask is None or best_bid <= 0 or best_ask <= 0:
            return self.market.prices.get(outcome)

        mid_price = (best_bid + best_ask) / 2.0
        return mid_price

    def detect_spike(self, outcome: str, current_price: float) -> Optional[str]:
        """
        Detect price spikes.

        Returns:
            'up' if upward spike detected
            'down' if downward spike detected
            None if no spike
        """
        history = self.price_history[outcome]

        if len(history) < 10:
            return None

        recent_prices = list(history)[-10:]
        avg_price = sum(recent_prices) / len(recent_prices)

        price_change = (current_price - avg_price) / avg_price

        if abs(price_change) >= self.spike_threshold:
            if price_change > 0:
                return "up"
            else:
                return "down"

        return None

    def detect_and_trade_spike(self, outcome: str, current_price: float, token_id: str):
        """Detect spikes and enter trades"""
        spike_direction = self.detect_spike(outcome, current_price)

        if spike_direction is None:
            return

        if self.spike_detected.get(outcome, False):
            return

        best_bid, best_ask = self.get_best_bid_ask(token_id)
        if best_bid is None or best_ask is None:
            return

        if spike_direction == "up":
            side = OrderSide.SELL
            entry_price = self.round_price(best_bid)
            logger.info(
                f"  {Colors.red('↑ SPIKE UP')} detected on {Colors.magenta(outcome)}: "
                f"{Colors.yellow(f'{current_price:.4f}')} - "
                f"Selling into spike at {Colors.yellow(f'{entry_price:.4f}')}"
            )
        else:
            side = OrderSide.BUY
            entry_price = self.round_price(best_ask)
            logger.info(
                f"  {Colors.green('↓ SPIKE DOWN')} detected on {Colors.magenta(outcome)}: "
                f"{Colors.yellow(f'{current_price:.4f}')} - "
                f"Buying the dip at {Colors.yellow(f'{entry_price:.4f}')}"
            )

        if side == OrderSide.BUY and self.cash < self.order_size:
            logger.warning(f"  Insufficient cash: ${self.cash:.2f} < ${self.order_size:.2f}")
            return

        try:
            self.create_order(outcome, side, entry_price, self.order_size, token_id)
            self.entry_prices[outcome] = entry_price
            self.spike_detected[outcome] = True
            self.log_order(side, self.order_size, outcome, entry_price, "SPIKE")
        except Exception as e:
            logger.error(f"  Failed to enter spike trade: {e}")

    def manage_position(self, outcome: str, current_price: float, position: float):
        """Manage existing positions with profit target and stop loss"""
        entry_price = self.entry_prices.get(outcome, 0)
        if entry_price <= 0:
            return

        token_id = self.get_token_id(outcome)
        if not token_id:
            return

        pnl_pct = (current_price - entry_price) / entry_price

        should_exit = False
        exit_reason = ""

        if pnl_pct >= self.profit_target:
            should_exit = True
            exit_reason = f"PROFIT TARGET ({pnl_pct*100:.1f}%)"
        elif pnl_pct <= -self.stop_loss:
            should_exit = True
            exit_reason = f"STOP LOSS ({pnl_pct*100:.1f}%)"

        if should_exit:
            best_bid, best_ask = self.get_best_bid_ask(token_id)
            if best_bid is None or best_bid <= 0:
                return

            exit_price = self.round_price(best_bid)
            exit_size = float(int(position))

            if exit_size > 0:
                try:
                    self.create_order(outcome, OrderSide.SELL, exit_price, exit_size, token_id)
                    logger.info(
                        f"  {Colors.gray('EXIT')} {Colors.magenta(outcome)} @ "
                        f"{Colors.yellow(f'{exit_price:.4f}')} - {exit_reason}"
                    )

                    self.entry_prices[outcome] = 0.0
                    self.spike_detected[outcome] = False
                except Exception as e:
                    logger.error(f"  Failed to exit position: {e}")

    def log_spike_status(self):
        """Log current spike trading status"""
        status_parts = []
        for outcome in self.outcomes:
            position = self._positions.get(outcome, 0)
            if position > 0:
                entry_price = self.entry_prices.get(outcome, 0)
                current_price = self.get_current_price(outcome)
                if entry_price > 0 and current_price:
                    pnl_pct = (current_price - entry_price) / entry_price
                    pnl_color = Colors.green if pnl_pct >= 0 else Colors.red
                    status_parts.append(
                        f"{Colors.magenta(outcome[:8])}: {pnl_color(f'{pnl_pct*100:+.1f}%')}"
                    )

        if status_parts:
            logger.info(f"  Positions: {' | '.join(status_parts)}")

    def cleanup(self):
        """Exit all positions before shutdown"""
        logger.info(f"\n{Colors.bold('Spike Bot shutting down...')}")

        self.cancel_all_orders()

        for outcome in self.outcomes:
            position = self._positions.get(outcome, 0)
            if position > 0:
                token_id = self.get_token_id(outcome)
                if token_id:
                    best_bid, _ = self.get_best_bid_ask(token_id)
                    if best_bid and best_bid > 0:
                        exit_size = float(int(position))
                        if exit_size > 0:
                            try:
                                self.create_order(
                                    outcome, OrderSide.SELL, best_bid, exit_size, token_id
                                )
                                logger.info(
                                    f"  Liquidating {Colors.magenta(outcome)}: "
                                    f"{exit_size:.0f} @ {Colors.yellow(f'{best_bid:.4f}')}"
                                )
                            except Exception as e:
                                logger.error(f"  Failed to liquidate {outcome}: {e}")

        time.sleep(3)

        self.client.stop()
        logger.info("Spike Bot stopped")
