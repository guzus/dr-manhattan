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
    vwap_entry: Optional[float] = None  # Updated ONLY on confirmed fills
    round_start_ts: float = 0.0

    last_buy_ts: float = 0.0
    last_sell_ts: float = 0.0
    phase_start_ts: float = 0.0

    consecutive_order_failures: int = 0
    last_failure_ts: float = 0.0
    last_tp_ts: float = 0.0
    last_sl_ts: float = 0.0


class DefensiveCapitalPreservationStrategy(Strategy):
    def __init__(
        self,
        exchange: Exchange,
        market_id: str,
        target_outcome: Optional[str] = None,
        shares: float = 5.0,
        max_inventory: float = 50.0,
        buy_band_low: float = 0.30,
        buy_band_high: float = 0.50,
        buy_cooldown_seconds: float = 10.0,
        min_cash_buffer: float = 1.0,
        take_profit_pct: float = 0.007,
        stop_loss_pct: float = 0.035,
        min_profit_abs: float = 0.0,
        max_hold_seconds: float = 3600.0,
        sell_cooldown_seconds: float = 2.0,
        check_interval: float = 1.0,
        max_consecutive_failures: int = 5,
        failure_cooldown_seconds: float = 60.0,
        post_exit_cooldown_seconds: float = 5.0,
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

        self.take_profit_pct = float(take_profit_pct)
        self.stop_loss_pct = float(stop_loss_pct)
        self.min_profit_abs = float(min_profit_abs)
        self.max_hold_seconds = float(max_hold_seconds)

        self.sell_cooldown_seconds = float(sell_cooldown_seconds)

        self.max_consecutive_failures = int(max_consecutive_failures)
        self.failure_cooldown_seconds = float(failure_cooldown_seconds)
        self.post_exit_cooldown_seconds = float(post_exit_cooldown_seconds)

        self.state = State()
        self._forced_target_outcome = target_outcome

        self.bid_hist: Dict[str, Deque[Tuple[float, float]]] = {}
        self._pos_open_ts: Optional[float] = None

        # pending BUY tracking
        self._pending_buy_price: Optional[float] = None
        self._pending_buy_qty: float = 0.0
        self._pending_buy_ts: float = 0.0

        # pending SELL tracking
        self._pending_sell_price: Optional[float] = None
        self._pending_sell_qty: float = 0.0
        self._pending_sell_ts: float = 0.0

        self._last_synced_inventory: float = 0.0
        self._pending_order_timeout: float = 60.0
        self._fills_lock = threading.Lock()
        self._buy_fill_queue: Dict[str, Deque[Tuple[float, float]]] = {}
        self._sell_fill_queue: Dict[str, Deque[Tuple[float, float]]] = {}
        self._fallback_priced_queue: Dict[str, Deque[Tuple[float, float]]] = {}
        self._vwap_priced_qty: Dict[str, float] = {}

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

        self.bid_hist = {o: deque(maxlen=600) for o in self.outcomes}

        self._clear_pending_buy()
        self._clear_pending_sell()
        self._last_synced_inventory = 0.0
        self._buy_fill_queue = {o: deque() for o in self.outcomes}
        self._sell_fill_queue = {o: deque() for o in self.outcomes}
        self._fallback_priced_queue = {o: deque() for o in self.outcomes}
        self._vwap_priced_qty = {o: 0.0 for o in self.outcomes}

        self._sync_inventory_from_positions()

        if self.state.inventory_shares > 0:
            self.state.phase = Phase.HOLD
            self._pos_open_ts = now
            if self.state.vwap_entry is None:
                self._recover_vwap_fallback("on_start with existing inventory")

        self.client.on_fill(self._handle_fill_event)

        logger.info(
            f"\n{Colors.bold('DefensiveCapitalPreservation Config:')}\n"
            f"  TargetOutcome: {Colors.magenta(str(self.state.target_outcome))}\n"
            f"  shares={Colors.cyan(str(self.shares))} maxInv={Colors.cyan(str(self.max_inventory))}\n"
            f"  BuyBand=[{Colors.yellow(f'{self.buy_band_low:.2f}')}, {Colors.yellow(f'{self.buy_band_high:.2f}')}] "
            f"buyCooldown={Colors.gray(f'{self.buy_cooldown_seconds:.0f}s')} cashBuffer={Colors.gray(f'{self.min_cash_buffer:.2f}')}\n"
            f"  TP={Colors.yellow(f'{self.take_profit_pct*100:.2f}%')} SL={Colors.yellow(f'{self.stop_loss_pct*100:.2f}%')} "
            f"maxHold={Colors.gray(f'{self.max_hold_seconds:.0f}s')}\n"
            f"  Failure: maxConsecutive={Colors.gray(str(self.max_consecutive_failures))} "
            f"cooldown={Colors.gray(f'{self.failure_cooldown_seconds:.0f}s')}\n"
            f"  PostExitCooldown={Colors.gray(f'{self.post_exit_cooldown_seconds:.0f}s')}\n"
            f"  interval={Colors.gray(f'{self.check_interval:.2f}s')}\n"
        )

    def on_stop(self) -> None:
        logger.info(f"\n{Colors.bold('Shutting down...')}")
        try:
            self.cancel_all_orders()
        except Exception as e:
            logger.error(f"Error canceling orders during shutdown: {e}")

    # ---------- main loop ----------
    def on_tick(self) -> None:
        self.refresh_state()
        now = time.time()

        if self._in_failure_cooldown(now):
            self._log_status(extra=f"FAIL_COOLDOWN ({self.failure_cooldown_seconds:.0f}s)")
            return

        self._update_histories(now)

        if not self.state.target_outcome:
            self.state.target_outcome = self._select_target_outcome()
            if not self.state.target_outcome:
                self._log_status(extra="No target outcome available")
                return

        # Expire stale pending orders
        self._expire_pending_orders(now)

        # Always sync inventory (fill detection here)
        self._sync_inventory_from_positions()

        # If inv>0 but vwap missing, recover
        if self.state.inventory_shares > 0 and self.state.vwap_entry is None:
            self._recover_vwap_fallback("inventory > 0 but vwap is None")

        # Phase routing
        if self.state.phase == Phase.ACCUMULATE:
            if self.state.inventory_shares > 0:
                self._enter_hold(now, reason="Found existing inventory -> HOLD")
            else:
                self._accumulate(now)

        elif self.state.phase == Phase.HOLD:
            # Core logic: if no position, skip exit logic and clean up state
            if self.state.inventory_shares <= 0:
                if self._has_pending_buy():
                    # Position update may be delayed, wait for confirmation
                    pass
                else:
                    self._enter_accumulate(now, reason="No inventory in HOLD -> ACCUMULATE")
            else:
                if self._pos_open_ts and (now - self._pos_open_ts) >= self.max_hold_seconds:
                    self._enter_exiting(now, reason="MAX_HOLD reached -> EXITING")
                else:
                    self._maybe_exit(now)

        elif self.state.phase == Phase.EXITING:
            self._sell_all(now)

        elif self.state.phase == Phase.COOLDOWN:
            if (now - self.state.phase_start_ts) >= self.post_exit_cooldown_seconds:
                self._enter_accumulate(now, reason="COOLDOWN done -> ACCUMULATE")

        self._log_status()

    # ---------- phase actions ----------
    def _accumulate(self, now: float) -> None:
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

        est_cost = price * self.shares
        if not self._has_sufficient_cash(est_cost):
            self._log_status(extra=f"SKIP BUY (cash too low for cost~{est_cost:.2f})")
            return

        logger.info(
            f"  {Colors.bold('ACCUM')} {Colors.magenta(outcome)} "
            f"band hit -> BUY {Colors.cyan(str(self.shares))} @ {Colors.yellow(f'{price:.4f}')}"
        )

        # Store pending BUY before placing
        self._pending_buy_price = price
        self._pending_buy_qty = self.shares
        self._pending_buy_ts = now

        ok = self._place_order(outcome, OrderSide.BUY, price, self.shares, token_id)
        if not ok:
            self._clear_pending_buy()
            return

        self.state.last_buy_ts = now
        self._enter_hold(now, reason="BUY placed -> HOLD (awaiting fill)")

    def _maybe_exit(self, now: float) -> None:
        outcome = self.state.target_outcome
        token_id = self.get_token_id(outcome)
        if not token_id:
            return

        # If inventory is zero, no need to check exit conditions
        if self.state.inventory_shares <= 0:
            return

        bid, _ask = self.get_best_bid_ask(token_id)
        if bid is None or bid <= 0 or bid > 1.0:
            return
        bid = float(bid)

        vwap = self.state.vwap_entry
        if vwap is None or vwap <= 0:
            # If we reach here with invalid vwap, it's truly an abnormal state
            logger.warning(
                f"  {Colors.yellow('WARN')} _maybe_exit called with vwap=None "
                f"(inv={self.state.inventory_shares:.2f})."
            )
            return

        stop_price = vwap * (1.0 - self.stop_loss_pct)
        if bid <= stop_price:
            self.state.last_sl_ts = now
            self._enter_exiting(
                now,
                reason=f"STOP_LOSS (bid {bid:.4f} <= {stop_price:.4f}, vwap {vwap:.4f})"
            )
            return

        tp_price = vwap * (1.0 + self.take_profit_pct)
        if bid >= tp_price:
            if self.min_profit_abs > 0:
                approx_pnl = (bid - vwap) * float(self.state.inventory_shares)
                if approx_pnl < self.min_profit_abs:
                    return
            self.state.last_tp_ts = now
            self._enter_exiting(
                now,
                reason=f"TAKE_PROFIT (bid {bid:.4f} >= {tp_price:.4f}, vwap {vwap:.4f})"
            )

    def _sell_all(self, now: float) -> None:
        if self._has_pending_sell():
            return
        if (now - self.state.last_sell_ts) < self.sell_cooldown_seconds:
            return

        self._sync_inventory_from_positions()
        if self.state.inventory_shares <= 0:
            # Only transition to cooldown here
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

        # Record pending SELL
        self._pending_sell_price = sell_price
        self._pending_sell_qty = sell_qty
        self._pending_sell_ts = now

        ok = self._place_order(outcome, OrderSide.SELL, sell_price, sell_qty, token_id)
        if not ok:
            self._clear_pending_sell()
            return

        self.state.last_sell_ts = now

        # Important: stay in EXITING phase after placing sell order
        # Only transition to COOLDOWN when inventory==0 is confirmed
        return

    # ---------- helpers ----------
    def _update_histories(self, now: float) -> None:
        for outcome in self.outcomes:
            token_id = self.get_token_id(outcome)
            if not token_id:
                continue
            bid, _ask = self.get_best_bid_ask(token_id)
            if bid is not None and 0 < bid <= 1.0:
                self.bid_hist[outcome].append((now, float(bid)))

        window = 60.0
        for outcome in self.outcomes:
            h = self.bid_hist.get(outcome)
            while h and (now - h[0][0]) > window:
                h.popleft()

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

    def _sync_inventory_from_positions(self) -> None:
        if not self.state.target_outcome:
            return

        actual = float(self.positions.get(self.state.target_outcome, 0.0))
        previous = float(self._last_synced_inventory)
        outcome = self.state.target_outcome

        # SELL fill detected (inventory decreased)
        if actual < previous:
            sold_qty = previous - actual
            logger.info(
                f"  {Colors.green('SELL FILL DETECTED')} inventory {previous:.2f} -> {actual:.2f} (-{sold_qty:.2f})"
            )
            # pending SELL clear once we see any decrease (pragmatic)
            if self._pending_sell_price is not None:
                self._clear_pending_sell()

        self.state.inventory_shares = actual
        self._last_synced_inventory = actual

        # Atomic critical section: fill queue access, VWAP calculation, state updates
        with self._fills_lock:
            if outcome:
                priced_qty = float(self._vwap_priced_qty.get(outcome, 0.0))
                if actual < priced_qty:
                    self._vwap_priced_qty[outcome] = actual
                    priced_qty = actual

                self._reconcile_fallback_with_fills(outcome)

                unpriced_qty = max(0.0, actual - priced_qty)
                if unpriced_qty > 0:
                    unpriced_qty = self._consume_buy_fills(outcome, unpriced_qty)

                if unpriced_qty > 0:
                    if self._pending_buy_price is not None:
                        self._apply_fallback_price(outcome, self._pending_buy_price, unpriced_qty)
                        self._clear_pending_buy()
                    else:
                        logger.warning("WARN: VWAP fallback used because fill price unavailable")
                        self._recover_vwap_fallback("fill price unavailable")
                        if self.state.vwap_entry is not None:
                            self._vwap_priced_qty[outcome] = actual

            # Inventory fully closed, cooldown is allowed and vwap reset
            if actual <= 0:
                if self._pending_buy_price is None:  # Keep vwap if buy is pending
                    self.state.vwap_entry = None
                    self._pos_open_ts = None
                    if outcome:
                        self._vwap_priced_qty[outcome] = 0.0
                        self._fallback_priced_queue[outcome].clear()

        # Check phase transition outside lock (to avoid holding lock during transition)
        if actual <= 0 and self.state.phase == Phase.EXITING:
            self._enter_cooldown(time.time(), reason="Position closed -> COOLDOWN")

    def _update_vwap_on_fill(self, fill_price: float, fill_qty: float, inv_before: float) -> None:
        if fill_qty <= 0 or fill_price <= 0:
            return

        if self.state.vwap_entry is None or inv_before <= 0:
            self.state.vwap_entry = float(fill_price)
        else:
            vwap = float(self.state.vwap_entry)
            self.state.vwap_entry = (vwap * inv_before + fill_price * fill_qty) / (inv_before + fill_qty)

    def _handle_fill_event(self, event, order, fill_size: float) -> None:
        if order.market_id != self.market_id:
            return
        outcome = order.outcome
        fill_qty = float(fill_size)
        fill_price = float(order.price)
        if fill_qty <= 0 or fill_price <= 0:
            return

        with self._fills_lock:
            if order.side == OrderSide.BUY:
                self._buy_fill_queue.setdefault(outcome, deque()).append((fill_price, fill_qty))
            elif order.side == OrderSide.SELL:
                self._sell_fill_queue.setdefault(outcome, deque()).append((fill_price, fill_qty))

    def _consume_buy_fills(self, outcome: str, target_qty: float) -> float:
        """Consume fills from queue. Caller must hold _fills_lock."""
        if target_qty <= 0:
            return 0.0

        q = self._buy_fill_queue.get(outcome)
        while q and target_qty > 0:
                fill_price, fill_qty = q[0]
                take_qty = min(fill_qty, target_qty)
                inv_before = float(self._vwap_priced_qty.get(outcome, 0.0))
                self._update_vwap_on_fill(fill_price, take_qty, inv_before)
                self._vwap_priced_qty[outcome] = inv_before + take_qty
                pending_price = self._pending_buy_price
                pending_str = f"{pending_price:.4f}" if pending_price is not None else "N/A"
                logger.info(
                    f"  {Colors.green('VWAP UPDATED')} using fill_price={fill_price:.4f}, "
                    f"pending_price={pending_str}, new vwap={self.state.vwap_entry:.4f}"
                )

                target_qty -= take_qty
                if take_qty >= fill_qty:
                    q.popleft()
                else:
                    q[0] = (fill_price, fill_qty - take_qty)
                    break

        return target_qty

    def _apply_fallback_price(self, outcome: str, price: float, qty: float) -> None:
        if qty <= 0 or price <= 0:
            return
        logger.warning("WARN: VWAP fallback used because fill price unavailable")
        inv_before = float(self._vwap_priced_qty.get(outcome, 0.0))
        self._update_vwap_on_fill(price, qty, inv_before)
        self._vwap_priced_qty[outcome] = inv_before + qty
        self._fallback_priced_queue.setdefault(outcome, deque()).append((price, qty))
        pending_price = self._pending_buy_price
        pending_str = f"{pending_price:.4f}" if pending_price is not None else "N/A"
        logger.info(
            f"  {Colors.green('VWAP UPDATED')} using fill_price=N/A, "
            f"pending_price={pending_str}, new vwap={self.state.vwap_entry:.4f}"
        )

    def _reconcile_fallback_with_fills(self, outcome: str) -> None:
        with self._fills_lock:
            fallback_q = self._fallback_priced_queue.get(outcome)
            fill_q = self._buy_fill_queue.get(outcome)
            if not fallback_q or not fill_q:
                return

            while fallback_q and fill_q:
                fallback_price, fallback_qty = fallback_q[0]
                fill_price, fill_qty = fill_q[0]
                replace_qty = min(fallback_qty, fill_qty)
                priced_qty = float(self._vwap_priced_qty.get(outcome, 0.0))
                if self.state.vwap_entry is not None and priced_qty > 0:
                    vwap = float(self.state.vwap_entry)
                    self.state.vwap_entry = (
                        (vwap * priced_qty - fallback_price * replace_qty + fill_price * replace_qty)
                        / priced_qty
                    )
                    pending_price = self._pending_buy_price
                    pending_str = f"{pending_price:.4f}" if pending_price is not None else "N/A"
                    logger.info(
                        f"  {Colors.green('VWAP UPDATED')} using fill_price={fill_price:.4f}, "
                        f"pending_price={pending_str}, new vwap={self.state.vwap_entry:.4f}"
                    )

                if replace_qty >= fallback_qty:
                    fallback_q.popleft()
                else:
                    fallback_q[0] = (fallback_price, fallback_qty - replace_qty)

                if replace_qty >= fill_qty:
                    fill_q.popleft()
                else:
                    fill_q[0] = (fill_price, fill_qty - replace_qty)

    # ----- pending helpers -----
    def _has_pending_buy(self) -> bool:
        return self._pending_buy_price is not None

    def _clear_pending_buy(self) -> None:
        self._pending_buy_price = None
        self._pending_buy_qty = 0.0
        self._pending_buy_ts = 0.0

    def _has_pending_sell(self) -> bool:
        return self._pending_sell_price is not None

    def _clear_pending_sell(self) -> None:
        self._pending_sell_price = None
        self._pending_sell_qty = 0.0
        self._pending_sell_ts = 0.0

    def _expire_pending_orders(self, now: float) -> None:
        if self._pending_buy_price is not None and (now - self._pending_buy_ts) > self._pending_order_timeout:
            logger.warning(
                f"  {Colors.yellow('WARN')} Pending BUY expired after {self._pending_order_timeout:.0f}s "
                f"(price={self._pending_buy_price:.4f}, qty={self._pending_buy_qty:.2f})"
            )
            self._clear_pending_buy()

        if self._pending_sell_price is not None and (now - self._pending_sell_ts) > self._pending_order_timeout:
            logger.warning(
                f"  {Colors.yellow('WARN')} Pending SELL expired after {self._pending_order_timeout:.0f}s "
                f"(price={self._pending_sell_price:.4f}, qty={self._pending_sell_qty:.2f})"
            )
            self._clear_pending_sell()

    def _recover_vwap_fallback(self, reason: str) -> None:
        if self.state.vwap_entry is not None:
            return
        if self.state.inventory_shares <= 0:
            return

        outcome = self.state.target_outcome
        if not outcome:
            return

        token_id = self.get_token_id(outcome)
        if not token_id:
            return

        bid, ask = self.get_best_bid_ask(token_id)

        # Conservative approach: use bid price first (safer for exit calculations)
        fallback_price = None
        if bid is not None and 0 < bid <= 1.0:
            fallback_price = float(bid)
        elif ask is not None and 0 < ask <= 1.0:
            fallback_price = float(ask)

        if fallback_price is not None:
            self.state.vwap_entry = fallback_price
            logger.warning(
                f"  {Colors.yellow('VWAP RECOVERED')} using fallback price {fallback_price:.4f} (reason: {reason})"
            )
        else:
            logger.error(
                f"  {Colors.red('ERROR')} Cannot recover VWAP - no valid price (reason: {reason})"
            )

    def _has_sufficient_cash(self, est_cost: float) -> bool:
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

            # Core logic: do not reset vwap if inventory > 0
            if self.state.inventory_shares <= 0 and not self._has_pending_buy():
                self.state.vwap_entry = None

            self._pos_open_ts = None
            if reason:
                logger.info(f"  {Colors.green('PHASE')} ACCUMULATE | {Colors.gray(reason)}")

    def _enter_cooldown(self, now: float, reason: str = "") -> None:
        if self.state.phase != Phase.COOLDOWN:
            self.state.phase = Phase.COOLDOWN
            self.state.phase_start_ts = now
            # Clear pending orders when entering cooldown
            self._clear_pending_buy()
            self._clear_pending_sell()
            if reason:
                logger.info(f"  {Colors.green('PHASE')} COOLDOWN | {Colors.gray(reason)}")

    # ---------- logging ----------
    def _log_status(self, extra: str = "") -> None:
        cash_str = f"{self.cash:.2f}" if isinstance(self.cash, (int, float)) else "N/A"
        outcome = self.state.target_outcome
        inv = self.state.inventory_shares
        vwap = self.state.vwap_entry

        pending_parts = []
        if self._pending_buy_price is not None:
            pending_parts.append(Colors.yellow(f"pending_buy@{self._pending_buy_price:.4f}"))
        if self._pending_sell_price is not None:
            pending_parts.append(Colors.yellow(f"pending_sell@{self._pending_sell_price:.4f}"))
        pending_str = f" | {' '.join(pending_parts)}" if pending_parts else ""

        pnl_str = ""
        if vwap and inv > 0 and outcome:
            token_id = self.get_token_id(outcome)
            if token_id:
                bid, _ = self.get_best_bid_ask(token_id)
                if bid and bid > 0:
                    pnl = (float(bid) - vwap) * inv
                    pnl_pct = ((float(bid) / vwap) - 1) * 100
                    pnl_color = Colors.green if pnl >= 0 else Colors.red
                    pnl_str = f" | pnl={pnl_color(f'{pnl:+.4f} ({pnl_pct:+.2f}%)')}"

        msg = (
            f"{Colors.gray('phase')}: {Colors.gray(self.state.phase)} | "
            f"{Colors.gray('outcome')}: {Colors.magenta(str(outcome))} | "
            f"{Colors.gray('inv')}: {Colors.cyan(f'{inv:.2f}')} | "
            f"{Colors.gray('vwap')}: {Colors.cyan(f'{vwap:.4f}' if vwap is not None else 'N/A')} | "
            f"cash={Colors.cyan(cash_str)} | "
            f"fails={Colors.gray(str(self.state.consecutive_order_failures))}"
            f"{pending_str}"
            f"{pnl_str}"
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
            except Exception as e:
                logger.debug(f"Error fetching markets page {page}: {e}")
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
    p = argparse.ArgumentParser(description="Defensive Capital Preservation Strategy")
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

    p.add_argument("--tp", type=float, default=0.007)
    p.add_argument("--sl", type=float, default=0.035)
    p.add_argument("--min-profit-abs", type=float, default=0.0)
    p.add_argument("--max-hold", type=float, default=3600.0)

    p.add_argument("--sell-cooldown", type=float, default=2.0)
    p.add_argument("--post-exit-cooldown", type=float, default=5.0)
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

    strat = DefensiveCapitalPreservationStrategy(
        exchange=exchange,
        market_id=market_id,
        target_outcome=args.outcome,
        shares=args.shares,
        max_inventory=args.max_inventory,
        buy_band_low=args.buy_band_low,
        buy_band_high=args.buy_band_high,
        buy_cooldown_seconds=args.buy_cooldown,
        min_cash_buffer=args.cash_buffer,
        take_profit_pct=args.tp,
        stop_loss_pct=args.sl,
        min_profit_abs=args.min_profit_abs,
        max_hold_seconds=args.max_hold,
        sell_cooldown_seconds=args.sell_cooldown,
        post_exit_cooldown_seconds=args.post_exit_cooldown,
        check_interval=args.interval,
        max_consecutive_failures=args.max_fails,
        failure_cooldown_seconds=args.fail_cooldown,
    )
    strat.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
