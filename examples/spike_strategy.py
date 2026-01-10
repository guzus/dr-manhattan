"""
Spike Strategy - Mean Reversion for Polymarket

Detects price spikes and buys the dip expecting bounce back.
BUY-only: YES dip -> BUY YES, NO dip -> BUY NO.
"""

import argparse
import os
import sys
import time
from collections import deque
from dataclasses import dataclass
from typing import Dict, List, Optional

from dotenv import load_dotenv

from dr_manhattan import Strategy
from dr_manhattan.base import Exchange, create_exchange
from dr_manhattan.models import Market
from dr_manhattan.models.order import OrderSide
from dr_manhattan.utils import prompt_market_selection, setup_logger
from dr_manhattan.utils.logger import Colors

logger = setup_logger(__name__)


@dataclass
class Position:
    """Tracks a position with entry details"""

    entry_price: float
    size: float
    entry_time: float


class SpikeStrategy(Strategy):
    """
    Spike detection strategy - buys dips expecting mean reversion.

    Since YES + NO = 1.0, buying NO on dip is like shorting YES.
    This naturally covers both directions with BUY-only logic.
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
        ema_period: int = 30,
        cooldown_seconds: float = 30.0,
        check_interval: float = 1.0,
    ):
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
        self.ema_period = ema_period
        self.cooldown_seconds = cooldown_seconds

        self.ema_prices: Dict[str, float] = {}
        self.ema_alpha = 2.0 / (ema_period + 1)
        self.price_history: Dict[str, deque] = {}
        self.entries: Dict[str, Position] = {}
        self.last_exit_time: Dict[str, float] = {}

    def setup(self) -> bool:
        if not super().setup():
            return False

        for outcome in self.outcomes:
            self.ema_prices[outcome] = 0.0
            self.price_history[outcome] = deque(maxlen=60)
            self.last_exit_time[outcome] = 0.0

        logger.info(
            f"\n{Colors.bold('Spike Strategy Config:')}\n"
            f"  Threshold: {Colors.yellow(f'{self.spike_threshold * 100:.1f}%')} | "
            f"TP: {Colors.green(f'{self.profit_target * 100:.1f}%')} | "
            f"SL: {Colors.red(f'{self.stop_loss * 100:.1f}%')}\n"
            f"  Size: {Colors.cyan(f'${self.order_size:.0f}')} | "
            f"EMA: {Colors.gray(f'{self.ema_period}s')} | "
            f"Cooldown: {Colors.gray(f'{self.cooldown_seconds}s')}"
        )
        return True

    def on_tick(self):
        self.refresh_state()

        for outcome in self.outcomes:
            token_id = self.get_token_id(outcome)
            if not token_id:
                continue

            price = self._get_mid_price(outcome, token_id)
            if price is None or price <= 0:
                continue

            self._update_ema(outcome, price)
            self.price_history[outcome].append(price)

            pos = self._positions.get(outcome, 0)

            if outcome in self.entries:
                self._manage_position(outcome, price, pos, token_id)
            else:
                self._check_spike_and_buy(outcome, price, token_id)

        self._log_status()

    def _get_mid_price(self, outcome: str, token_id: Optional[str] = None) -> Optional[float]:
        if token_id is None:
            token_id = self.get_token_id(outcome)
            if not token_id:
                return None

        bid, ask = self.get_best_bid_ask(token_id)
        if bid is None or ask is None or bid <= 0 or ask <= 0:
            return self.market.prices.get(outcome)

        return (bid + ask) / 2.0

    def _update_ema(self, outcome: str, price: float):
        if self.ema_prices[outcome] == 0.0:
            self.ema_prices[outcome] = price
        else:
            self.ema_prices[outcome] = price * self.ema_alpha + self.ema_prices[outcome] * (
                1 - self.ema_alpha
            )

    def _is_in_cooldown(self, outcome: str) -> bool:
        return (time.time() - self.last_exit_time.get(outcome, 0.0)) < self.cooldown_seconds

    def _detect_spike_down(self, outcome: str, price: float) -> bool:
        ema = self.ema_prices.get(outcome, 0.0)
        if ema <= 0 or len(self.price_history[outcome]) < self.ema_period:
            return False
        return (price - ema) / ema <= -self.spike_threshold

    def _check_spike_and_buy(self, outcome: str, price: float, token_id: str):
        if self._is_in_cooldown(outcome):
            return

        if not self._detect_spike_down(outcome, price):
            return

        if self.cash < self.order_size:
            return

        _, ask = self.get_best_bid_ask(token_id)
        # Binary market prices are 0-1 (probability)
        if ask is None or ask <= 0 or ask > 1.0:
            return

        entry_price = self.round_price(ask)

        logger.info(
            f"  {Colors.green('SPIKE')} {Colors.magenta(outcome)}: "
            f"{Colors.yellow(f'{price:.4f}')} < EMA {Colors.gray(f'{self.ema_prices[outcome]:.4f}')} "
            f"-> BUY @ {Colors.yellow(f'{entry_price:.4f}')}"
        )

        try:
            self.create_order(outcome, OrderSide.BUY, entry_price, self.order_size, token_id)
            self.entries[outcome] = Position(entry_price, self.order_size, time.time())
        except Exception as e:
            logger.error(f"  Buy failed: {e}")

    def _manage_position(self, outcome: str, price: float, exchange_pos: float, token_id: str):
        pos = self.entries.get(outcome)
        if not pos:
            return

        # Positions < 1 are dust (below minimum order size)
        if exchange_pos < 1:
            del self.entries[outcome]
            return

        if pos.entry_price <= 0:
            del self.entries[outcome]
            return

        pnl = (price - pos.entry_price) / pos.entry_price

        if pnl >= self.profit_target:
            reason = f"TP +{pnl * 100:.1f}%"
        elif pnl <= -self.stop_loss:
            reason = f"SL {pnl * 100:.1f}%"
        else:
            return

        bid, _ = self.get_best_bid_ask(token_id)
        if bid is None or bid <= 0:
            return

        exit_price = self.round_price(bid)
        exit_size = min(exchange_pos, pos.size)

        try:
            self.create_order(outcome, OrderSide.SELL, exit_price, exit_size, token_id)
            color = Colors.green if pnl >= 0 else Colors.red
            logger.info(
                f"  {Colors.bold('EXIT')} {Colors.magenta(outcome)} @ "
                f"{Colors.yellow(f'{exit_price:.4f}')} - {color(reason)}"
            )
            del self.entries[outcome]
            self.last_exit_time[outcome] = time.time()
        except Exception as e:
            logger.error(f"  Exit failed: {e}")

    def _log_status(self):
        if not self.entries:
            return

        parts = []
        for outcome, pos in self.entries.items():
            price = self._get_mid_price(outcome)
            if price:
                pnl = (price - pos.entry_price) / pos.entry_price
                color = Colors.green if pnl >= 0 else Colors.red
                parts.append(f"{Colors.magenta(outcome[:8])}: {color(f'{pnl * 100:+.1f}%')}")

        if parts:
            logger.info(f"  Positions: {' | '.join(parts)}")

    def cleanup(self):
        logger.info(f"\n{Colors.bold('Shutting down...')}")
        self.cancel_all_orders()

        for outcome, pos in list(self.entries.items()):
            token_id = self.get_token_id(outcome)
            if not token_id:
                continue

            exchange_pos = self._positions.get(outcome, 0)
            if exchange_pos < 1:
                continue

            bid, _ = self.get_best_bid_ask(token_id)
            if not bid or bid <= 0:
                continue

            try:
                self.create_order(
                    outcome,
                    OrderSide.SELL,
                    self.round_price(bid),
                    min(exchange_pos, pos.size),
                    token_id,
                )
            except Exception as e:
                logger.debug(f"Cleanup sell failed for {outcome}: {e}")

        time.sleep(3)
        self.client.stop()


def find_market_id(
    exchange: Exchange, slug: str, market_index: Optional[int] = None
) -> Optional[str]:
    logger.info(f"Searching for market: {slug}")

    markets: List[Market] = []

    if hasattr(exchange, "fetch_markets_by_slug"):
        markets = exchange.fetch_markets_by_slug(slug)

    if not markets:
        keywords = slug.replace("-", " ").lower()
        keyword_parts = [k for k in keywords.split() if len(k) > 2]

        all_markets: List[Market] = []
        for page in range(1, 6):
            try:
                page_markets = exchange.fetch_markets({"page": page, "limit": 20})
                if not page_markets:
                    break
                all_markets.extend(page_markets)
            except Exception:
                break

        markets = [m for m in all_markets if all(k in m.question.lower() for k in keyword_parts)]

    if not markets:
        logger.error(f"No markets found for: {slug}")
        return None

    if len(markets) == 1:
        logger.info(f"Found: {markets[0].question}")
        return markets[0].id

    if market_index is not None:
        if 0 <= market_index < len(markets):
            logger.info(f"Selected [{market_index}]: {markets[market_index].question}")
            return markets[market_index].id
        else:
            logger.error(f"Index {market_index} out of range (0-{len(markets) - 1})")
            return None

    return prompt_market_selection(markets)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Spike Strategy - Mean Reversion")
    parser.add_argument(
        "-e", "--exchange", default=os.getenv("EXCHANGE", "polymarket"), help="Exchange name"
    )
    parser.add_argument("-s", "--slug", default=os.getenv("MARKET_SLUG", ""), help="Market slug")
    parser.add_argument("-m", "--market-id", default=os.getenv("MARKET_ID", ""), help="Market ID")
    parser.add_argument(
        "--market", type=int, default=None, dest="market_index", help="Market index"
    )
    parser.add_argument(
        "--spike-threshold", type=float, default=0.015, help="Spike threshold (default: 1.5%%)"
    )
    parser.add_argument(
        "--profit-target", type=float, default=0.03, help="Profit target (default: 3%%)"
    )
    parser.add_argument("--stop-loss", type=float, default=0.02, help="Stop loss (default: 2%%)")
    parser.add_argument(
        "--position-size", type=float, default=5.0, help="Position size (default: $5)"
    )
    parser.add_argument(
        "--max-position", type=float, default=20.0, help="Max position (default: $20)"
    )
    parser.add_argument("--ema-period", type=int, default=30, help="EMA period (default: 30s)")
    parser.add_argument("--cooldown", type=float, default=30.0, help="Cooldown (default: 30s)")
    parser.add_argument("--duration", type=int, default=None, help="Duration in minutes")
    return parser.parse_args()


def main() -> int:
    load_dotenv()
    args = parse_args()

    if not args.market_id and not args.slug:
        logger.error("Provide --market-id or --slug")
        return 1

    try:
        exchange = create_exchange(args.exchange)
    except ValueError as e:
        logger.error(str(e))
        return 1

    logger.info(f"\n{Colors.bold('Exchange:')} {Colors.cyan(args.exchange.upper())}")

    market_id: Optional[str] = args.market_id
    if not market_id and args.slug:
        market_id = find_market_id(exchange, args.slug, args.market_index)
        if not market_id:
            return 1

    strategy = SpikeStrategy(
        exchange=exchange,
        market_id=market_id,
        spike_threshold=args.spike_threshold,
        profit_target=args.profit_target,
        stop_loss=args.stop_loss,
        position_size=args.position_size,
        max_position=args.max_position,
        ema_period=args.ema_period,
        cooldown_seconds=args.cooldown,
    )

    try:
        strategy.run(duration_minutes=args.duration)
    except KeyboardInterrupt:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
