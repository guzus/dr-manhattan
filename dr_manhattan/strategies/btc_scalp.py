"""
BTC 5-Minute Scalp Strategy

Places passive limit buy orders at entry_price on both YES and NO outcomes
of the rolling Polymarket BTC 5-minute Up/Down market. When one side fills,
places a sell at profit_target and cancels the other pending buy.

Phase 1 features:
- Auto-discovers the active BTC 5-min market window
- Rolls to next window automatically before expiry
- Both-sides arbitrage detection: buy both sides when combined cost < 0.97

Phase 2 features:
- Kelly Criterion position sizing based on running win rate
- EWMA momentum filter: skips entries during sustained price declines
- Order lifetime enforcement: cancels unfilled buys after order_lifetime seconds

Phase 3 features (dynamic profit rules):
- High-water mark trailing stop: tracks highest mid-price seen since fill
- Three-tier exit logic based on gain magnitude and time remaining:
    Tier 1 (<15% gain): hold at profit_target; near expiry lower to entry+0.01
    Tier 2 (15-100% gain): trail at 85-92% of high-water (time-interpolated)
    Tier 3 (>100% gain): trail at 88-94% of high-water
- Emergency exit: if price gaps below trailing floor, sell immediately at bid

Phase 4 features:
- Binance WebSocket price feed: real-time BTC/USDT from external source
- 100ms tick loop: reacts to price events ~50x faster than the default 5s loop
- Tiered state refresh: REST calls every 2s max; price data from WebSocket (in-memory)
- BTC-direction momentum filter: uses live Binance feed instead of Polymarket price history

Phase 5 features:
- Arb positions excluded from trailing stop management (ride to resolution)
- Win counting moved to sell fill completion, not buy fill (Kelly estimates now accurate)
- Both-sides arb detection runs every 100ms instead of every 2s
- Kelly b-ratio uses actual historical average exit price instead of fixed profit_target
- Daily loss limit: new entries paused when session P&L falls below -max_daily_loss

Fee structure (Polymarket, January 2026):
- Limit orders earn 0.20% maker rebate on both entry and exit legs
- Effective net profit per round trip is slightly above raw spread
"""

import json
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from ..base.strategy import Strategy
from ..feeds.binance import BinancePriceFeed
from ..models.market import Market, OutcomeToken
from ..models.order import OrderSide
from ..utils import setup_logger

logger = setup_logger(__name__)

# Minimum seconds remaining in a window to place new entry orders
MIN_WINDOW_FOR_ENTRY = 162  # cancel_before_expiry(90) + order_lifetime(72)

# Threshold for both-sides arbitrage detection
ARB_THRESHOLD = 0.97  # buy both when YES_ask + NO_ask < this

# Adaptive exit: Tier 1 fallback when <120s left and gain is small
ADAPTIVE_EXIT_SECS = 120

# Trailing stop thresholds
MOMENTUM_THRESHOLD = 0.15   # Tier 2 engages after 15% gain above entry
LARGE_GAIN_THRESHOLD = 1.00  # Tier 3 engages after 100% gain above entry

# Tier 2 trailing percentages (interpolated from early to late window)
TRAILING_STOP_EARLY = 0.85
TRAILING_STOP_LATE = 0.92

# Tier 3 trailing percentages
TRAILING_LARGE_EARLY = 0.88
TRAILING_LARGE_LATE = 0.94

# REST state refresh interval
STATE_REFRESH_INTERVAL = 2.0  # seconds


class BTCScalpStrategy(Strategy):
    """
    Passive limit-order scalp on the Polymarket BTC 5-minute Up/Down market.

    Buys both Up and Down at entry_price. When one side fills, places a sell
    at profit_target and cancels the other side. Trailing stop manages the exit.
    Kelly Criterion sizes each trade based on running win rate and actual exit prices.

    Parameters:
        entry_price: Limit buy price for both outcomes (default 0.32).
        profit_target: Initial sell price after fill (default 0.35).
        order_size_usd: USD to risk per side (default 10.0). Kelly scales this.
        order_lifetime: Seconds before cancelling unfilled buys (default 72).
        cancel_before_expiry: Cancel all orders this many seconds before close (default 90).
        max_daily_loss: Stop placing entries when session P&L falls below -this (default 50.0).

    Tick rate: 100ms. REST state refresh capped at once per 2s.
    """

    def __init__(
        self,
        exchange,
        market_id: str = "btc-5min-auto",
        entry_price: float = 0.32,
        profit_target: float = 0.35,
        order_size_usd: float = 10.0,
        order_lifetime: float = 72.0,
        cancel_before_expiry: float = 90.0,
        max_daily_loss: float = 50.0,
        **kwargs,
    ):
        base_keys = {"max_position", "order_size", "max_delta", "check_interval", "track_fills"}
        base_kwargs = {k: v for k, v in kwargs.items() if k in base_keys}
        base_kwargs.setdefault("check_interval", 0.1)
        super().__init__(exchange, market_id, **base_kwargs)

        if profit_target <= entry_price + 0.005:
            raise ValueError(
                f"profit_target ({profit_target}) must be > entry_price ({entry_price}) + 0.005"
            )

        self.entry_price = entry_price
        self.profit_target = profit_target
        self.order_size_usd = order_size_usd
        self.order_lifetime = order_lifetime
        self.cancel_before_expiry = cancel_before_expiry
        self.max_daily_loss = max_daily_loss

        # Per-window state
        self._buy_order_ids: Dict[str, str] = {}
        self._sell_order_ids: Dict[str, str] = {}
        self._orders_placed_at: Optional[float] = None
        self._window_reset: bool = False

        # Kelly Criterion state
        self._wins: int = 0
        self._losses: int = 0

        # Track actual exit prices for accurate Kelly b-ratio
        self._sum_sell_prices: float = 0.0
        self._n_exits: int = 0

        # Empirical loss tracking for Kelly b-ratio
        self._sum_loss_amounts: float = 0.0
        self._n_losses_with_amounts: int = 0

        self._state_path: str = os.environ.get("KELLY_STATE_PATH", "/data/kelly_state.json")
        self._load_kelly_state()

        # P&L tracking
        self._session_pnl: float = 0.0
        self._fill_contracts: Dict[str, float] = {}
        self._current_sell_prices: Dict[str, float] = {}

        # Arb positions ride to resolution
        self._arb_positions: set = set()

        # Fill rate tracking
        self._buys_placed: int = 0
        self._buys_filled: int = 0

        # Price history for momentum filter
        self._price_history: Dict[str, List[Tuple[float, float]]] = {}

        # Trailing stop
        self._high_water: Dict[str, float] = {}

        # Binance price feed
        self._price_feed: BinancePriceFeed = BinancePriceFeed()
        self._window_start_btc: Optional[float] = None
        self._last_state_refresh: float = 0.0

    # -------------------------------------------------------------------------
    # Setup
    # -------------------------------------------------------------------------

    def setup(self) -> bool:
        market = self._find_btc_5min_market()
        if not market:
            logger.error("No active BTC 5-min market found during setup")
            return False

        self.market = market
        self.market_id = market.id
        self.tick_size = market.tick_size

        token_ids = market.metadata.get("clobTokenIds", [])
        if not token_ids:
            logger.error("No clobTokenIds in market metadata")
            return False

        self.outcome_tokens = [
            OutcomeToken(market_id=self.market_id, outcome=outcome, token_id=token_id)
            for outcome, token_id in zip(market.outcomes, token_ids)
        ]

        token_ids = [ot.token_id for ot in self.outcome_tokens]
        self.client.setup_orderbook_websocket(self.market_id, token_ids)
        self._positions = self.client.fetch_positions_dict_for_market(self.market)

        self._price_feed.start()
        for _ in range(20):
            if self._price_feed.price is not None:
                break
            time.sleep(0.1)
        self._window_start_btc = self._price_feed.price
        if self._window_start_btc:
            logger.info(f"BTC window open price: ${self._window_start_btc:,.2f}")
        else:
            logger.warning("Binance feed not yet connected — momentum filter disabled until price arrives")

        self._log_trader_profile()
        self._log_market_info()
        logger.info(
            f"Strategy: entry={self.entry_price} target={self.profit_target} "
            f"size=${self.order_size_usd} lifetime={self.order_lifetime}s"
        )
        return True

    # -------------------------------------------------------------------------
    # Main loop
    # -------------------------------------------------------------------------

    def on_tick(self):
        now = time.time()
        secs = self._seconds_until_expiry()

        # Roll window before expiry
        if secs < self.cancel_before_expiry:
            if not self._window_reset:
                logger.info(f"Window expiring in {secs:.0f}s — rolling")
                self._reset_window()
                self._window_reset = True
            new_market = self._find_btc_5min_market()
            if new_market and new_market.id != self.market_id:
                self._switch_market(new_market)
            return

        # Arb check every 100ms
        if self._check_arb():
            return

        # Update EWMA from WebSocket orderbook
        for ot in self.outcome_tokens:
            bid, ask = self.get_best_bid_ask(ot.token_id)
            if bid and ask:
                self._update_price_history(ot.outcome, (bid + ask) / 2.0)

        # Slow path: REST calls capped at STATE_REFRESH_INTERVAL
        if now - self._last_state_refresh < STATE_REFRESH_INTERVAL:
            return

        self.refresh_state()
        self._last_state_refresh = now

        self._handle_fills(secs)

        if self._orders_placed_at and (now - self._orders_placed_at > self.order_lifetime):
            self._cancel_pending_buys()
            self._orders_placed_at = None

        no_open_positions = not any(self._positions.get(o.outcome, 0) > 0.5 for o in self.outcome_tokens)
        if (
            not self._buy_order_ids
            and not self._sell_order_ids
            and no_open_positions
            and secs > MIN_WINDOW_FOR_ENTRY
            and self._session_pnl > -self.max_daily_loss
        ):
            if self._session_pnl <= -self.max_daily_loss * 0.8:
                logger.warning(
                    f"Approaching daily loss limit: P&L ${self._session_pnl:.2f} / "
                    f"limit -${self.max_daily_loss:.2f}"
                )
            self._place_entry_orders()

        self._log_scalp_status(secs)

    # -------------------------------------------------------------------------
    # Market discovery
    # -------------------------------------------------------------------------

    def _find_btc_5min_market(self) -> Optional[Market]:
        now = datetime.now(timezone.utc)
        try:
            markets = self.exchange.search_markets(
                keywords=["BTC", "Up or Down"],
                closed=False,
                end_date_min=now,
                end_date_max=now + timedelta(minutes=6),
                min_liquidity=1.0,
            )
            if not markets:
                markets = self.exchange.search_markets(
                    query="Bitcoin Up or Down",
                    closed=False,
                    end_date_min=now,
                    end_date_max=now + timedelta(minutes=8),
                )
            if not markets:
                logger.warning("No BTC 5-min market found")
                return None
            with_close = [m for m in markets if m.close_time]
            return min(with_close, key=lambda m: m.close_time) if with_close else markets[0]
        except Exception as e:
            logger.warning(f"Market discovery error: {e}")
            return None

    def _switch_market(self, market: Market):
        self.market = market
        self.market_id = market.id
        self.tick_size = market.tick_size

        token_ids = market.metadata.get("clobTokenIds", [])
        self.outcome_tokens = [
            OutcomeToken(market_id=self.market_id, outcome=outcome, token_id=token_id)
            for outcome, token_id in zip(market.outcomes, token_ids)
        ]
        self._positions = self.client.fetch_positions_dict_for_market(self.market)
        token_ids = [ot.token_id for ot in self.outcome_tokens]
        self.client.setup_orderbook_websocket(self.market_id, token_ids)
        self._price_history.clear()
        self._price_ewma.clear()
        self._arb_positions.clear()
        self._fill_contracts.clear()
        self._current_sell_prices.clear()
        self._window_reset = False
        self._window_start_btc = self._price_feed.price
        if self._window_start_btc:
            logger.info(f"New window: {market.question[:60]} | BTC ${self._window_start_btc:,.2f}")
        else:
            logger.info(f"New window: {market.question[:70]}")

    # -------------------------------------------------------------------------
    # Kelly Criterion sizing + persistence
    # -------------------------------------------------------------------------

    def _load_kelly_state(self):
        try:
            with open(self._state_path) as f:
                data = json.load(f)
            self._wins = int(data.get("wins", 0))
            self._losses = int(data.get("losses", 0))
            self._sum_sell_prices = float(data.get("sum_sell_prices", 0.0))
            self._n_exits = int(data.get("n_exits", 0))
            self._sum_loss_amounts = float(data.get("sum_loss_amounts", 0.0))
            self._n_losses_with_amounts = int(data.get("n_losses_with_amounts", 0))
            self._buys_placed = int(data.get("buys_placed", 0))
            self._buys_filled = int(data.get("buys_filled", 0))
            avg = f"{self._sum_sell_prices / self._n_exits:.4f}" if self._n_exits > 0 else "n/a"
            avg_loss = f"{self._sum_loss_amounts / self._n_losses_with_amounts:.4f}" if self._n_losses_with_amounts > 0 else "n/a"
            logger.info(
                f"Kelly state loaded: W/L={self._wins}/{self._losses} "
                f"exits={self._n_exits} avg_exit={avg} avg_loss={avg_loss} "
                f"fills={self._buys_filled}/{self._buys_placed}"
            )
        except FileNotFoundError:
            logger.info("No Kelly state file found — starting fresh")
        except Exception as e:
            logger.warning(f"Could not load Kelly state: {e} — starting fresh")

    def _save_kelly_state(self):
        data = {
            "wins": self._wins,
            "losses": self._losses,
            "sum_sell_prices": self._sum_sell_prices,
            "n_exits": self._n_exits,
            "sum_loss_amounts": self._sum_loss_amounts,
            "n_losses_with_amounts": self._n_losses_with_amounts,
            "buys_placed": self._buys_placed,
            "buys_filled": self._buys_filled,
        }
        tmp = self._state_path + ".tmp"
        try:
            os.makedirs(os.path.dirname(self._state_path) or ".", exist_ok=True)
            with open(tmp, "w") as f:
                json.dump(data, f)
            os.replace(tmp, self._state_path)
        except Exception as e:
            logger.warning(f"Could not save Kelly state: {e}")

    def _kelly_size(self) -> float:
        """
        f* = p - (1-p)/b
        where p = Bayesian win rate (6 pseudo-wins, 4 pseudo-losses prior),
        b = win_amount / avg_loss (empirical once >= 5 losses observed).

        Defaults: avg_exit = profit_target, avg_loss = entry_price (full loss).
        Returns a fraction of order_size_usd, clamped to 10-100%.
        """
        p = (self._wins + 6) / (self._wins + self._losses + 10)
        avg_exit = self._sum_sell_prices / self._n_exits if self._n_exits >= 5 else self.profit_target
        avg_loss = self._sum_loss_amounts / self._n_losses_with_amounts if self._n_losses_with_amounts >= 5 else self.entry_price
        win_amount = avg_exit - self.entry_price
        b = win_amount / avg_loss
        f = p - (1.0 - p) / b
        if f < 0:
            logger.warning(f"Kelly f*={f:.3f} (negative edge): p={p:.2f} b={b:.3f} — sizing at floor 10%")
        f = max(0.10, min(f, 1.0))
        return round(self.order_size_usd * f, 2)

    # -------------------------------------------------------------------------
    # Dynamic sell target (trailing stop)
    # -------------------------------------------------------------------------

    def _dynamic_sell_target(self, outcome: str, current_mid: float, secs_remaining: float) -> float:
        """
        Tier 1 (gain < 15%): flat profit_target; drop to entry+0.01 near expiry.
        Tier 2 (15-100%): trail at 85-92% of high-water.
        Tier 3 (>100%): trail at 88-94% of high-water.
        """
        gain = (current_mid - self.entry_price) / self.entry_price
        high_water = self._high_water.get(outcome, current_mid)
        urgency = max(0.0, min(1.0, 1.0 - secs_remaining / 300.0))

        if gain < MOMENTUM_THRESHOLD:
            if secs_remaining < ADAPTIVE_EXIT_SECS:
                return self.round_price(self.entry_price + 0.01)
            return self.profit_target
        elif gain < LARGE_GAIN_THRESHOLD:
            pct = TRAILING_STOP_EARLY + (TRAILING_STOP_LATE - TRAILING_STOP_EARLY) * urgency
            return max(self.profit_target, self.round_price(high_water * pct))
        else:
            pct = TRAILING_LARGE_EARLY + (TRAILING_LARGE_LATE - TRAILING_LARGE_EARLY) * urgency
            return max(self.profit_target, self.round_price(high_water * pct))

    # -------------------------------------------------------------------------
    # EWMA momentum filter
    # -------------------------------------------------------------------------

    def _update_price_history(self, outcome: str, mid: float):
        history = self._price_history.setdefault(outcome, [])
        history.append((time.time(), mid))
        if len(history) > 60:
            history.pop(0)

    def _is_momentum_favorable(self, outcome: str) -> bool:
        """
        Return False if BTC is trending strongly against buying this outcome.

        Primary signal: Binance BTC direction vs. window open.
        Fallback: 3+ consecutive declining ticks in Polymarket price history.
        """
        current_btc = self._price_feed.price
        if current_btc is not None and self._window_start_btc is not None:
            pct = (current_btc - self._window_start_btc) / self._window_start_btc
            if outcome in ("Yes", "UP") and pct < -0.003:
                logger.info(f"Skipping {outcome}: BTC down {pct:.3%}, falling knife risk")
                return False
            if outcome in ("No", "DOWN") and pct > 0.003:
                logger.info(f"Skipping {outcome}: BTC up {pct:.3%}, falling knife risk")
                return False

        history = self._price_history.get(outcome, [])
        if len(history) >= 4:
            recent = [p for _, p in history[-4:]]
            consecutive_falls = sum(1 for i in range(len(recent) - 1) if recent[i + 1] < recent[i])
            if consecutive_falls >= 3:
                logger.info(f"Skipping {outcome}: {consecutive_falls} consecutive declining ticks")
                return False
        return True

    # -------------------------------------------------------------------------
    # Arbitrage
    # -------------------------------------------------------------------------

    def _check_arb(self) -> bool:
        """Buy both outcomes immediately when combined ask < ARB_THRESHOLD."""
        if len(self.outcome_tokens) < 2:
            return False

        asks: Dict[str, float] = {}
        for ot in self.outcome_tokens:
            _, ask = self.get_best_bid_ask(ot.token_id)
            if ask is None:
                return False
            asks[ot.outcome] = ask

        total = sum(asks.values())
        if total >= ARB_THRESHOLD:
            return False

        logger.info(f"Arb: {asks} total={total:.4f} < {ARB_THRESHOLD}")
        contracts = max(1, round(self.order_size_usd / total))
        for ot in self.outcome_tokens:
            try:
                self.create_order(ot.outcome, OrderSide.BUY, asks[ot.outcome], contracts, ot.token_id)
                self._arb_positions.add(ot.outcome)
                logger.info(f"Arb buy: {ot.outcome} @ {asks[ot.outcome]:.4f} x{contracts}")
            except Exception as e:
                logger.warning(f"Arb buy failed ({ot.outcome}): {e}")
        return True

    # -------------------------------------------------------------------------
    # Entry orders
    # -------------------------------------------------------------------------

    def _place_entry_orders(self):
        kelly_usd = self._kelly_size()
        contracts = max(1, round(kelly_usd / self.entry_price))
        self._orders_placed_at = time.time()

        for ot in self.outcome_tokens:
            _, ask = self.get_best_bid_ask(ot.token_id)

            # Skip if ask is well above entry — unlikely to fill
            if ask is not None and ask > self.entry_price + 0.05:
                continue

            if not self._is_momentum_favorable(ot.outcome):
                continue

            try:
                order = self.create_order(ot.outcome, OrderSide.BUY, self.entry_price, contracts, ot.token_id)
                self._buy_order_ids[ot.outcome] = order.id
                self._buys_placed += 1
                self.log_order(OrderSide.BUY, contracts, ot.outcome, self.entry_price)
            except Exception as e:
                logger.warning(f"Buy order failed ({ot.outcome}): {e}")

    # -------------------------------------------------------------------------
    # Fill management
    # -------------------------------------------------------------------------

    def _handle_fills(self, secs_remaining: float):
        open_order_ids = {o.id for o in self._open_orders}

        # Clean up completed sell orders
        for outcome in list(self._sell_order_ids.keys()):
            if self._sell_order_ids[outcome] not in open_order_ids:
                if self._positions.get(outcome, 0.0) < 0.5:
                    sell_price = self._current_sell_prices.get(outcome, self.profit_target)
                    contracts = self._fill_contracts.get(outcome, 0.0)
                    pnl = (sell_price - self.entry_price) * contracts
                    self._session_pnl += pnl
                    self._sum_sell_prices += sell_price
                    self._n_exits += 1
                    self._wins += 1
                    self._save_kelly_state()
                    logger.info(
                        f"Sell filled: {outcome} @ {sell_price:.4f} "
                        f"(P&L: ${pnl:+.2f}, session: ${self._session_pnl:+.2f})"
                    )
                    del self._sell_order_ids[outcome]
                    self._high_water.pop(outcome, None)
                    self._fill_contracts.pop(outcome, None)
                    self._current_sell_prices.pop(outcome, None)

        for ot in self.outcome_tokens:
            pos = self._positions.get(ot.outcome, 0.0)
            if pos < 0.5:
                continue
            if ot.outcome in self._arb_positions:
                continue

            bid, ask = self.get_best_bid_ask(ot.token_id)
            current_mid = (bid + ask) / 2.0 if bid and ask else None

            if ot.outcome in self._sell_order_ids:
                if current_mid is None:
                    continue

                self._high_water[ot.outcome] = max(
                    self._high_water.get(ot.outcome, current_mid), current_mid
                )
                dynamic_target = self._dynamic_sell_target(ot.outcome, current_mid, secs_remaining)

                _, sell_orders = self.get_orders_for_outcome(ot.outcome)
                active_sells = [o for o in sell_orders if o.id in open_order_ids]

                for sell_order in active_sells:
                    if abs(sell_order.price - dynamic_target) <= self.tick_size:
                        continue

                    try:
                        self.client.cancel_order(sell_order.id)

                        if bid is not None and bid < dynamic_target - self.tick_size:
                            exit_price = bid
                            logger.info(
                                f"Emergency exit: {ot.outcome} gapped to {bid:.4f} "
                                f"(floor was {dynamic_target:.4f})"
                            )
                        else:
                            exit_price = dynamic_target
                            logger.info(
                                f"Trailing: {ot.outcome} "
                                f"{sell_order.price:.4f} → {exit_price:.4f} "
                                f"(HWM={self._high_water[ot.outcome]:.4f})"
                            )

                        new_order = self.create_order(
                            ot.outcome, OrderSide.SELL, exit_price, pos, ot.token_id
                        )
                        self._sell_order_ids[ot.outcome] = new_order.id
                        self._current_sell_prices[ot.outcome] = exit_price
                    except Exception as e:
                        logger.warning(f"Sell update failed ({ot.outcome}): {e}")
                continue

            # First fill detection
            is_first_detection = ot.outcome not in self._fill_contracts
            if is_first_detection:
                self._high_water[ot.outcome] = current_mid if current_mid else self.entry_price
                self._fill_contracts[ot.outcome] = pos
                self._buys_filled += 1
                logger.info(
                    f"Fill: {ot.outcome} {pos:.0f}c — placing sell "
                    f"(mid={self._high_water[ot.outcome]:.4f})"
                )
                for other in self.outcome_tokens:
                    if other.outcome != ot.outcome and other.outcome in self._buy_order_ids:
                        try:
                            self.client.cancel_order(self._buy_order_ids[other.outcome])
                            del self._buy_order_ids[other.outcome]
                            logger.info(f"Cancelled opposite buy: {other.outcome}")
                        except Exception as e:
                            logger.warning(f"Cancel opposite buy failed ({other.outcome}): {e}")
                self._buy_order_ids.pop(ot.outcome, None)

            initial_target = self._dynamic_sell_target(
                ot.outcome, self._high_water[ot.outcome], secs_remaining
            )

            try:
                sell_order = self.create_order(
                    ot.outcome, OrderSide.SELL, initial_target, pos, ot.token_id
                )
                self._sell_order_ids[ot.outcome] = sell_order.id
                self._current_sell_prices[ot.outcome] = initial_target
                self.log_order(OrderSide.SELL, pos, ot.outcome, initial_target)
            except Exception as e:
                logger.warning(f"Sell order failed ({ot.outcome}): {e}")

    # -------------------------------------------------------------------------
    # Window management
    # -------------------------------------------------------------------------

    def _cancel_pending_buys(self):
        for outcome, order_id in list(self._buy_order_ids.items()):
            try:
                self.client.cancel_order(order_id)
                logger.info(f"Lifetime expired: cancelled buy {outcome}")
            except Exception as e:
                logger.warning(f"Cancel failed ({outcome}): {e}")
        self._buy_order_ids.clear()

    def _reset_window(self):
        for outcome in list(self._sell_order_ids.keys()):
            contracts = self._fill_contracts.get(outcome, 0.0)
            if contracts > 0:
                loss = self.entry_price * contracts
                self._session_pnl -= loss
                self._sum_loss_amounts += self.entry_price
                self._n_losses_with_amounts += 1
            self._losses += 1
            self._save_kelly_state()
        self.cancel_all_orders()
        self._buy_order_ids.clear()
        self._sell_order_ids.clear()
        self._arb_positions.clear()
        self._orders_placed_at = None
        self._high_water.clear()
        self._fill_contracts.clear()
        self._current_sell_prices.clear()

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def cleanup(self):
        self._price_feed.stop()
        super().cleanup()

    def refresh_state(self):
        self._positions = self.client.fetch_positions_dict_for_market(self.market)
        self._open_orders = self.client.fetch_open_orders(market_id=self.market_id)

    def _seconds_until_expiry(self) -> float:
        if not self.market or not self.market.close_time:
            return float("inf")
        close_time = self.market.close_time
        if close_time.tzinfo is None:
            close_time = close_time.replace(tzinfo=timezone.utc)
        return max(0.0, (close_time - datetime.now(timezone.utc)).total_seconds())

    def _log_scalp_status(self, secs_remaining: float):
        total = self._wins + self._losses
        win_rate = f"{self._wins / total:.0%}" if total > 0 else "N/A"
        kelly_usd = self._kelly_size()

        btc_str = ""
        current_btc = self._price_feed.price
        if current_btc and self._window_start_btc:
            pct = (current_btc - self._window_start_btc) / self._window_start_btc
            btc_str = f" | BTC ${current_btc:,.0f} ({pct:+.3%})"
        elif current_btc:
            btc_str = f" | BTC ${current_btc:,.0f}"

        fill_rate = f"{self._buys_filled}/{self._buys_placed}" if self._buys_placed else "0/0"
        logger.info(
            f"  [Scalp] W/L: {self._wins}/{self._losses} ({win_rate}) | "
            f"P&L: ${self._session_pnl:+.2f} | "
            f"Kelly: ${kelly_usd:.2f} | "
            f"Fills: {fill_rate} | "
            f"Window: {secs_remaining:.0f}s | "
            f"Buys: {len(self._buy_order_ids)} | "
            f"Sells: {len(self._sell_order_ids)}"
            f"{btc_str}"
        )
