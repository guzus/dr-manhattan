"""
Step Jump Capture Strategy (ACCUMULATE -> DISTRIBUTE (SELL ALL))

Concept:
- Accumulate when price is cheap (absolute band).
- Detect a step-up jump.
- On jump, immediately sell all inventory.

Modes:
- --test (default): logs simulated orders, does not place real orders
- --live: places real orders
"""

import argparse
import os
import sys
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


class Phase:
    ACCUMULATE = "ACCUMULATE"
    DISTRIBUTE = "DISTRIBUTE"
    COOLDOWN = "COOLDOWN"


@dataclass
class StepState:
    phase: str = Phase.ACCUMULATE
    target_outcome: Optional[str] = None
    inventory_shares: float = 0.0
    vwap_entry: Optional[float] = None
    round_start_ts: float = 0.0
    last_buy_ts: float = 0.0
    last_sell_ts: float = 0.0
    phase_start_ts: float = 0.0


class StepJumpCaptureStrategy(Strategy):
    def __init__(
        self,
        exchange: Exchange,
        market_id: str,
        target_outcome: Optional[str] = None,
        shares: float = 20.0,
        max_inventory: float = 200.0,
        buy_band_low: float = 0.35,
        buy_band_high: float = 0.45,
        buy_cooldown_seconds: float = 10.0,
        jump_window_seconds: float = 30.0,
        jump_pct: float = 0.20,
        sell_cooldown_seconds: float = 1.0,
        time_stop_seconds: float = 3600.0,
        distribute_timeout_seconds: float = 120.0,
        check_interval: float = 1.0,
        test_mode: bool = True,
    ):
        super().__init__(
            exchange=exchange,
            market_id=market_id,
            max_position=max_inventory,
            order_size=shares,
            max_delta=max_inventory * 2,
            check_interval=check_interval,
            track_fills=True,
        )

        self.shares = float(shares)
        self.max_inventory = float(max_inventory)

        self.buy_band_low = float(buy_band_low)
        self.buy_band_high = float(buy_band_high)
        self.buy_cooldown_seconds = float(buy_cooldown_seconds)

        self.jump_window_seconds = float(jump_window_seconds)
        self.jump_pct = float(jump_pct)

        self.sell_cooldown_seconds = float(sell_cooldown_seconds)

        self.time_stop_seconds = float(time_stop_seconds)
        self.distribute_timeout_seconds = float(distribute_timeout_seconds)

        self.test_mode = bool(test_mode)

        self.ask_history: Dict[str, Deque[Tuple[float, float]]] = {}
        self.state = StepState()
        self._forced_target_outcome = target_outcome

    def on_start(self) -> None:
        now = time.time()
        self.state = StepState(
            phase=Phase.ACCUMULATE,
            target_outcome=self._select_target_outcome(),
            inventory_shares=0.0,
            vwap_entry=None,
            round_start_ts=now,
            last_buy_ts=0.0,
            last_sell_ts=0.0,
            phase_start_ts=now,
        )
        self.ask_history = {o: deque(maxlen=300) for o in self.outcomes}

        mode = "TEST" if self.test_mode else "LIVE"
        logger.info(
            f"\n{Colors.bold('StepJumpCapture Strategy Config:')}\n"
            f"  Mode: {Colors.yellow(mode)}\n"
            f"  TargetOutcome: {Colors.magenta(str(self.state.target_outcome))}\n"
            f"  Shares(per buy): {Colors.cyan(str(self.shares))} | MaxInventory: {Colors.cyan(str(self.max_inventory))}\n"
            f"  BuyBand: [{Colors.yellow(f'{self.buy_band_low:.2f}')}, {Colors.yellow(f'{self.buy_band_high:.2f}')}] "
            f"| buyCooldown: {Colors.gray(f'{self.buy_cooldown_seconds:.0f}s')}\n"
            f"  Jump: window={Colors.gray(f'{self.jump_window_seconds:.0f}s')} "
            f"pct={Colors.yellow(f'{self.jump_pct*100:.1f}%')}\n"
            f"  SellCooldown: {Colors.gray(f'{self.sell_cooldown_seconds:.0f}s')}\n"
            f"  timeStop: {Colors.gray(f'{self.time_stop_seconds:.0f}s')} | distributeTimeout: {Colors.gray(f'{self.distribute_timeout_seconds:.0f}s')}\n"
            f"  interval: {Colors.gray(f'{self.check_interval:.2f}s')}\n"
        )

    def on_stop(self) -> None:
        logger.info(f"\n{Colors.bold('Shutting down...')}")
        if not self.test_mode:
            try:
                self.cancel_all_orders()
            except Exception:
                pass

    def on_tick(self) -> None:
        self.refresh_state()

        now = time.time()

        if (now - self.state.round_start_ts) >= self.time_stop_seconds:
            self._log_status(extra=f"TIME_STOP reached ({self.time_stop_seconds:.0f}s)")
            return

        for outcome in self.outcomes:
            token_id = self.get_token_id(outcome)
            if not token_id:
                continue
            _bid, ask = self.get_best_bid_ask(token_id)
            if ask is None or ask <= 0 or ask > 1.0:
                continue
            self.ask_history[outcome].append((now, float(ask)))

        if not self.state.target_outcome:
            self.state.target_outcome = self._select_target_outcome()
            if not self.state.target_outcome:
                self._log_status(extra="No target outcome available")
                return

        if self.state.phase == Phase.ACCUMULATE:
            self._accumulate_phase()

            if self._detect_jump(self.state.target_outcome):
                self.state.phase = Phase.DISTRIBUTE
                self.state.phase_start_ts = time.time()
                self._log_status(extra="JUMP detected -> switch to DISTRIBUTE (SELL ALL)")

        elif self.state.phase == Phase.DISTRIBUTE:
            self._sell_all_now()

            if (now - self.state.phase_start_ts) >= self.distribute_timeout_seconds:
                self.state.phase = Phase.COOLDOWN
                self.state.phase_start_ts = now
                self._log_status(extra="DISTRIBUTE timeout -> COOLDOWN")

        elif self.state.phase == Phase.COOLDOWN:
            self._log_status(extra="COOLDOWN (idle)")
            return

        self._log_status()

    def _accumulate_phase(self) -> None:
        now = time.time()
        if (now - self.state.last_buy_ts) < self.buy_cooldown_seconds:
            return

        if self.state.inventory_shares + self.shares > self.max_inventory:
            return

        outcome = self.state.target_outcome
        token_id = self.get_token_id(outcome)
        if not token_id:
            return

        _bid, ask = self.get_best_bid_ask(token_id)
        if ask is None or ask <= 0 or ask > 1.0:
            return

        ask = float(ask)
        if not (self.buy_band_low <= ask <= self.buy_band_high):
            return

        price = self.round_price(ask)

        logger.info(
            f"  {Colors.bold('ACCUM')} {Colors.magenta(outcome)} "
            f"band hit -> BUY {Colors.cyan(str(self.shares))} @ {Colors.yellow(f'{price:.4f}')}"
        )

        if not self._place_order(outcome, OrderSide.BUY, price, self.shares, token_id):
            return

        self._update_vwap_on_buy(price, self.shares)
        self.state.inventory_shares += self.shares
        self.state.last_buy_ts = now

    def _sell_all_now(self) -> None:
        now = time.time()
        if self.state.inventory_shares <= 0:
            self.state.phase = Phase.COOLDOWN
            self.state.phase_start_ts = now
            return

        if (now - self.state.last_sell_ts) < self.sell_cooldown_seconds:
            return

        outcome = self.state.target_outcome
        token_id = self.get_token_id(outcome)
        if not token_id:
            return

        bid, ask = self.get_best_bid_ask(token_id)
        if bid is None or bid <= 0 or bid > 1.0:
            return

        bid = float(bid)
        sell_price = self.round_price(bid)
        sell_qty = float(self.state.inventory_shares)

        logger.info(
            f"  {Colors.bold('SELLALL')} {Colors.magenta(outcome)} "
            f"-> SELL {Colors.cyan(f'{sell_qty:.2f}')} @ {Colors.yellow(f'{sell_price:.4f}')} (best_bid={bid:.4f})"
        )

        if not self._place_order(outcome, OrderSide.SELL, sell_price, sell_qty, token_id):
            return

        self.state.inventory_shares = 0.0
        self.state.last_sell_ts = now
        self.state.phase = Phase.COOLDOWN
        self.state.phase_start_ts = now

    def _detect_jump(self, outcome: str) -> bool:
        now = time.time()
        hist = self.ask_history.get(outcome)
        if not hist or len(hist) < 2:
            return False

        while hist and (now - hist[0][0]) > self.jump_window_seconds:
            hist.popleft()

        if len(hist) < 2:
            return False

        min_ask = min(p for _, p in hist)
        cur_ask = hist[-1][1]
        if min_ask <= 0:
            return False

        jump = (cur_ask - min_ask) / min_ask
        return jump >= self.jump_pct

    def _select_target_outcome(self) -> Optional[str]:
        if self._forced_target_outcome:
            if self._forced_target_outcome in self.outcomes:
                return self._forced_target_outcome
            for o in self.outcomes:
                if o.lower() == self._forced_target_outcome.lower():
                    return o

        best: Tuple[Optional[str], float] = (None, 999.0)
        for o in self.outcomes:
            token_id = self.get_token_id(o)
            if not token_id:
                continue
            _bid, ask = self.get_best_bid_ask(token_id)
            if ask is None or ask <= 0 or ask > 1.0:
                continue
            a = float(ask)
            if a < best[1]:
                best = (o, a)
        return best[0]

    def _update_vwap_on_buy(self, price: float, qty: float) -> None:
        if qty <= 0:
            return
        if self.state.vwap_entry is None or self.state.inventory_shares <= 0:
            self.state.vwap_entry = float(price)
            return

        inv = float(self.state.inventory_shares)
        vwap = float(self.state.vwap_entry)
        new_vwap = (vwap * inv + float(price) * float(qty)) / (inv + float(qty))
        self.state.vwap_entry = new_vwap

    def _place_order(
        self,
        outcome: str,
        side: OrderSide,
        price: float,
        shares: float,
        token_id: str,
    ) -> bool:
        if self.test_mode:
            logger.info(
                f"  {Colors.gray('[TEST ORDER]')} {side.name} {Colors.magenta(outcome)} "
                f"{Colors.cyan(str(shares))} @ {Colors.yellow(f'{price:.4f}')}"
            )
            return True

        try:
            self.create_order(outcome, side, price, shares, token_id)
            return True
        except Exception as e:
            logger.error(f"  Order failed: {e}")
            return False

    def _log_status(self, extra: str = "") -> None:
        mode = "TEST" if self.test_mode else "LIVE"
        cash_str = f"{self.cash:.2f}" if isinstance(self.cash, (int, float)) else "N/A"

        outcome = self.state.target_outcome
        inv = self.state.inventory_shares
        vwap = self.state.vwap_entry

        msg = (
            f"  {Colors.gray('mode')}: {Colors.gray(mode)} | "
            f"{Colors.gray('phase')}: {Colors.gray(self.state.phase)} | "
            f"{Colors.gray('outcome')}: {Colors.magenta(str(outcome))} | "
            f"{Colors.gray('inv')}: {Colors.cyan(f'{inv:.2f}')} | "
            f"{Colors.gray('vwap')}: {Colors.cyan(f'{vwap:.4f}' if vwap is not None else 'N/A')} | "
            f"cash={Colors.cyan(cash_str)}"
        )
        if extra:
            msg += f" | {Colors.yellow(extra)}"
        logger.info(msg)


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

    if market_index is not None:
        if market_index < 0 or market_index >= len(markets):
            logger.error(f"Index {market_index} out of range (0-{len(markets) - 1})")
            return None
        return markets[market_index].id

    if len(markets) == 1:
        return markets[0].id

    return prompt_market_selection(markets)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Step Jump Capture Strategy (SELL ALL on jump)")
    parser.add_argument(
        "-e", "--exchange", default=os.getenv("EXCHANGE", "polymarket"), help="Exchange name"
    )
    parser.add_argument("-s", "--slug", default=os.getenv("MARKET_SLUG", ""), help="Market slug")
    parser.add_argument("-m", "--market-id", default=os.getenv("MARKET_ID", ""), help="Market ID")
    parser.add_argument("--market", type=int, default=None, dest="market_index", help="Market index")

    parser.add_argument("--outcome", type=str, default=None, help="Target outcome to trade (optional)")

    parser.add_argument("--shares", type=float, default=20.0, help="Shares per buy")
    parser.add_argument("--max-inventory", type=float, default=200.0, help="Max inventory to hold")

    parser.add_argument("--buy-band-low", type=float, default=0.35, help="Buy band low (absolute)")
    parser.add_argument("--buy-band-high", type=float, default=0.45, help="Buy band high (absolute)")
    parser.add_argument("--buy-cooldown", type=float, default=10.0, help="Seconds between buys")

    parser.add_argument("--jump-window", type=float, default=30.0, help="Jump lookback seconds")
    parser.add_argument("--jump-pct", type=float, default=0.20, help="Jump threshold as fraction")

    parser.add_argument("--sell-cooldown", type=float, default=1.0, help="Seconds between sell attempts")

    parser.add_argument("--time-stop", type=float, default=3600.0, help="Stop logic after N seconds")
    parser.add_argument("--distribute-timeout", type=float, default=120.0, help="Max time in DISTRIBUTE")

    parser.add_argument(
        "--interval",
        type=float,
        default=float(os.getenv("CHECK_INTERVAL", "1")),
        help="Tick interval seconds",
    )
    parser.add_argument("--duration", type=int, default=None, help="Duration in minutes")

    parser.add_argument("--test", action="store_true", help="Test mode (default)")
    parser.add_argument("--live", action="store_true", help="Live mode (places real orders)")
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

    test_mode = True
    if args.live:
        test_mode = False

    strategy = StepJumpCaptureStrategy(
        exchange=exchange,
        market_id=market_id,
        target_outcome=args.outcome,
        shares=args.shares,
        max_inventory=args.max_inventory,
        buy_band_low=args.buy_band_low,
        buy_band_high=args.buy_band_high,
        buy_cooldown_seconds=args.buy_cooldown,
        jump_window_seconds=args.jump_window,
        jump_pct=args.jump_pct,
        sell_cooldown_seconds=args.sell_cooldown,
        time_stop_seconds=args.time_stop,
        distribute_timeout_seconds=args.distribute_timeout,
        check_interval=args.interval,
        test_mode=test_mode,
    )

    try:
        strategy.run(duration_minutes=args.duration)
    except KeyboardInterrupt:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())