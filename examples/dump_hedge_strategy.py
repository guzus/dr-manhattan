"""
Dump Hedge Strategy (2-leg)

Watches the first `window_min` minutes for a fast dump:
- Dump = best ask drops by at least `move_pct` within `dump_window_seconds`

Leg 1:
- Buy the dumped outcome at best ask (rounded to tick)

Leg 2:
- Buy the opposite outcome when:
  leg1_entry_price + opposite_best_ask <= sum_target
"""

import argparse
import os
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Optional, Tuple

from dotenv import load_dotenv

from dr_manhattan import Strategy
from dr_manhattan.base import Exchange, create_exchange
from dr_manhattan.models import Market
from dr_manhattan.models.order import OrderSide
from dr_manhattan.utils import prompt_market_selection, setup_logger
from dr_manhattan.utils.logger import Colors

logger = setup_logger(__name__)


@dataclass
class CycleState:
    in_cycle: bool = False
    leg1_outcome: Optional[str] = None
    leg1_entry_price: Optional[float] = None
    leg1_time: float = 0.0
    leg1_expected_qty: float = 0.0
    leg1_filled_qty: float = 0.0
    leg2_done: bool = False


class DumpHedgeStrategy(Strategy):
    """
    Two-leg dump-then-hedge strategy.
    """

    def __init__(
        self,
        exchange: Exchange,
        market_id: str,
        shares: float = 20.0,
        sum_target: float = 0.95,
        move_pct: float = 0.15,
        window_min: float = 2.0,
        dump_window_seconds: float = 3.0,
        max_position: float = 200.0,
        check_interval: float = 1.0,
    ):
        super().__init__(
            exchange=exchange,
            market_id=market_id,
            max_position=max_position,
            order_size=shares,
            max_delta=max_position * 2,
            check_interval=check_interval,
            track_fills=True,
        )

        self.shares = float(shares)
        self.sum_target = float(sum_target)
        self.move_pct = float(move_pct)
        self.window_min = float(window_min)
        self.dump_window_seconds = float(dump_window_seconds)

        self.round_start_ts: float = 0.0
        self.ask_history: Dict[str, Deque[Tuple[float, float]]] = {}
        self.cycle = CycleState()
        self.cycle_lock = threading.Lock()

    def on_start(self) -> None:
        # Validate binary market assumption
        if len(self.outcomes) != 2:
            logger.error(
                f"{Colors.red('ERROR:')} This strategy requires a binary market (2 outcomes). "
                f"Found {len(self.outcomes)} outcomes: {self.outcomes}"
            )
            raise ValueError(f"Binary market required, found {len(self.outcomes)} outcomes")

        self.round_start_ts = time.time()
        self.ask_history = {o: deque(maxlen=50) for o in self.outcomes}
        self.cycle = CycleState()

        # Register fill callback to track Leg 1 fills
        self.client.on_fill(self._handle_fill_event)

        logger.info(
            f"\n{Colors.bold('DumpHedge Strategy Config:')}\n"
            f"  Shares: {Colors.cyan(str(self.shares))}\n"
            f"  sumTarget: {Colors.yellow(str(self.sum_target))} | "
            f"movePct: {Colors.yellow(f'{self.move_pct * 100:.1f}%')} | "
            f"windowMin: {Colors.yellow(f'{self.window_min:.2f}')}\n"
            f"  dumpWindow: {Colors.gray(f'{self.dump_window_seconds:.2f}s')} | "
            f"interval: {Colors.gray(f'{self.check_interval:.2f}s')}\n"
        )

    def on_stop(self) -> None:
        logger.info(f"\n{Colors.bold('Shutting down...')}")
        try:
            self.cancel_all_orders()
        except Exception as e:
            logger.error(f"Error canceling orders during shutdown: {e}")

    def on_tick(self) -> None:
        self.refresh_state()

        now = time.time()
        in_watch_window = (now - self.round_start_ts) <= (self.window_min * 60.0)

        for outcome in self.outcomes:
            token_id = self.get_token_id(outcome)
            if not token_id:
                continue

            _bid, ask = self.get_best_bid_ask(token_id)
            if ask is None or ask <= 0 or ask > 1.0:
                continue

            self.ask_history[outcome].append((now, float(ask)))

        if self.cycle.in_cycle:
            self._maybe_execute_leg2()
            self._log_status(in_watch_window)
            return

        if not in_watch_window:
            self._log_status(in_watch_window)
            return

        dumped_outcome, entry_ask = self._detect_dump()
        if dumped_outcome is not None and entry_ask is not None:
            self._execute_leg1(dumped_outcome, entry_ask)

        self._log_status(in_watch_window)

    def _detect_dump(self) -> Tuple[Optional[str], Optional[float]]:
        now = time.time()

        for outcome in self.outcomes:
            hist = self.ask_history.get(outcome)
            if not hist or len(hist) < 2:
                continue

            while hist and (now - hist[0][0]) > self.dump_window_seconds:
                hist.popleft()

            if len(hist) < 2:
                continue

            _, oldest_ask = hist[0]
            _, newest_ask = hist[-1]
            if oldest_ask <= 0:
                continue

            pct_change = (newest_ask - oldest_ask) / oldest_ask
            if pct_change <= -self.move_pct:
                return outcome, newest_ask

        return None, None

    def _execute_leg1(self, outcome: str, current_ask: float) -> None:
        token_id = self.get_token_id(outcome)
        if not token_id:
            return

        entry_price = self.round_price(float(current_ask))

        logger.info(
            f"  {Colors.bold('LEG1')} {Colors.magenta(outcome)} "
            f"dump detected -> BUY {Colors.cyan(str(self.shares))} @ {Colors.yellow(f'{entry_price:.4f}')}"
        )

        if not self._place_order(outcome, OrderSide.BUY, entry_price, self.shares, token_id):
            return

        with self.cycle_lock:
            self.cycle = CycleState(
                in_cycle=True,
                leg1_outcome=outcome,
                leg1_entry_price=float(entry_price),
                leg1_time=time.time(),
                leg1_expected_qty=self.shares,
                leg1_filled_qty=0.0,
                leg2_done=False,
            )

    def _maybe_execute_leg2(self) -> None:
        # Check conditions with lock
        with self.cycle_lock:
            if not self.cycle.in_cycle or self.cycle.leg2_done:
                return
            if not self.cycle.leg1_outcome or self.cycle.leg1_entry_price is None:
                return

            # Only execute Leg 2 if Leg 1 order is fully filled
            if self.cycle.leg1_filled_qty < self.cycle.leg1_expected_qty:
                return

            leg1 = self.cycle.leg1_outcome
            leg1_entry = self.cycle.leg1_entry_price

        opp = self.outcomes[0] if self.outcomes[1] == leg1 else self.outcomes[1]

        opp_token = self.get_token_id(opp)
        if not opp_token:
            return

        _bid, opp_ask = self.get_best_bid_ask(opp_token)
        if opp_ask is None or opp_ask <= 0 or opp_ask > 1.0:
            return

        opp_ask = float(opp_ask)
        condition_value = float(leg1_entry) + opp_ask
        if condition_value > self.sum_target:
            return

        hedge_price = self.round_price(opp_ask)

        logger.info(
            f"  {Colors.bold('LEG2')} {Colors.magenta(opp)} "
            f"(leg1 {leg1_entry:.4f} + opp {opp_ask:.4f} = "
            f"{Colors.green(f'{condition_value:.4f}')} <= {self.sum_target}) "
            f"-> BUY {Colors.cyan(str(self.shares))} @ {Colors.yellow(f'{hedge_price:.4f}')}"
        )

        if not self._place_order(opp, OrderSide.BUY, hedge_price, self.shares, opp_token):
            return

        # Update cycle state with lock
        with self.cycle_lock:
            self.cycle.leg2_done = True
            self.cycle.in_cycle = False
            self.cycle.leg1_outcome = None
            self.cycle.leg1_entry_price = None

        for o in self.outcomes:
            self.ask_history[o].clear()

    def _handle_fill_event(self, event, order, fill_size: float) -> None:
        """Track fills for Leg 1 orders (thread-safe)"""
        if order.market_id != self.market_id:
            return

        with self.cycle_lock:
            if not self.cycle.in_cycle or self.cycle.leg2_done:
                return
            if order.outcome != self.cycle.leg1_outcome:
                return
            if order.side != OrderSide.BUY:
                return

            fill_qty = float(fill_size)
            if fill_qty > 0:
                self.cycle.leg1_filled_qty += fill_qty
                filled = self.cycle.leg1_filled_qty
                expected = self.cycle.leg1_expected_qty

        if fill_qty > 0:
            logger.info(
                f"  {Colors.green('LEG1 FILL:')} {fill_qty:.2f} shares "
                f"(total: {filled:.2f}/{expected:.2f})"
            )

    def _place_order(
        self,
        outcome: str,
        side: OrderSide,
        price: float,
        shares: float,
        token_id: str,
    ) -> bool:
        try:
            self.create_order(outcome, side, price, shares, token_id)
            return True
        except Exception as e:
            logger.error(f"  Order failed: {e}")
            return False

    def _log_status(self, in_watch_window: bool) -> None:
        window_left = max(0.0, (self.window_min * 60.0) - (time.time() - self.round_start_ts))
        cycle_state = (
            f"cycle=LEG2_WAIT({self.cycle.leg1_outcome})" if self.cycle.in_cycle else "cycle=IDLE"
        )

        cash_str = f"{self.cash:.2f}" if isinstance(self.cash, (int, float)) else "N/A"

        logger.info(
            f"{Colors.gray('window_left')}: {Colors.gray(f'{window_left:5.1f}s')} | "
            f"{Colors.gray('watch')}: {Colors.gray('ON' if in_watch_window else 'OFF')} | "
            f"{Colors.gray(cycle_state)} | "
            f"cash={Colors.cyan(cash_str)}"
        )


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
            except Exception as e:
                logger.debug(f"Error fetching markets page {page}: {e}")
                break

        markets = [m for m in all_markets if all(k in m.question.lower() for k in keyword_parts)]

    if not markets:
        logger.error(f"No markets found for: {slug}")
        return None

    if market_index is not None:
        if market_index < 0 or market_index >= len(markets):
            logger.error(f"Index {market_index} out of range (0-{len(markets) - 1})")
            return None
        return markets[market_index].id

    if len(markets) == 1:
        return markets[0].id

    return prompt_market_selection(markets)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dump Hedge Strategy (2-leg)")
    parser.add_argument(
        "-e", "--exchange", default=os.getenv("EXCHANGE", "polymarket"), help="Exchange name"
    )
    parser.add_argument("-s", "--slug", default=os.getenv("MARKET_SLUG", ""), help="Market slug")
    parser.add_argument("-m", "--market-id", default=os.getenv("MARKET_ID", ""), help="Market ID")
    parser.add_argument("--market", type=int, default=None, dest="market_index", help="Market index")

    parser.add_argument("--shares", type=float, default=20.0, help="Shares per leg")
    parser.add_argument("--sum-target", type=float, default=0.95, help="Leg1 + OppAsk threshold")
    parser.add_argument("--move-pct", type=float, default=0.15, help="Dump threshold as fraction")
    parser.add_argument("--window-min", type=float, default=2.0, help="Watch window in minutes")
    parser.add_argument("--dump-window", type=float, default=3.0, help="Dump lookback seconds")
    parser.add_argument("--max-position", type=float, default=200.0, help="Max position per outcome")
    parser.add_argument(
        "--interval",
        type=float,
        default=float(os.getenv("CHECK_INTERVAL", "1")),
        help="Tick interval seconds",
    )
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

    market_id = args.market_id
    if not market_id and args.slug:
        market_id = find_market_id(exchange, args.slug, args.market_index)
        if not market_id:
            return 1

    strategy = DumpHedgeStrategy(
        exchange=exchange,
        market_id=market_id,
        shares=args.shares,
        sum_target=args.sum_target,
        move_pct=args.move_pct,
        window_min=args.window_min,
        dump_window_seconds=args.dump_window,
        max_position=args.max_position,
        check_interval=args.interval,
    )

    try:
        strategy.run(duration_minutes=args.duration)
    except KeyboardInterrupt:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())