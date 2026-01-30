"""
VPIN-Based BBO Market Making Strategy

Combines BBO-joining spread quoting with VPIN-based liquidity withdrawal.

- Earns spread by joining best bid/ask (BBO) on each outcome
- Monitors order flow toxicity using a VPIN-like metric (Price-Spread Toxicity Score)
- Withdraws liquidity when toxicity exceeds threshold (adverse selection detected)
- Resumes market making when toxicity falls below resume threshold

VPIN Metric (Prediction Market Adapted):
    Instead of classic buy/sell volume imbalance (unreliable on Polymarket),
    we use exponentially-weighted price velocity + spread pressure:

    toxicity = 0.7 * ema_price_velocity + 0.3 * spread_pressure

    Where:
    - ema_price_velocity: EMA of absolute mid-price returns (recent price jumpiness)
    - spread_pressure: normalized spread compression (1 - spread/ema_spread)

    This captures adverse selection risk from rapid price moves and spread collapse,
    using only reliable orderbook data.

Usage:
    uv run python examples/vpin_strategy.py --slug bitcoin-above-100000-on-january-1
    uv run python examples/vpin_strategy.py --market-id MARKET_ID --vpin-threshold 0.75

Environment:
    export POLYMARKET_PRIVATE_KEY=...
    export POLYMARKET_FUNDER=...
"""

import argparse
import math
import os
import sys
import threading
import time
from collections import deque
from typing import Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv

from dr_manhattan import Strategy
from dr_manhattan.base import Exchange, create_exchange
from dr_manhattan.models import Market
from dr_manhattan.models.order import Order, OrderSide
from dr_manhattan.utils import prompt_market_selection, setup_logger
from dr_manhattan.utils.logger import Colors

logger = setup_logger(__name__)


class VPINState:
    """State for VPIN calculation and gating logic"""

    def __init__(self):
        # Price-Spread Toxicity components
        self.ema_velocity: float = 0.0  # EMA of absolute mid-price returns
        self.ema_spread: float = 0.0  # EMA of spread width
        self.current_spread: float = 0.0  # Current spread (for pressure calculation)
        self.last_mid: Optional[float] = None  # Previous mid-price
        self.update_count: int = 0  # Number of toxicity updates (for warmup)

        # Toxicity history (for logging/analysis)
        self.toxicity_history: deque = deque(maxlen=100)  # Recent toxicity scores

        # Liquidity state
        self.is_liquidity_withdrawn: bool = False
        self.last_withdraw_time: float = 0.0
        self.last_resume_time: float = 0.0

        # Optional: tick-rule trade tracking (fallback if orderbook unreliable)
        self.seen_trades: deque = deque(maxlen=5000)
        self.seen_trades_set: set = set()
        self.last_trade_ts: int = 0
        self.last_trade_price: Optional[float] = None
        self.total_trades_processed: int = 0
        self.tick_buy_count: int = 0  # Trades with upward tick
        self.tick_sell_count: int = 0  # Trades with downward tick


class VPINBBOStrategy(Strategy):
    """
    BBO Market Making with VPIN-based liquidity withdrawal.

    Continuously joins the BBO to earn spread, but withdraws liquidity
    when VPIN indicates toxic order flow (informed trading).
    """

    def __init__(
        self,
        exchange: Exchange,
        market_id: str,
        max_position: float = 100.0,
        order_size: float = 5.0,
        max_delta: float = 20.0,
        check_interval: float = 5.0,
        # VPIN parameters (adapted for price-spread toxicity)
        alpha_fast: float = 0.3,  # EMA decay for price velocity (fast)
        alpha_slow: float = 0.05,  # EMA decay for spread baseline (slow)
        velocity_weight: float = 0.7,  # Weight for price velocity component
        spread_weight: float = 0.3,  # Weight for spread pressure component
        warmup_ticks: int = 20,  # Ticks needed before VPIN is valid
        vpin_threshold: float = 0.80,
        resume_threshold: Optional[float] = None,
        cooldown_seconds: float = 60.0,
        # Trade polling (optional for tick-rule fallback)
        trade_poll_interval: float = 2.0,
        enable_trade_polling: bool = False,  # Disabled by default (not needed for price-spread metric)
    ):
        super().__init__(
            exchange=exchange,
            market_id=market_id,
            max_position=max_position,
            order_size=order_size,
            max_delta=max_delta,
            check_interval=check_interval,
            track_fills=True,
        )

        # VPIN config (price-spread toxicity parameters)
        self.alpha_fast = float(alpha_fast)
        self.alpha_slow = float(alpha_slow)
        self.velocity_weight = float(velocity_weight)
        self.spread_weight = float(spread_weight)
        self.warmup_ticks = int(warmup_ticks)
        self.vpin_threshold = float(vpin_threshold)
        self.resume_threshold = (
            float(resume_threshold) if resume_threshold is not None else self.vpin_threshold * 0.875
        )  # 12.5% hysteresis by default
        self.cooldown_seconds = float(cooldown_seconds)

        # Trade polling (optional)
        self.trade_poll_interval = float(trade_poll_interval)
        self.enable_trade_polling = enable_trade_polling

        # State
        self.vpin_state = VPINState()
        self.state_lock = threading.Lock()

        # Logging control
        self.tick_count = 0
        self.log_interval = 6  # Log VPIN every 6 ticks (~30s if check_interval=5s)

        # Background thread
        self.trade_thread: Optional[threading.Thread] = None
        self.trade_thread_running = False

    def setup(self) -> bool:
        """Setup market and start trade polling thread (if enabled)"""
        if not super().setup():
            return False

        self._log_vpin_config()

        # Start trade polling thread only if enabled (for tick-rule fallback)
        if self.enable_trade_polling:
            self.trade_thread = threading.Thread(target=self._trade_poll_loop, daemon=True)
            self.trade_thread_running = True
            self.trade_thread.start()
            logger.info(f"{Colors.cyan('Trade polling:')} enabled (tick-rule fallback)")
        else:
            logger.info(f"{Colors.gray('Trade polling:')} disabled (using orderbook-only metric)")

        # Wait for initial orderbook data
        time.sleep(3)

        return True

    def _log_vpin_config(self):
        """Log VPIN configuration"""
        logger.info(
            f"\n{Colors.bold('VPIN Config (Price-Spread Toxicity):')}\n"
            f"  α_fast: {Colors.cyan(f'{self.alpha_fast:.2f}')} | "
            f"α_slow: {Colors.cyan(f'{self.alpha_slow:.2f}')} | "
            f"weights: {Colors.cyan(f'{self.velocity_weight:.1f}')}/{Colors.cyan(f'{self.spread_weight:.1f}')}\n"
            f"  Withdraw: {Colors.yellow(f'{self.vpin_threshold:.2f}')} | "
            f"Resume: {Colors.green(f'{self.resume_threshold:.2f}')} | "
            f"Cooldown: {Colors.gray(f'{self.cooldown_seconds:.0f}s')} | "
            f"Warmup: {Colors.gray(f'{self.warmup_ticks} ticks')}"
        )

    # VPIN Calculation (Price-Spread Toxicity)

    def _update_toxicity_from_orderbook(self):
        """
        Update toxicity score from orderbook BBO data.

        Computes:
        - Price velocity: EMA of absolute mid-price returns
        - Spread pressure: normalized spread compression
        - Toxicity: weighted combination
        """
        # Get aggregate BBO across all outcomes (use first outcome as proxy, or compute average)
        # For simplicity, use the first outcome token
        if not self.outcome_tokens or len(self.outcome_tokens) == 0:
            logger.debug("No outcome tokens available for toxicity update")
            return

        token_id = self.outcome_tokens[0].token_id
        best_bid, best_ask = self.get_best_bid_ask(token_id)

        if best_bid is None or best_ask is None or best_bid <= 0 or best_ask <= 0:
            return

        # Validate bid/ask
        if best_bid >= best_ask:
            return

        mid = (best_bid + best_ask) / 2.0
        spread = best_ask - best_bid

        with self.state_lock:
            # Initialize on first update
            if self.vpin_state.last_mid is None:
                self.vpin_state.last_mid = mid
                self.vpin_state.ema_spread = spread
                self.vpin_state.current_spread = spread
                self.vpin_state.update_count = 1
                return

            # Compute mid-price return (velocity)
            mid_return = abs(mid - self.vpin_state.last_mid) / max(self.vpin_state.last_mid, 1e-9)

            # Update EMAs
            self.vpin_state.ema_velocity = (
                self.alpha_fast * mid_return + (1 - self.alpha_fast) * self.vpin_state.ema_velocity
            )
            self.vpin_state.ema_spread = (
                self.alpha_slow * spread + (1 - self.alpha_slow) * self.vpin_state.ema_spread
            )

            # Store current spread for pressure calculation
            self.vpin_state.current_spread = spread

            # Update state
            self.vpin_state.last_mid = mid
            self.vpin_state.update_count += 1

    def _get_vpin(self) -> float:
        """
        Compute toxicity score from price velocity + spread pressure.

        Returns value in [0, 1] range (approximately).
        """
        with self.state_lock:
            if self.vpin_state.update_count < 2:
                return 0.0

            # Price velocity component (normalize by typical range)
            # Typical mid return: 0-5% per tick, so divide by 0.05 to get [0,1] range
            velocity_component = min(1.0, self.vpin_state.ema_velocity / 0.05)

            # Spread pressure component (high when spread compresses below baseline)
            if self.vpin_state.ema_spread > 1e-9:
                # Compare current spread to EMA baseline
                # If current spread < ema_spread, pressure is positive (spread compressed)
                spread_ratio = self.vpin_state.current_spread / max(self.vpin_state.ema_spread, 1e-9)
                spread_pressure = max(0.0, 1.0 - spread_ratio)
            else:
                spread_pressure = 0.0

            # Combined toxicity score
            toxicity = (
                self.velocity_weight * velocity_component +
                self.spread_weight * spread_pressure
            )

            # Store in history
            self.vpin_state.toxicity_history.append(toxicity)

            return toxicity

    def _is_vpin_ready(self) -> bool:
        """Check if enough updates have occurred for VPIN to be valid"""
        with self.state_lock:
            return self.vpin_state.update_count >= self.warmup_ticks

    # Trade Polling

    def _trade_poll_loop(self):
        if not hasattr(self.exchange, "DATA_API_URL"):
            logger.warning("Exchange does not support trade polling - VPIN disabled")
            return

        condition_id = self.market.metadata.get("conditionId", self.market.id)
        url = f"{self.exchange.DATA_API_URL}/trades"
        logger.info(f"Starting trade polling: {url} (market={str(condition_id)[:8]}...)")

        poll_count = 0
        while self.trade_thread_running:
            if not getattr(self, "is_running", False):
                time.sleep(0.2)
                continue

            poll_count += 1
            try:
                params = {"market": condition_id, "limit": 200, "offset": 0, "takerOnly": "true"}
                resp = requests.get(url, params=params, timeout=5)
                resp.raise_for_status()
                data = resp.json()

                if isinstance(data, list):
                    self._process_trades(data)
            except Exception as e:
                logger.debug(f"Trade poll #{poll_count} failed: {e}")

            time.sleep(self.trade_poll_interval)

    def _process_trades(self, trades: List[Dict]):
        """Process trades from API response with de-duplication"""
        new_rows = []

        for row in trades:
            # Extract trade fields
            ts = row.get("timestamp")
            tx = row.get("transactionHash") or row.get("transaction_hash")
            side = row.get("side")
            price = row.get("price")
            size = row.get("size")

            # Create de-duplication key
            key = (tx, ts, side, price, size)

            with self.trade_lock:
                # Skip if already seen
                if key in self.vpin_state.seen_trades_set:
                    continue

            # Parse timestamp
            try:
                ts_int = int(ts) if ts is not None else 0
            except Exception:
                ts_int = 0

            # Only accept newer trades
            with self.trade_lock:
                if ts_int < self.vpin_state.last_trade_ts:
                    continue

            new_rows.append((ts_int, key, row))

        # Sort by timestamp (chronological order)
        new_rows.sort(key=lambda x: x[0])

        # Ingest trades
        for ts_int, key, row in new_rows:
            with self.trade_lock:
                # Update seen trades
                if len(self.vpin_state.seen_trades) == self.vpin_state.seen_trades.maxlen:
                    old_key = self.vpin_state.seen_trades.popleft()
                    self.vpin_state.seen_trades_set.discard(old_key)

                self.vpin_state.seen_trades.append(key)
                self.vpin_state.seen_trades_set.add(key)
                self.vpin_state.last_trade_ts = max(self.vpin_state.last_trade_ts, ts_int)

            self._handle_trade(row)

    def _handle_trade(self, trade: Dict):
        """
        Ingest a single trade using tick rule for direction inference.

        This is optional (only runs if trade polling enabled).
        Can be used as fallback metric or for additional analysis.
        """
        price_raw = trade.get("price")
        size_raw = trade.get("size")

        try:
            price = float(price_raw)
            size = float(size_raw)
            if size <= 0:
                return
        except Exception:
            return

        with self.state_lock:
            self.vpin_state.total_trades_processed += 1

            # Tick rule: infer direction from price change
            if self.vpin_state.last_trade_price is not None:
                if price > self.vpin_state.last_trade_price:
                    # Upward tick -> inferred BUY
                    self.vpin_state.tick_buy_count += 1
                    inferred_side = "BUY"
                elif price < self.vpin_state.last_trade_price:
                    # Downward tick -> inferred SELL
                    self.vpin_state.tick_sell_count += 1
                    inferred_side = "SELL"
                else:
                    # No change -> use last direction (not implemented, skip)
                    inferred_side = "NEUTRAL"
            else:
                inferred_side = "UNKNOWN"

            self.vpin_state.last_trade_price = price

        # Log occasionally
        if self.vpin_state.total_trades_processed <= 5 or self.vpin_state.total_trades_processed % 20 == 0:
            logger.debug(
                f"{Colors.gray(f'Trade #{self.vpin_state.total_trades_processed}')}: "
                f"{size:.2f} @ {price:.4f} (tick: {inferred_side})"
            )

    # BBO Market Making with VPIN Gating

    def on_tick(self):
        """Main strategy tick - VPIN gating + BBO market making"""
        self.tick_count += 1

        # Update toxicity from orderbook
        self._update_toxicity_from_orderbook()

        # Get current toxicity score
        vpin = self._get_vpin()
        vpin_ready = self._is_vpin_ready()

        # Log VPIN status (periodically to reduce spam)
        if self.tick_count % self.log_interval == 0 or not vpin_ready or self.vpin_state.is_liquidity_withdrawn:
            self._log_vpin_status(vpin, vpin_ready)

        # VPIN gating logic with hysteresis
        if vpin_ready:
            self._update_liquidity_state(vpin)
        else:
            # During warmup, show a hint occasionally
            if self.tick_count % self.log_interval == 0:
                with self.state_lock:
                    update_count = self.vpin_state.update_count
                logger.info(
                    f"  VPIN warming up... ({update_count}/{self.warmup_ticks} updates) "
                    f"- market making active"
                )

        # If liquidity is withdrawn, skip market making
        if self.vpin_state.is_liquidity_withdrawn:
            if self.tick_count % self.log_interval == 0:
                logger.info(Colors.red("  Liquidity WITHDRAWN - not quoting"))
            return

        # Otherwise, proceed with normal BBO market making
        if self.tick_count % self.log_interval == 0:
            self.log_status()
        self._place_bbo_orders_with_risk_limits()

    def _log_vpin_status(self, vpin: float, ready: bool):
        """Log current VPIN status (toxicity score)"""
        with self.state_lock:
            update_count = self.vpin_state.update_count
            ema_velocity = self.vpin_state.ema_velocity
            ema_spread = self.vpin_state.ema_spread
            total_trades = self.vpin_state.total_trades_processed

        status_parts = [
            f"VPIN: {Colors.yellow(f'{vpin:.4f}')}",
        ]

        # Status indicator
        if not ready:
            status_parts.append(Colors.gray(f"(warming up, {update_count}/{self.warmup_ticks} updates)"))
        elif vpin >= self.vpin_threshold:
            status_parts.append(Colors.red("HIGH"))
        elif vpin >= self.resume_threshold:
            status_parts.append(Colors.yellow("ELEVATED"))
        else:
            status_parts.append(Colors.green("OK"))

        # Components (for debugging)
        velocity_norm = min(1.0, ema_velocity / 0.05)
        status_parts.append(
            f"velocity: {Colors.cyan(f'{velocity_norm:.3f}')} "
            f"spread: {Colors.cyan(f'{ema_spread:.4f}')}"
        )

        # Recent average
        if len(self.vpin_state.toxicity_history) >= 5:
            recent = list(self.vpin_state.toxicity_history)[-5:]
            recent_avg = sum(recent) / len(recent)
            status_parts.append(f"avg5: {Colors.gray(f'{recent_avg:.4f}')}")

        # Optional: trade count if polling enabled
        if self.enable_trade_polling and total_trades > 0:
            status_parts.append(f"trades: {Colors.gray(str(total_trades))}")

        logger.info(" | ".join(status_parts))

    def _update_liquidity_state(self, vpin: float):
        """Update liquidity state based on VPIN with hysteresis and cooldown"""
        now = time.time()

        # Currently providing liquidity
        if not self.vpin_state.is_liquidity_withdrawn:
            # Check if we should withdraw
            if vpin >= self.vpin_threshold:
                logger.warning(
                    f"\n{Colors.bold(Colors.red('WITHDRAWING LIQUIDITY'))} "
                    f"VPIN {vpin:.4f} >= {self.vpin_threshold:.2f}"
                )
                self.cancel_all_orders()
                self.vpin_state.is_liquidity_withdrawn = True
                self.vpin_state.last_withdraw_time = now

        # Currently withdrawn
        else:
            # Check cooldown
            if (now - self.vpin_state.last_withdraw_time) < self.cooldown_seconds:
                return

            # Check if we should resume (with hysteresis)
            if vpin < self.resume_threshold:
                logger.info(
                    f"\n{Colors.bold(Colors.green('RESUMING LIQUIDITY'))} "
                    f"VPIN {vpin:.4f} < {self.resume_threshold:.2f}"
                )
                self.vpin_state.is_liquidity_withdrawn = False
                self.vpin_state.last_resume_time = now

    def _place_bbo_orders_with_risk_limits(self):
        """Place BBO orders with risk limits (position, delta, shorting)"""
        self.refresh_state()

        for ot in self.outcome_tokens:
            self._place_bbo_for_outcome_with_limits(ot.outcome, ot.token_id)

    def _place_bbo_for_outcome_with_limits(self, outcome: str, token_id: str):
        """Place BBO orders for a single outcome with all risk limits"""
        best_bid, best_ask = self.get_best_bid_ask(token_id)

        if best_bid is None or best_ask is None:
            logger.debug(f"  {outcome}: No orderbook data (bid={best_bid}, ask={best_ask})")
            return

        # Use floor for bid, ceil for ask to avoid crossing spread
        our_bid = self._floor_to_tick(best_bid)
        our_ask = self._ceil_to_tick(best_ask)

        # Clamp to valid range [0.01, 0.99]
        our_bid = max(0.01, min(0.99, our_bid))
        our_ask = max(0.01, min(0.99, our_ask))

        # Validate spread
        if our_bid >= our_ask:
            logger.debug(f"  {outcome}: Invalid spread (bid={our_bid:.4f} >= ask={our_ask:.4f})")
            return

        position = self._positions.get(outcome, 0)
        buy_orders, sell_orders = self.get_orders_for_outcome(outcome)

        # Delta management
        force_buy_only = False
        force_sell_only = False

        if self._delta_info and self.delta > self.max_delta:
            # If this outcome has max position and delta too high, only allow sells
            if position == self._delta_info.max_position:
                force_sell_only = True
                logger.debug(f"  {outcome}: Delta mgmt - sell only")
            # If this outcome has min position and delta too high, only allow buys
            elif position == self._delta_info.min_position:
                force_buy_only = True
                logger.debug(f"  {outcome}: Delta mgmt - buy only")

        # BUY order logic
        should_buy = not force_sell_only

        if should_buy:
            if not self.has_order_at_price(buy_orders, our_bid):
                # Cancel stale orders
                self.cancel_stale_orders(buy_orders, our_bid)

                # Check position limit
                if position + self.order_size > self.max_position:
                    should_buy = False
                    logger.debug(
                        f"  {outcome}: Skip BUY - position limit "
                        f"(pos={position:.1f} + size={self.order_size:.1f} > max={self.max_position:.1f})"
                    )

                # Check cash
                if should_buy and self.cash < self.order_size:
                    should_buy = False
                    logger.info(
                        f"  {outcome}: Skip BUY - insufficient cash "
                        f"(${self.cash:.2f} < ${self.order_size:.2f})"
                    )

                if should_buy:
                    try:
                        self.create_order(outcome, OrderSide.BUY, our_bid, self.order_size, token_id)
                        self.log_order(OrderSide.BUY, self.order_size, outcome, our_bid)
                    except Exception as e:
                        logger.error(f"    BUY failed: {e}")

        # SELL order logic
        should_sell = not force_buy_only

        if should_sell:
            if not self.has_order_at_price(sell_orders, our_ask):
                # Cancel stale orders
                self.cancel_stale_orders(sell_orders, our_ask)

                # Never short (position must be > 0)
                if position <= 0:
                    should_sell = False
                    logger.debug(
                        f"  {outcome}: Skip SELL - no position (pos={position:.1f})"
                    )

                if should_sell:
                    # Sell size cannot exceed position
                    sell_size = min(position, self.order_size)

                    try:
                        self.create_order(outcome, OrderSide.SELL, our_ask, sell_size, token_id)
                        self.log_order(OrderSide.SELL, sell_size, outcome, our_ask)
                    except Exception as e:
                        logger.error(f"    SELL failed: {e}")

    def _floor_to_tick(self, price: float) -> float:
        """Round price down to tick size (for bids)"""
        return math.floor(price / self.tick_size) * self.tick_size

    def _ceil_to_tick(self, price: float) -> float:
        """Round price up to tick size (for asks)"""
        return math.ceil(price / self.tick_size) * self.tick_size

    # Cleanup

    def cleanup(self):
        """Stop trade thread and cleanup"""
        logger.info(f"\n{Colors.bold('Shutting down...')}")

        # Stop trade polling
        self.trade_thread_running = False
        if self.trade_thread:
            self.trade_thread.join(timeout=5)

        # Standard cleanup
        super().cleanup()


# CLI Helpers


def find_market_id(
    exchange: Exchange, slug: str, market_index: Optional[int] = None
) -> Optional[str]:
    """Find market ID by slug with optional selection"""
    logger.info(f"Searching for market: {slug}")

    markets: List[Market] = []

    # Try fetch_markets_by_slug if available (Polymarket)
    if hasattr(exchange, "fetch_markets_by_slug"):
        markets = exchange.fetch_markets_by_slug(slug)

    # Fallback: search through paginated markets
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
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="VPIN-based BBO Market Making Strategy",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # Market selection
    parser.add_argument(
        "-e",
        "--exchange",
        default=os.getenv("EXCHANGE", "polymarket"),
        help="Exchange name",
    )
    parser.add_argument(
        "-m",
        "--market-id",
        default=os.getenv("MARKET_ID", ""),
        help="Market ID to trade",
    )
    parser.add_argument(
        "-s",
        "--slug",
        default=os.getenv("MARKET_SLUG", ""),
        help="Market slug for search",
    )
    parser.add_argument(
        "--market",
        type=int,
        default=None,
        dest="market_index",
        help="Select specific market index from search results",
    )

    # Position and order sizing
    parser.add_argument(
        "--max-position",
        type=float,
        default=float(os.getenv("MAX_POSITION", "100")),
        help="Maximum position size per outcome",
    )
    parser.add_argument(
        "--order-size",
        type=float,
        default=float(os.getenv("ORDER_SIZE", "5")),
        help="Order size",
    )
    parser.add_argument(
        "--max-delta",
        type=float,
        default=float(os.getenv("MAX_DELTA", "20")),
        help="Maximum delta (position imbalance)",
    )

    # Timing
    parser.add_argument(
        "--interval",
        type=float,
        default=float(os.getenv("CHECK_INTERVAL", "5")),
        help="Check interval in seconds",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=None,
        help="Run duration in minutes (None = run indefinitely)",
    )

    # VPIN parameters (price-spread toxicity)
    parser.add_argument(
        "--alpha-fast",
        type=float,
        default=0.3,
        help="EMA decay for price velocity (fast component)",
    )
    parser.add_argument(
        "--alpha-slow",
        type=float,
        default=0.05,
        help="EMA decay for spread baseline (slow component)",
    )
    parser.add_argument(
        "--velocity-weight",
        type=float,
        default=0.7,
        help="Weight for price velocity in toxicity score",
    )
    parser.add_argument(
        "--spread-weight",
        type=float,
        default=0.3,
        help="Weight for spread pressure in toxicity score",
    )
    parser.add_argument(
        "--warmup-ticks",
        type=int,
        default=20,
        help="Number of ticks before VPIN is valid",
    )
    parser.add_argument(
        "--vpin-threshold",
        type=float,
        default=0.80,
        help="VPIN threshold for liquidity withdrawal",
    )
    parser.add_argument(
        "--resume-threshold",
        type=float,
        default=None,
        help="VPIN resume threshold (default: withdraw_threshold * 0.875)",
    )
    parser.add_argument(
        "--cooldown",
        type=float,
        default=60.0,
        help="Cooldown seconds after withdrawal before resuming",
    )

    # Trade polling (optional, for tick-rule fallback)
    parser.add_argument(
        "--enable-trade-polling",
        action="store_true",
        help="Enable trade polling (tick-rule fallback, not needed for orderbook metric)",
    )
    parser.add_argument(
        "--trade-poll-interval",
        type=float,
        default=2.0,
        help="Seconds between trade API polls (if enabled)",
    )

    return parser.parse_args()


def main() -> int:
    """Entry point for the VPIN BBO strategy"""
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

    # Find market_id from slug if needed
    market_id: Optional[str] = args.market_id
    if not market_id and args.slug:
        market_id = find_market_id(exchange, args.slug, args.market_index)
        if not market_id:
            return 1

    strategy = VPINBBOStrategy(
        exchange=exchange,
        market_id=market_id,
        max_position=args.max_position,
        order_size=args.order_size,
        max_delta=args.max_delta,
        check_interval=args.interval,
        alpha_fast=args.alpha_fast,
        alpha_slow=args.alpha_slow,
        velocity_weight=args.velocity_weight,
        spread_weight=args.spread_weight,
        warmup_ticks=args.warmup_ticks,
        vpin_threshold=args.vpin_threshold,
        resume_threshold=args.resume_threshold,
        cooldown_seconds=args.cooldown,
        trade_poll_interval=args.trade_poll_interval,
        enable_trade_polling=args.enable_trade_polling,
    )

    try:
        strategy.run(duration_minutes=args.duration)
    except KeyboardInterrupt:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
