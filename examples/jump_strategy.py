"""
Defensive Step Jump Capture Strategy (ACCUMULATE -> HOLD -> EXITING -> COOLDOWN -> ACCUMULATE)

Goals (defensive):
- Never spam orders when balance/allowance is insufficient.
- Sync inventory from actual positions every tick (avoid state drift).
- Take-profit only when:
    (1) Step-up jump is detected, AND
    (2) Profit condition is satisfied (bid >= vwap*(1+tp_pct) OR min_profit_abs).
- Always stop-loss if price dumps too much (bid <= vwap*(1-sl_pct)) or "drop" detected.
- Backoff / cooldown when repeated order failures happen.
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
    HOLD = "HOLD"
    EXITING = "EXITING"
    COOLDOWN = "COOLDOWN"


@dataclass
class State:
    phase: str = Phase.ACCUMULATE
    target_outcome: Optional[str] = None

    inventory_shares: float = 0.0
    vwap_entry: Optional[float] = None  # best-effort estimate (see notes)
    round_start_ts: float = 0.0

    last_buy_ts: float = 0.0
    last_sell_ts: float = 0.0
    phase_start_ts: float = 0.0

    # defensive bookkeeping
    consecutive_order_failures: int = 0
    last_failure_ts: float = 0.0
    last_tp_ts: float = 0.0
    last_sl_ts: float = 0.0


class DefensiveJumpCaptureStrategy(Strategy):
    def __init__(
        self,
        exchange: Exchange,
        market_id: str,
        target_outcome: Optional[str] = None,
        shares: float = 5.0,
        max_inventory: float = 50.0,

        # Entry conditions
        buy_band_low: float = 0.30,
        buy_band_high: float = 0.50,
        buy_cooldown_seconds: float = 10.0,
        min_cash_buffer: float = 1.0,  # keep some cash unspent

        # Jump/Drop detectors (use rolling window)
        window_seconds: float = 30.0,
        jump_up_pct: float = 0.15,   # e.g. +15% from min ask in window
        drop_down_pct: float = 0.15, # e.g. -15% from max bid in window

        # Exit (take profit / stop loss)
        take_profit_pct: float = 0.03,     # require bid >= vwap*(1+tp)
        stop_loss_pct: float = 0.06,       # force exit if bid <= vwap*(1-sl)
        min_profit_abs: float = 0.0,       # optional absolute profit floor in USDC (best-effort)
        max_hold_seconds: float = 3600.0,  # time-stop for any position

        # Order pacing
        sell_cooldown_seconds: float = 2.0,
        check_interval: float = 1.0,

        # Failure handling
        max_consecutive_failures: int = 5,
        failure_cooldown_seconds: float = 60.0,

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
        self.min_cash_buffer = float(min_cash_buffer)

        self.window_seconds = float(window_seconds)
        self.jump_up_pct = float(jump_up_pct)
        self.drop_down_pct = float(drop_down_pct)

        self.take_profit_pct = float(take_profit_pct)
        self.stop_loss_pct = float(stop_loss_pct)
        self.min_profit_abs = float(min_profit_abs)
        self.max_hold_seconds = float(max_hold_seconds)

        self.sell_cooldown_seconds = float(sell_cooldown_seconds)

        self.max_consecutive_failures = int(max_consecutive_failures)
        self.failure_cooldown_seconds = float(failure_cooldown_seconds)

        self.state = State()
        self._forced_target_outcome = target_outcome

        # histories per outcome
        self.ask_hist: Dict[str, Deque[Tuple[float, float]]] = {}
        self.bid_hist: Dict[str, Deque[Tuple[float, float]]] = {}

        # if we entered HOLD, remember when
        self._pos_open_ts: Optional[float] = None

    # ---------- lifecycle ----------
    def on_start(self) -> None:
        self.refresh_state()
        now = time.time()

        self.state = State(
            phase=Phase.ACCUMULATE,
            target_outcome=self._select_target_outcome(),
            inventory_shares=0.0,
            vwap_entry=None,
            round_start_ts=now,
            last_buy_ts=0.0,
            last_sell_ts=0.0,
            phase_start_ts=now,
            consecutive_order_failures=0,
            last_failure_ts=0.0,
            last_tp_ts=0.0,
            last_sl_ts=0.0,
        )

        self.ask_hist = {o: deque(maxlen=600) for o in self.outcomes}
        self.bid_hist = {o: deque(maxlen=600) for o in self.outcomes}

        self._sync_inventory_from_positions()
        if self.state.inventory_shares > 0:
            self.state.phase = Phase.HOLD
            self._pos_open_ts = now

        logger.info(
            f"\n{Colors.bold('DefensiveJumpCapture Config:')}\n"
            f"  TargetOutcome: {Colors.magenta(str(self.state.target_outcome))}\n"
            f"  shares={Colors.cyan(str(self.shares))} maxInv={Colors.cyan(str(self.max_inventory))}\n"
            f"  BuyBand=[{Colors.yellow(f'{self.buy_band_low:.2f}')}, {Colors.yellow(f'{self.buy_band_high:.2f}')}] "
            f"buyCooldown={Colors.gray(f'{self.buy_cooldown_seconds:.0f}s')} cashBuffer={Colors.gray(f'{self.min_cash_buffer:.2f}')}\n"
            f"  Window={Colors.gray(f'{self.window_seconds:.0f}s')} jumpUp={Colors.yellow(f'{self.jump_up_pct*100:.1f}%')} "
            f"dropDown={Colors.yellow(f'{self.drop_down_pct*100:.1f}%')}\n"
            f"  TP={Colors.yellow(f'{self.take_profit_pct*100:.1f}%')} SL={Colors.yellow(f'{self.stop_loss_pct*100:.1f}%')} "
            f"maxHold={Colors.gray(f'{self.max_hold_seconds:.0f}s')}\n"
            f"  Failure: maxConsecutive={Colors.gray(str(self.max_consecutive_failures))} "
            f"cooldown={Colors.gray(f'{self.failure_cooldown_seconds:.0f}s')}\n"
            f"  interval={Colors.gray(f'{self.check_interval:.2f}s')}\n"
        )

    def on_stop(self) -> None:
        logger.info(f"\n{Colors.bold('Shutting down...')}")
        try:
            self.cancel_all_orders()
        except Exception:
            pass

    # ---------- main loop ----------
    def on_tick(self) -> None:
        self.refresh_state()
        now = time.time()

        # failure cooldown gate (important when you got 403/cloudflare or allowance issues)
        if self._in_failure_cooldown(now):
            self._log_status(extra=f"FAIL_COOLDOWN ({self.failure_cooldown_seconds:.0f}s)")
            return

        # keep histories updated
        self._update_histories(now)

        # ensure target
        if not self.state.target_outcome:
            self.state.target_outcome = self._select_target_outcome()
            if not self.state.target_outcome:
                self._log_status(extra="No target outcome available")
                return

        # always sync real inventory
        self._sync_inventory_from_positions()

        # phase routing
        if self.state.phase == Phase.ACCUMULATE:
            if self.state.inventory_shares > 0:
                self._enter_hold(now, reason="Found existing inventory -> HOLD")
            else:
                self._accumulate(now)

        elif self.state.phase == Phase.HOLD:
            # time stop
            if self._pos_open_ts and (now - self._pos_open_ts) >= self.max_hold_seconds:
                self._enter_exiting(now, reason="MAX_HOLD reached -> EXITING")
            else:
                self._maybe_exit(now)

        elif self.state.phase == Phase.EXITING:
            self._sell_all(now)

        elif self.state.phase == Phase.COOLDOWN:
            # simple cooldown after exits or failure storms
            if (now - self.state.phase_start_ts) >= 5.0:
                self._enter_accumulate(now, reason="COOLDOWN done -> ACCUMULATE")

        self._log_status()

    # ---------- phase actions ----------
    def _accumulate(self, now: float) -> None:
        # buy cooldown
        if (now - self.state.last_buy_ts) < self.buy_cooldown_seconds:
            return

        # cap
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

        # entry band
        if not (self.buy_band_low <= ask <= self.buy_band_high):
            return

        price = self.round_price(ask)

        # balance/allowance sanity: don't even try if cash too low
        est_cost = price * self.shares
        if not self._has_sufficient_cash(est_cost):
            self._log_status(extra=f"SKIP BUY (cash too low for cost≈{est_cost:.2f})")
            return

        logger.info(
            f"  {Colors.bold('ACCUM')} {Colors.magenta(outcome)} "
            f"band hit -> BUY {Colors.cyan(str(self.shares))} @ {Colors.yellow(f'{price:.4f}')}"
        )

        ok = self._place_order(outcome, OrderSide.BUY, price, self.shares, token_id)
        if not ok:
            return

        # best-effort vwap tracking (not perfect if partial fills happen)
        self._update_vwap_on_buy(price, self.shares)
        self.state.last_buy_ts = now

        # after buy attempt, re-sync next tick via positions
        # but if you want immediate transition:
        self._enter_hold(now, reason="BUY placed -> HOLD")

    def _maybe_exit(self, now: float) -> None:
        outcome = self.state.target_outcome
        token_id = self.get_token_id(outcome)
        if not token_id:
            return

        bid, ask = self.get_best_bid_ask(token_id)
        if bid is None or bid <= 0 or bid > 1.0:
            return

        bid = float(bid)
        ask = float(ask) if ask is not None else None

        vwap = self._get_effective_vwap()
        if vwap is None or vwap <= 0:
            # if we can't estimate entry, be conservative: only stop-loss on large drops
            if self._detect_drop(outcome):
                self._enter_exiting(now, reason="DROP detected (no vwap) -> EXITING")
            return

        # stop loss first (defensive)
        if bid <= vwap * (1.0 - self.stop_loss_pct):
            self.state.last_sl_ts = now
            self._enter_exiting(now, reason=f"STOP_LOSS hit (bid {bid:.4f} <= vwap {vwap:.4f})")
            return

        # drop detector as extra stop trigger
        if self._detect_drop(outcome):
            self.state.last_sl_ts = now
            self._enter_exiting(now, reason="DROP detected -> EXITING")
            return

        # take profit condition: require jump up + profit condition
        jumped = self._detect_jump(outcome)
        if not jumped:
            return

        profit_ok = bid >= vwap * (1.0 + self.take_profit_pct)

        # optional absolute profit gate (best-effort)
        if self.min_profit_abs > 0 and profit_ok:
            # approx pnl = (bid - vwap) * shares
            approx_pnl = (bid - vwap) * float(self.state.inventory_shares)
            profit_ok = approx_pnl >= self.min_profit_abs

        if profit_ok:
            self.state.last_tp_ts = now
            self._enter_exiting(now, reason=f"JUMP+TP -> EXITING (bid {bid:.4f} vs vwap {vwap:.4f})")

    def _sell_all(self, now: float) -> None:
        # sell cooldown
        if (now - self.state.last_sell_ts) < self.sell_cooldown_seconds:
            return

        self._sync_inventory_from_positions()
        if self.state.inventory_shares <= 0:
            self._enter_cooldown(now, reason="No inventory -> COOLDOWN")
            return

        outcome = self.state.target_outcome
        token_id = self.get_token_id(outcome)
        if not token_id:
            return

        bid, _ask = self.get_best_bid_ask(token_id)
        if bid is None or bid <= 0 or bid > 1.0:
            return

        sell_price = self.round_price(float(bid))
        sell_qty = float(self.state.inventory_shares)

        logger.info(
            f"  {Colors.bold('SELLALL')} {Colors.magenta(outcome)} "
            f"-> SELL {Colors.cyan(f'{sell_qty:.2f}')} @ {Colors.yellow(f'{sell_price:.4f}')} (best_bid={bid:.4f})"
        )

        ok = self._place_order(outcome, OrderSide.SELL, sell_price, sell_qty, token_id)
        if not ok:
            # keep EXITING and retry later; failure handler will backoff if repeated
            return

        self.state.last_sell_ts = now
        # inventory will be synced from positions; until then keep cautious
        self._enter_cooldown(now, reason="SELL placed -> COOLDOWN")

    # ---------- helpers ----------
    def _update_histories(self, now: float) -> None:
        for outcome in self.outcomes:
            token_id = self.get_token_id(outcome)
            if not token_id:
                continue
            bid, ask = self.get_best_bid_ask(token_id)
            if ask is not None and 0 < ask <= 1.0:
                self.ask_hist[outcome].append((now, float(ask)))
            if bid is not None and 0 < bid <= 1.0:
                self.bid_hist[outcome].append((now, float(bid)))

        # prune by window_seconds
        for outcome in self.outcomes:
            h = self.ask_hist.get(outcome)
            while h and (now - h[0][0]) > self.window_seconds:
                h.popleft()
            h2 = self.bid_hist.get(outcome)
            while h2 and (now - h2[0][0]) > self.window_seconds:
                h2.popleft()

    def _detect_jump(self, outcome: str) -> bool:
        h = self.ask_hist.get(outcome)
        if not h or len(h) < 2:
            return False
        min_ask = min(p for _, p in h)
        cur_ask = h[-1][1]
        if min_ask <= 0:
            return False
        jump = (cur_ask - min_ask) / min_ask
        return jump >= self.jump_up_pct

    def _detect_drop(self, outcome: str) -> bool:
        h = self.bid_hist.get(outcome)
        if not h or len(h) < 2:
            return False
        max_bid = max(p for _, p in h)
        cur_bid = h[-1][1]
        if max_bid <= 0:
            return False
        drop = (max_bid - cur_bid) / max_bid
        return drop >= self.drop_down_pct

    def _select_target_outcome(self) -> Optional[str]:
        if self._forced_target_outcome:
            if self._forced_target_outcome in self.outcomes:
                return self._forced_target_outcome
            for o in self.outcomes:
                if o.lower() == self._forced_target_outcome.lower():
                    return o

        # choose cheapest ask now
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

    def _sync_inventory_from_positions(self) -> None:
        if not self.state.target_outcome:
            return
        actual = float(self.positions.get(self.state.target_outcome, 0.0))
        self.state.inventory_shares = actual
        if actual <= 0:
            self.state.vwap_entry = None
            self._pos_open_ts = None

    def _get_effective_vwap(self) -> Optional[float]:
        # best-effort: use tracked vwap_entry
        # If your framework exposes avg entry price somewhere, you can plug it here.
        return self.state.vwap_entry

    def _update_vwap_on_buy(self, price: float, qty: float) -> None:
        if qty <= 0:
            return
        inv = float(self.state.inventory_shares)
        # note: inv here is BEFORE sync; best-effort only
        if self.state.vwap_entry is None or inv <= 0:
            self.state.vwap_entry = float(price)
            return
        vwap = float(self.state.vwap_entry)
        self.state.vwap_entry = (vwap * inv + float(price) * float(qty)) / (inv + float(qty))

    def _has_sufficient_cash(self, est_cost: float) -> bool:
        # if cash isn't numeric or missing, just allow (some exchanges hide it)
        if not isinstance(self.cash, (int, float)):
            return True
        return float(self.cash) >= (float(est_cost) + self.min_cash_buffer)

    def _in_failure_cooldown(self, now: float) -> bool:
        if self.state.consecutive_order_failures < self.max_consecutive_failures:
            return False
        return (now - self.state.last_failure_ts) < self.failure_cooldown_seconds

    def _place_order(self, outcome: str, side: OrderSide, price: float, shares: float, token_id: str) -> bool:
        try:
            self.create_order(outcome, side, price, shares, token_id)
            self.state.consecutive_order_failures = 0
            return True
        except Exception as e:
            self.state.consecutive_order_failures += 1
            self.state.last_failure_ts = time.time()
            logger.error(f"  Order failed: {e}")
            # if failures pile up -> switch to COOLDOWN to avoid spam
            if self.state.consecutive_order_failures >= self.max_consecutive_failures:
                self._enter_cooldown(self.state.last_failure_ts, reason="Too many failures -> COOLDOWN")
            return False

    # ---------- phase transitions ----------
    def _enter_hold(self, now: float, reason: str = "") -> None:
        if self.state.phase != Phase.HOLD:
            self.state.phase = Phase.HOLD
            self.state.phase_start_ts = now
            if self._pos_open_ts is None:
                self._pos_open_ts = now
            if reason:
                logger.info(f"  {Colors.green('PHASE')} HOLD | {Colors.gray(reason)}")

    def _enter_exiting(self, now: float, reason: str = "") -> None:
        if self.state.phase != Phase.EXITING:
            self.state.phase = Phase.EXITING
            self.state.phase_start_ts = now
            if reason:
                logger.info(f"  {Colors.green('PHASE')} EXITING | {Colors.gray(reason)}")

    def _enter_accumulate(self, now: float, reason: str = "") -> None:
        if self.state.phase != Phase.ACCUMULATE:
            self.state.phase = Phase.ACCUMULATE
            self.state.phase_start_ts = now
            if reason:
                logger.info(f"  {Colors.green('PHASE')} ACCUMULATE | {Colors.gray(reason)}")

    def _enter_cooldown(self, now: float, reason: str = "") -> None:
        if self.state.phase != Phase.COOLDOWN:
            self.state.phase = Phase.COOLDOWN
            self.state.phase_start_ts = now
            if reason:
                logger.info(f"  {Colors.green('PHASE')} COOLDOWN | {Colors.gray(reason)}")

    # ---------- logging ----------
    def _log_status(self, extra: str = "") -> None:
        cash_str = f"{self.cash:.2f}" if isinstance(self.cash, (int, float)) else "N/A"
        outcome = self.state.target_outcome
        inv = self.state.inventory_shares
        vwap = self.state.vwap_entry
        msg = (
            f"{Colors.gray('phase')}: {Colors.gray(self.state.phase)} | "
            f"{Colors.gray('outcome')}: {Colors.magenta(str(outcome))} | "
            f"{Colors.gray('inv')}: {Colors.cyan(f'{inv:.2f}')} | "
            f"{Colors.gray('vwap')}: {Colors.cyan(f'{vwap:.4f}' if vwap is not None else 'N/A')} | "
            f"cash={Colors.cyan(cash_str)} | "
            f"fails={Colors.gray(str(self.state.consecutive_order_failures))}"
        )
        if extra:
            msg += f" | {Colors.yellow(extra)}"
        logger.info(msg)


def find_market_id(exchange: Exchange, slug: str, market_index: Optional[int] = None) -> Optional[str]:
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
        if 0 <= market_index < len(markets):
            return markets[market_index].id
        logger.error(f"Index {market_index} out of range (0-{len(markets)-1})")
        return None

    if len(markets) == 1:
        return markets[0].id

    return prompt_market_selection(markets)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Defensive Jump Capture Strategy")
    p.add_argument("-e", "--exchange", default=os.getenv("EXCHANGE", "polymarket"))
    p.add_argument("-s", "--slug", default=os.getenv("MARKET_SLUG", ""))
    p.add_argument("-m", "--market-id", default=os.getenv("MARKET_ID", ""))
    p.add_argument("--market", type=int, default=None, dest="market_index")

    p.add_argument("--outcome", type=str, default=None)
    p.add_argument("--shares", type=float, default=5.0)
    p.add_argument("--max-inventory", type=float, default=50.0)

    p.add_argument("--buy-band-low", type=float, default=0.30)
    p.add_argument("--buy-band-high", type=float, default=0.50)
    p.add_argument("--buy-cooldown", type=float, default=10.0)
    p.add_argument("--cash-buffer", type=float, default=1.0)

    p.add_argument("--window", type=float, default=30.0)
    p.add_argument("--jump-up", type=float, default=0.15)
    p.add_argument("--drop-down", type=float, default=0.15)

    p.add_argument("--tp", type=float, default=0.03)
    p.add_argument("--sl", type=float, default=0.06)
    p.add_argument("--min-profit-abs", type=float, default=0.0)
    p.add_argument("--max-hold", type=float, default=3600.0)

    p.add_argument("--sell-cooldown", type=float, default=2.0)
    p.add_argument("--interval", type=float, default=float(os.getenv("CHECK_INTERVAL", "1")))

    p.add_argument("--max-fails", type=int, default=5)
    p.add_argument("--fail-cooldown", type=float, default=60.0)

    return p.parse_args()


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

    market_id = args.market_id
    if not market_id and args.slug:
        market_id = find_market_id(exchange, args.slug, args.market_index)
        if not market_id:
            return 1

    strat = DefensiveJumpCaptureStrategy(
        exchange=exchange,
        market_id=market_id,
        target_outcome=args.outcome,
        shares=args.shares,
        max_inventory=args.max_inventory,
        buy_band_low=args.buy_band_low,
        buy_band_high=args.buy_band_high,
        buy_cooldown_seconds=args.buy_cooldown,
        min_cash_buffer=args.cash_buffer,
        window_seconds=args.window,
        jump_up_pct=args.jump_up,
        drop_down_pct=args.drop_down,
        take_profit_pct=args.tp,
        stop_loss_pct=args.sl,
        min_profit_abs=args.min_profit_abs,
        max_hold_seconds=args.max_hold,
        sell_cooldown_seconds=args.sell_cooldown,
        check_interval=args.interval,
        max_consecutive_failures=args.max_fails,
        failure_cooldown_seconds=args.fail_cooldown,
    )
    strat.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
