"""
Hybrid Market Making Example with Endgame Sweep Mode

Extends a standard BBO-join spread market maker with an endgame "sweep" mode.
When an endgame signal is detected:
  - Cancel all outstanding MM quotes
  - Only BUY the most likely winning outcome within a tight entry range
  - Hold to settlement to capture the last few basis points

Endgame signal:
  (1) If an end/settle timestamp can be inferred:
        time_to_settle <= ENDGAME_TIME_HOURS
  (2) Otherwise use a price/spread proxy on YES:
        mid >= ENDGAME_PRICE_TRIGGER AND spread <= ENDGAME_SPREAD_MAX

Safety:
  - Sweep mode uses a position cap (fraction of max_position)
  - Sweep only triggers in a narrow "endgame price" band (e.g. 0.997-0.999)

Modes:
  - live: place/cancel orders
  - test: log decisions without sending orders

Usage:
    uv run python examples/endgame_sweep_strategy.py MARKET_SLUG --mode=live
    uv run python examples/endgame_sweep_strategy.py MARKET_SLUG --mode=test
"""

import os
import sys
import time
import asyncio
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone
from dotenv import load_dotenv

import dr_manhattan
from dr_manhattan.models import OrderSide
from dr_manhattan.utils import setup_logger
from dr_manhattan.utils.logger import Colors

logger = setup_logger(__name__)


class EndgameSweepMarketMaker:
    """
    Two-mode hybrid strategy:

    NORMAL mode:
      - Join BBO on both sides for each outcome (spread-style market making)
      - Basic delta management across outcomes

    SWEEP mode:
      - Cancel all outstanding quotes
      - Select the most likely winning outcome (simple mid-price heuristic)
      - Only BUY in a tight endgame band and hold until settlement

    Binary market optimization:
      - Subscribe to YES orderbook only
      - Infer NO best bid/ask by (1 - YES best ask/bid)
    """

    # Strategy Thresholds (Sample Values)

    ENDGAME_TIME_HOURS = 3.0
    ENDGAME_PRICE_TRIGGER = 0.97
    ENDGAME_SPREAD_MAX = 0.003

    SWEEP_MIN_ENTRY = 0.997
    SWEEP_MAX_ENTRY = 0.999

    SWEEP_MAX_POSITION_FRACTION = 0.5  # Cap sweep exposure as a fraction of max_position

    def __init__(
        self,
        exchange: dr_manhattan.Polymarket,
        market_slug: str,
        max_position: float = 100.0,
        order_size: float = 5.0,
        max_delta: float = 20.0,
        check_interval: float = 5.0,
        mode: str = "live",  # "live" or "test"
    ):
        self.exchange = exchange
        self.market_slug = market_slug
        self.max_position = max_position
        self.order_size = order_size
        self.max_delta = max_delta
        self.check_interval = check_interval

        # Market state
        self.market = None
        self.token_ids: List[str] = []
        self.outcomes: List[str] = []
        self.tick_size: float = 0.01

        # WebSocket / orderbook state
        self.ws = None
        self.orderbook_manager = None
        self.ws_thread = None
        self.is_running = False

        # Mode state
        self.mode = "NORMAL"  # NORMAL or SWEEP
        self.sweep_side_outcome = None  # Selected outcome name
        self.live_mode = mode.lower() == "live"

    # Market Fetch / WebSocket

    def fetch_market(self) -> bool:
        """Fetch market metadata and infer token IDs / tick size."""
        logger.info(f"Fetching market: {self.market_slug}")
        self.market = self.exchange.fetch_market_by_slug(self.market_slug)
        if not self.market:
            logger.error(f"Failed to fetch market: {self.market_slug}")
            return False

        self.token_ids = self.market.metadata.get("clobTokenIds", [])
        self.outcomes = self.market.outcomes

        if not self.token_ids:
            logger.error("No token IDs found in market metadata")
            return False

        self.tick_size = self.exchange.get_tick_size(self.market)

        # Infer finer tick size if needed (heuristic)
        for outcome, price in self.market.prices.items():
            if price > 0:
                price_str = f"{price:.4f}"
                if "." in price_str:
                    decimals = len(price_str.split(".")[1].rstrip("0"))
                    if decimals == 3:
                        self.tick_size = 0.001
                        break

        logger.info(f"\n{Colors.bold('Market:')} {Colors.cyan(self.market.question)}")
        logger.info(
            f"Outcomes: {Colors.magenta(str(self.outcomes))} | "
            f"Tick: {Colors.yellow(str(self.tick_size))} | "
            f"Vol: {Colors.cyan(f'${self.market.volume:,.0f}')}"
        )

        for i, (outcome, _token_id) in enumerate(zip(self.outcomes, self.token_ids)):
            price = self.market.prices.get(outcome, 0)
            logger.info(f"  [{i}] {Colors.magenta(outcome)}: {Colors.yellow(f'{price:.4f}')}")

        slug = self.market.metadata.get("slug", "")
        if slug:
            logger.info(f"URL: {Colors.gray(f'https://polymarket.com/event/{slug}')}")

        return True

    def setup_websocket(self):
        """Initialize WebSocket client and orderbook manager."""
        self.ws = self.exchange.get_websocket()
        self.orderbook_manager = self.ws.get_orderbook_manager()

    def start_websocket(self):
        """
        Start WebSocket loop and subscribe to orderbooks.
        For binary markets, subscribe only to the YES token for efficiency.
        """
        tokens_to_subscribe = [self.token_ids[0]] if len(self.token_ids) == 2 else self.token_ids
        logger.info(
            f"Starting WebSocket (subscribing to {len(tokens_to_subscribe)}/{len(self.token_ids)} tokens)..."
        )

        if self.ws.loop is None:
            self.ws.loop = asyncio.new_event_loop()

        async def subscribe_all():
            await self.ws.connect()
            await self.ws.watch_orderbook_by_market(self.market.id, tokens_to_subscribe)
            await self.ws._receive_loop()

        import threading

        def run_loop():
            asyncio.set_event_loop(self.ws.loop)
            self.ws.loop.run_until_complete(subscribe_all())

        self.ws_thread = threading.Thread(target=run_loop, daemon=True)
        self.ws_thread.start()

        time.sleep(2)

    def stop_websocket(self):
        """Stop WebSocket and join background thread."""
        if self.ws:
            self.ws.stop()
            if self.ws_thread:
                self.ws_thread.join(timeout=5)

    # Account / Orders Helpers

    def get_positions(self) -> Dict[str, float]:
        """Fetch current position sizes per outcome (best-effort)."""
        positions = {}
        try:
            positions_list = self.exchange.fetch_positions_for_market(self.market)
            for pos in positions_list:
                positions[pos.outcome] = pos.size
        except Exception as e:
            logger.warning(f"Failed to fetch positions: {e}")
        return positions

    def get_open_orders(self) -> List:
        """Fetch open orders for this market (best-effort)."""
        try:
            condition_id = self.market.metadata.get("conditionId", self.market.id)
            return self.exchange.fetch_open_orders(market_id=condition_id)
        except Exception as e:
            logger.warning(f"Failed to fetch open orders: {e}")
            return []

    def cancel_all_orders(self):
        """Cancel all open orders for this market."""
        orders = self.get_open_orders()
        if not orders:
            return

        logger.info(f"Cancelling {Colors.cyan(str(len(orders)))} orders...")
        for order in orders:
            try:
                if self.live_mode:
                    self.exchange.cancel_order(order.id, market_id=self.market.id)
                else:
                    logger.info(
                        f"  (test) {Colors.gray('✕ Cancel')} {order.id} "
                        f"{order.outcome} {order.side.value.upper()} @ {order.price}"
                    )
            except Exception as e:
                logger.warning(f"  Failed to cancel {order.id}: {e}")

    # Pricing / Orderbook Helpers

    def best_bid_ask_for_outcome(self, i: int) -> Tuple[Optional[float], Optional[float]]:
        """
        Return best bid/ask for outcome index i.

        Binary optimization:
          - YES uses subscribed orderbook directly
          - NO is inferred from YES:
              NO_bid = 1 - YES_ask
              NO_ask = 1 - YES_bid
        """
        if len(self.token_ids) == 2 and i == 1:
            first_bid, first_ask = self.orderbook_manager.get_best_bid_ask(self.token_ids[0])
            if first_bid is None or first_ask is None:
                return None, None
            best_bid = 1.0 - first_ask
            best_ask = 1.0 - first_bid
            return best_bid, best_ask

        best_bid, best_ask = self.orderbook_manager.get_best_bid_ask(self.token_ids[i])
        return best_bid, best_ask

    def round_price(self, p: float) -> float:
        """Round to tick size and clamp to [0.01, 0.99]."""
        p = self.exchange.round_to_tick_size(p, self.tick_size)
        return max(0.01, min(0.99, p))

    # Endgame Detection Logic

    def infer_time_to_settle_seconds(self) -> Optional[float]:
        """
        Try to infer an end/settle timestamp from market metadata.
        Returns seconds to end if found, otherwise None.
        """
        md = getattr(self.market, "metadata", {}) or {}
        if not isinstance(md, dict):
            return None

        candidate_keys = [
            "endDate", "end_date", "endTime", "end_time",
            "closeTime", "close_time",
            "resolveTime", "resolve_time",
            "resolutionTime", "resolution_time",
            "expiration", "expiry", "expiresAt", "expires_at",
        ]

        ts = None
        for k in candidate_keys:
            v = md.get(k)
            if v:
                ts = v
                break

        if ts is None:
            for attr in ["end_date", "endTime", "close_time", "resolve_time", "resolution_time"]:
                v = getattr(self.market, attr, None)
                if v:
                    ts = v
                    break

        if ts is None:
            return None

        try:
            if isinstance(ts, (int, float)):
                # Heuristic: treat large numbers as ms timestamps
                if ts > 10_000_000_000:
                    end_dt = datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc)
                else:
                    end_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            elif isinstance(ts, str):
                # ISO8601-ish timestamps (allow trailing Z)
                s = ts.replace("Z", "+00:00")
                end_dt = datetime.fromisoformat(s)
                if end_dt.tzinfo is None:
                    end_dt = end_dt.replace(tzinfo=timezone.utc)
            else:
                return None

            now = datetime.now(timezone.utc)
            return (end_dt - now).total_seconds()
        except Exception:
            return None

    def endgame_signal(self) -> bool:
        """
        Decide whether to switch into sweep mode.

        Priority:
          1) Time-based trigger if end time is known
          2) Otherwise a price/spread proxy on the YES outcome
        """
        tts = self.infer_time_to_settle_seconds()
        if tts is not None and tts <= self.ENDGAME_TIME_HOURS * 3600:
            return True

        yes_bid, yes_ask = self.best_bid_ask_for_outcome(0)
        if yes_bid is None or yes_ask is None:
            return False

        mid = (yes_bid + yes_ask) / 2.0
        spr = max(0.0, yes_ask - yes_bid)

        return (mid >= self.ENDGAME_PRICE_TRIGGER) and (spr <= self.ENDGAME_SPREAD_MAX)

    def pick_sweep_outcome(self) -> str:
        """
        Select the sweep target outcome.

        Current heuristic:
          - Choose the outcome with the highest mid price.
        """
        mids = []
        for i, outcome in enumerate(self.outcomes):
            bid, ask = self.best_bid_ask_for_outcome(i)
            if bid is None or ask is None:
                mids.append((outcome, -1.0))
                continue
            mids.append((outcome, (bid + ask) / 2.0))

        mids.sort(key=lambda x: x[1], reverse=True)
        return mids[0][0] if mids else self.outcomes[0]

    # NORMAL Mode: BBO Join MM

    def place_orders_normal(self):
        """Place/maintain BBO-join quotes on both sides, with simple delta control."""
        positions = self.get_positions()
        open_orders = self.get_open_orders()

        max_position_size = max(positions.values()) if positions else 0
        min_position_size = min(positions.values()) if positions else 0
        delta = max_position_size - min_position_size

        logger.info(
            f"\n[{time.strftime('%H:%M:%S')}] Mode: {Colors.cyan('NORMAL')} | "
            f"Delta: {Colors.yellow(f'{delta:.1f}')} | "
            f"Orders: {Colors.cyan(str(len(open_orders)))}"
        )

        for i, (outcome, token_id) in enumerate(zip(self.outcomes, self.token_ids)):
            bid, ask = self.best_bid_ask_for_outcome(i)
            if bid is None or ask is None:
                logger.warning(f"  {outcome}: No orderbook data, skipping...")
                continue

            our_bid = self.round_price(bid)
            our_ask = self.round_price(ask)

            if our_bid >= our_ask:
                logger.warning(f"  {outcome}: Spread too tight (bid>=ask), skipping")
                continue

            position_size = positions.get(outcome, 0)

            outcome_orders = [o for o in open_orders if o.outcome == outcome]
            buy_orders = [o for o in outcome_orders if o.side == OrderSide.BUY]
            sell_orders = [o for o in outcome_orders if o.side == OrderSide.SELL]

            # Delta management: avoid adding exposure to the largest inventory outcome
            if delta > self.max_delta and position_size == max_position_size:
                logger.info(f"    {outcome}: Skip (delta mgmt)")
                continue

            # BUY: maintain a single best-bid-join order
            should_buy = True
            if buy_orders:
                for o in buy_orders:
                    if abs(o.price - our_bid) < 0.001:
                        should_buy = False
                        break
                if should_buy:
                    for o in buy_orders:
                        try:
                            if self.live_mode:
                                self.exchange.cancel_order(o.id)
                                logger.info(
                                    f"    {Colors.gray('✕ Cancel')} {Colors.green('BUY')} @ {Colors.yellow(f'{o.price:.4f}')}"
                                )
                            else:
                                logger.info(
                                    f"    (test) {Colors.gray('✕ Cancel')} {Colors.green('BUY')} @ {Colors.yellow(f'{o.price:.4f}')}"
                                )
                        except Exception:
                            pass

            if position_size + self.order_size > self.max_position:
                should_buy = False

            if should_buy:
                if self.live_mode:
                    try:
                        self.exchange.create_order(
                            market_id=self.market.id,
                            outcome=outcome,
                            side=OrderSide.BUY,
                            price=our_bid,
                            size=self.order_size,
                            params={"token_id": token_id},
                        )
                        logger.info(
                            f"    {Colors.gray('→')} {Colors.green('BUY')} {self.order_size:.0f} "
                            f"{Colors.magenta(outcome)} @ {Colors.yellow(f'{our_bid:.4f}')}"
                        )
                    except Exception as e:
                        logger.error(f"    BUY failed: {e}")
                else:
                    logger.info(
                        f"    (test) {Colors.green('BUY')} {self.order_size:.0f} "
                        f"{Colors.magenta(outcome)} @ {Colors.yellow(f'{our_bid:.4f}')}"
                    )

            # SELL: maintain a single best-ask-join order
            should_sell = True
            if sell_orders:
                for o in sell_orders:
                    if abs(o.price - our_ask) < 0.001:
                        should_sell = False
                        break
                if should_sell:
                    for o in sell_orders:
                        try:
                            if self.live_mode:
                                self.exchange.cancel_order(o.id)
                                logger.info(
                                    f"    {Colors.gray('✕ Cancel')} {Colors.red('SELL')} @ {Colors.yellow(f'{o.price:.4f}')}"
                                )
                            else:
                                logger.info(
                                    f"    (test) {Colors.gray('✕ Cancel')} {Colors.red('SELL')} @ {Colors.yellow(f'{o.price:.4f}')}"
                                )
                        except Exception:
                            pass

            if position_size < self.order_size:
                should_sell = False

            if should_sell:
                if self.live_mode:
                    try:
                        self.exchange.create_order(
                            market_id=self.market.id,
                            outcome=outcome,
                            side=OrderSide.SELL,
                            price=our_ask,
                            size=self.order_size,
                            params={"token_id": token_id},
                        )
                        logger.info(
                            f"    {Colors.gray('→')} {Colors.red('SELL')} {self.order_size:.0f} "
                            f"{Colors.magenta(outcome)} @ {Colors.yellow(f'{our_ask:.4f}')}"
                        )
                    except Exception as e:
                        logger.error(f"    SELL failed: {e}")
                else:
                    logger.info(
                        f"    (test) {Colors.red('SELL')} {self.order_size:.0f} "
                        f"{Colors.magenta(outcome)} @ {Colors.yellow(f'{our_ask:.4f}')}"
                    )

    # SWEEP Mode: Endgame Buying

    def place_orders_sweep(self):
        """
        Endgame sweep behavior:
          - Only BUY the selected outcome
          - Require ask to be within the endgame entry band
          - Respect a sweep position cap
        """
        positions = self.get_positions()
        open_orders = self.get_open_orders()

        sweep_outcome = self.sweep_side_outcome or (self.outcomes[0] if self.outcomes else None)
        if sweep_outcome is None:
            return

        try:
            idx = self.outcomes.index(sweep_outcome)
        except ValueError:
            idx = 0
            sweep_outcome = self.outcomes[0]

        bid, ask = self.best_bid_ask_for_outcome(idx)
        if bid is None or ask is None:
            logger.warning("SWEEP: missing orderbook data")
            return

        ask = float(ask)
        bid = float(bid)
        mid = (bid + ask) / 2.0
        spr = ask - bid

        logger.info(
            f"\n[{time.strftime('%H:%M:%S')}] Mode: {Colors.magenta('SWEEP')} | "
            f"Target: {Colors.magenta(sweep_outcome)} | mid={mid:.4f} spr={spr:.4f} | "
            f"Orders: {Colors.cyan(str(len(open_orders)))}"
        )

        sweep_max_pos = self.max_position * self.SWEEP_MAX_POSITION_FRACTION
        pos = positions.get(sweep_outcome, 0.0)

        if pos >= sweep_max_pos:
            logger.info(f"  SWEEP: position cap reached ({pos:.1f} >= {sweep_max_pos:.1f})")
            return

        # Only sweep when price is truly in the endgame band
        if ask < self.SWEEP_MIN_ENTRY:
            logger.info(
                f"  SWEEP: ask {ask:.4f} < SWEEP_MIN_ENTRY {self.SWEEP_MIN_ENTRY:.4f} "
                f"(not endgame-priced yet)"
            )
            return

        max_entry = min(self.SWEEP_MAX_ENTRY, ask)
        max_entry = self.round_price(max_entry)

        if max_entry > self.SWEEP_MAX_ENTRY:
            logger.info(
                f"  SWEEP: max_entry {max_entry:.4f} > SWEEP_MAX_ENTRY {self.SWEEP_MAX_ENTRY:.4f}, skip"
            )
            return

        size = min(self.order_size, max(0.0, sweep_max_pos - pos))
        if size <= 0:
            return

        if self.live_mode:
            try:
                self.exchange.create_order(
                    market_id=self.market.id,
                    outcome=sweep_outcome,
                    side=OrderSide.BUY,
                    price=max_entry,
                    size=size,
                    params={"token_id": self.token_ids[idx]},
                )
                logger.info(
                    f"    {Colors.gray('→')} {Colors.green('SWEEP BUY')} {size:.0f} "
                    f"{Colors.magenta(sweep_outcome)} @ {Colors.yellow(f'{max_entry:.4f}')}"
                )
            except Exception as e:
                logger.error(f"    SWEEP BUY failed: {e}")
        else:
            logger.info(
                f"    (test) {Colors.green('SWEEP BUY')} {size:.0f} "
                f"{Colors.magenta(sweep_outcome)} @ {Colors.yellow(f'{max_entry:.4f}')}"
            )

    # Mode Switching

    def maybe_switch_mode(self):
        """
        Switch from NORMAL to SWEEP when the endgame signal triggers.
        (No automatic revert to NORMAL in this example.)
        """
        if self.mode == "NORMAL" and self.endgame_signal():
            self.mode = "SWEEP"
            self.sweep_side_outcome = self.pick_sweep_outcome()

            logger.warning(
                f"\n{Colors.bold('*** MODE SWITCH ***')} {Colors.cyan('NORMAL')} → {Colors.magenta('SWEEP')} | "
                f"Target={Colors.magenta(self.sweep_side_outcome)}"
            )

            # Remove all existing quotes to avoid accidental sells / inventory drift
            self.cancel_all_orders()

    # Run Loop

    def run(self, duration_minutes: Optional[int] = None):
        """Main strategy loop."""
        logger.info(
            f"\n{Colors.bold('Hybrid MM:')} {Colors.cyan('BBO')} → {Colors.magenta('Endgame Sweep')} "
            f"| MaxPos: {Colors.blue(f'{self.max_position:.0f}')} | "
            f"Size: {Colors.yellow(f'{self.order_size:.0f}')} | "
            f"Interval: {Colors.gray(f'{self.check_interval}s')}"
        )

        if not self.fetch_market():
            logger.error("Failed to fetch market. Exiting.")
            return

        self.setup_websocket()
        self.start_websocket()

        time.sleep(5)

        # Optional: infer tick size from live orderbook if needed
        tokens_to_check = [self.token_ids[0]] if len(self.token_ids) == 2 else self.token_ids
        if self.orderbook_manager.has_all_data(tokens_to_check) and self.tick_size == 0.01:
            ob = self.orderbook_manager.get(self.token_ids[0])
            if ob:
                for price, _sz in (ob.get("bids", []) + ob.get("asks", [])):
                    if price % 0.01 != 0:
                        self.tick_size = 0.001
                        logger.info("Detected tick size: 0.001 (from orderbook)")
                        break

        self.is_running = True
        start_time = time.time()
        end_time = start_time + (duration_minutes * 60) if duration_minutes else None

        try:
            while self.is_running:
                if end_time and time.time() >= end_time:
                    break

                self.maybe_switch_mode()

                if self.mode == "NORMAL":
                    self.place_orders_normal()
                else:
                    self.place_orders_sweep()

                time.sleep(self.check_interval)

        except KeyboardInterrupt:
            logger.info("\nStopping...")

        finally:
            self.is_running = False
            self.cancel_all_orders()
            self.stop_websocket()
            logger.info("Stopped")


# CLI Entrypoint

def main():
    load_dotenv()

    private_key = os.getenv("POLYMARKET_PRIVATE_KEY")
    funder = os.getenv("POLYMARKET_FUNDER")

    if not private_key or not funder:
        logger.error("Missing environment variables!")
        logger.error("Set POLYMARKET_PRIVATE_KEY and POLYMARKET_FUNDER in .env")
        return 1

    market_slug = os.getenv("MARKET_SLUG", "")
    mode = os.getenv("MODE", "live")
    for arg in sys.argv[1:]:
        if arg.startswith("--mode="):
            mode = arg.split("=", 1)[1]
        elif arg == "--test":
            mode = "test"
        elif not market_slug:
            market_slug = arg

    if not market_slug:
        logger.error("No market slug provided!")
        logger.error("\nUsage:")
        logger.error("  uv run python examples/endgame_sweep_mm.py MARKET_SLUG")
        logger.error("  uv run python examples/endgame_sweep_mm.py https://polymarket.com/event/MARKET_SLUG")
        logger.error("  MARKET_SLUG=fed-decision-in-december uv run python examples/endgame_sweep_mm.py")
        return 1

    exchange = dr_manhattan.Polymarket(
        {"private_key": private_key, "funder": funder, "cache_ttl": 2.0, "verbose": True}
    )

    bot = EndgameSweepMarketMaker(
        exchange=exchange,
        market_slug=market_slug,
        max_position=100.0,
        order_size=5.0,
        max_delta=20.0,
        check_interval=5.0,
        mode=mode,
    )
    bot.run(duration_minutes=None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
