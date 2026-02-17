"""
Market Making Example with VPIN-based Liquidity Withdrawal

Adds VPIN monitoring to the SpreadStrategy.
- If VPIN >= threshold -> withdraw liquidity (cancel orders & skip quoting)
- Otherwise -> normal BBO join market making
- Modes: live (places orders) or test (logs only)

Usage:
    uv run python examples/vpin_strategy.py MARKET_SLUG --mode=live
    uv run python examples/vpin_strategy.py MARKET_SLUG --mode=test
Environment:
    export POLYMARKET_PRIVATE_KEY=...
    export POLYMARKET_FUNDER=...

Bucket count defaults to 50.
"""

import os
import sys
import time
import asyncio
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional
from collections import deque
import requests
from dotenv import load_dotenv

import dr_manhattan
from dr_manhattan.models import OrderSide
from dr_manhattan.utils import setup_logger
from dr_manhattan.utils.logger import Colors

logger = setup_logger(__name__)


class VPINStrategy:
    """
    Enhanced SpreadStrategy with VPIN monitoring.

    VPIN logic:
        - Maintain 50 buckets
        - Each bucket collects V units of volume
        - Compute imbalance per bucket
        - VPIN = average( last 50 bucket_imbalances )
        - If VPIN >= 0.8 -> withdraw liquidity
    """

    def __init__(
        self,
        exchange: dr_manhattan.Polymarket,
        market_slug: str,
        max_position: float = 100.0,
        order_size: float = 5.0,
        max_delta: float = 20.0,
        check_interval: float = 5.0,
        bucket_volume: float = 100.0,    # bucket size V
        vpin_threshold: float = 0.8,
        bucket_count: int = 50,
        flow_log_interval: float = 5.0,  # seconds: how often to print FLOW summary
        trade_poll_interval: float = 2.0,  # seconds between trade API polls
        mode: str = "live",  # "live" or "test"
    ):

        self.exchange = exchange
        self.market_slug = market_slug
        self.max_position = max_position
        self.order_size = order_size
        self.max_delta = max_delta
        self.check_interval = check_interval

        # VPIN parameters
        self.bucket_volume = bucket_volume
        self.bucket_count = bucket_count
        self.vpin_threshold = vpin_threshold

        # VPIN state
        self.buckets = []
        self.current_vol = 0.0
        self.current_buy = 0.0
        self.current_sell = 0.0
        self.seen_trades_max = 5000
        self.seen_trades = deque(maxlen=self.seen_trades_max)
        self.seen_trades_set = set()

        # Market/Websocket state
        self.market = None
        self.token_ids = []
        self.outcomes = []

        self.ws = None
        self.orderbook_manager = None
        self.ws_thread = None
        self.trade_thread = None
        self.is_running = False

        # Flow stats (price change proxy)
        self.flow_buy_count = 0
        self.flow_sell_count = 0
        self.flow_buy_vol = 0.0
        self.flow_sell_vol = 0.0
        self.flow_zero_size_count = 0

        self.flow_last_log_ts = 0.0
        self.flow_log_interval = float(flow_log_interval)

        # Trade polling (Data API /trades)
        self.trade_poll_interval = float(trade_poll_interval)
        self.trade_thread = None
        self.trade_thread_running = False
        self.last_trade_ts = 0

        # Mode
        self.live_mode = mode.lower() == "live"

        # Thread safety for trade ingestion/state
        self.trade_lock = threading.Lock()

    # VPIN Logic

    def ingest_trade(self, price: float, size: float, is_buy: bool):
        """ Feed each trade into VPIN buckets. """
        with self.trade_lock:
            self.current_vol += size
            if is_buy:
                self.current_buy += size
            else:
                self.current_sell += size

            # bucket full -> close and start new
            if self.current_vol >= self.bucket_volume:
                imbalance = abs(self.current_buy - self.current_sell)
                bucket_vpin = imbalance / max(self.current_vol, 1e-9)

                self.buckets.append(bucket_vpin)
                if len(self.buckets) > self.bucket_count:
                    self.buckets.pop(0)

                # reset
                self.current_vol = 0
                self.current_buy = 0
                self.current_sell = 0

    def get_vpin(self) -> float:
        """ Compute VPIN (average of last N bucket imbalances). """
        with self.trade_lock:
            if len(self.buckets) < self.bucket_count:
                return 0.0
            return sum(self.buckets) / len(self.buckets)

    # Trade polling (Data API /trades)

    def _maybe_log_flow_stats(self):
        now = time.time()
        with self.trade_lock:
            if self.flow_last_log_ts == 0.0:
                self.flow_last_log_ts = now
                return
            if now - self.flow_last_log_ts < self.flow_log_interval:
                return

            total_count = self.flow_buy_count + self.flow_sell_count
            total_vol = self.flow_buy_vol + self.flow_sell_vol

            buy_share = (self.flow_buy_vol / total_vol) if total_vol > 0 else 0.0
            sell_share = (self.flow_sell_vol / total_vol) if total_vol > 0 else 0.0

            logger.info(
                f"{Colors.gray('TRADES')} "
                f"count(B/S)={self.flow_buy_count}/{self.flow_sell_count} "
                f"| vol(B/S)={self.flow_buy_vol:.2f}/{self.flow_sell_vol:.2f} "
                f"| share(B/S)={buy_share:.1%}/{sell_share:.1%} "
                f"| zero_size={self.flow_zero_size_count} "
                f"| total_events={total_count}"
            )

            self.flow_last_log_ts = now

    def _handle_trade_row(self, row: Dict):
        """Ingest a single trade row from Data API /trades."""
        side = str(row.get("side", "")).upper()
        size_raw = row.get("size")
        price_raw = row.get("price")
        ts_raw = row.get("timestamp")

        try:
            size = float(size_raw)
            price = float(price_raw)
            if size <= 0:
                self.flow_zero_size_count += 1
                return
        except Exception:
            return

        with self.trade_lock:
            if side == "BUY":
                self.flow_buy_count += 1
                self.flow_buy_vol += size
            elif side == "SELL":
                self.flow_sell_count += 1
                self.flow_sell_vol += size
            else:
                return

        self.ingest_trade(price, size, side == "BUY")

        # Log each trade
        try:
            ts_dt = (
                datetime.fromtimestamp(int(ts_raw), tz=timezone.utc)
                if ts_raw is not None
                else datetime.now(timezone.utc)
            )
        except Exception:
            ts_dt = datetime.now(timezone.utc)

        logger.info(
            f"{Colors.gray('TRADE')} {Colors.green(side) if side=='BUY' else Colors.red(side)} "
            f"{size:.2f} @ {price:.4f} | {ts_dt.isoformat()}"
        )

    def _poll_trades_loop(self):
        """Background loop polling Data API /trades for this market."""
        condition_id = str(self.market.metadata.get("conditionId", self.market.id))
        url = f"{self.exchange.DATA_API_URL}/trades"
        self.trade_thread_running = True

        while self.trade_thread_running and self.is_running:
            try:
                params = {
                    "market": condition_id,
                    "limit": 200,
                    "offset": 0,
                    "takerOnly": "true",
                }
                resp = requests.get(url, params=params, timeout=5)
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, list):
                    new_rows = []
                    for row in data:
                        ts = row.get("timestamp")
                        tx = row.get("transactionHash") or row.get("transaction_hash")
                        key = (tx, ts, row.get("side"), row.get("price"), row.get("size"))
                        with self.trade_lock:
                            if key in self.seen_trades_set:
                                continue
                        # Only accept newer trades by timestamp if available
                        if ts is None:
                            continue
                        try:
                            ts_int = int(ts)
                        except Exception:
                            ts_int = 0
                        with self.trade_lock:
                            if ts_int < self.last_trade_ts:
                                continue
                        new_rows.append((ts_int, key, row))

                    # Process in chronological order
                    new_rows.sort(key=lambda x: x[0])
                    for ts_int, key, row in new_rows:
                        with self.trade_lock:
                            if len(self.seen_trades) == self.seen_trades_max:
                                old = self.seen_trades.popleft()
                                self.seen_trades_set.discard(old)
                            self.seen_trades.append(key)
                            self.seen_trades_set.add(key)
                            self.last_trade_ts = max(self.last_trade_ts, ts_int)
                        self._handle_trade_row(row)

                    self._maybe_log_flow_stats()
            except Exception as e:
                logger.warning(f"Trade poll failed: {e}")

            time.sleep(self.trade_poll_interval)

    # Market Fetch / Websocket

    def fetch_market(self) -> bool:
        logger.info(f"Fetching market: {self.market_slug}")
        self.market = self.exchange.fetch_market_by_slug(self.market_slug)

        if not self.market:
            logger.error("Failed to fetch market")
            return False

        self.token_ids = self.market.metadata.get('clobTokenIds', [])
        self.outcomes = self.market.outcomes

        if not self.token_ids:
            logger.error("No token IDs found")
            return False

        # Infer tick size
        self.tick_size = self.exchange.get_tick_size(self.market)

        for outcome, price in self.market.prices.items():
            ps = f"{price:.4f}"
            if '.' in ps and len(ps.split('.')[1].rstrip('0')) == 3:
                self.tick_size = 0.001
                break

        logger.info(f"Market: {self.market.question}")
        return True

    def setup_websocket(self):
        self.ws = self.exchange.get_websocket()
        self.orderbook_manager = self.ws.get_orderbook_manager()

    def start_websocket(self):
        # Subscribe to both tokens so we always have bids/asks even if one side is empty
        tokens = self.token_ids

        if self.ws.loop is None:
            self.ws.loop = asyncio.new_event_loop()

        async def subscribe():
            try:
                await self.ws.connect()
            except Exception as e:
                logger.error(f"WS connect failed: {e}")
                return

            try:
                await self.ws.watch_orderbook_by_market(
                    self.market.id,
                    tokens,
                )
            except Exception as e:
                logger.error(f"WS subscribe failed: {e}")
                return

            try:
                await self.ws._receive_loop()
            except Exception as e:
                logger.error(f"WS receive loop failed: {e}")

        def run_loop():
            asyncio.set_event_loop(self.ws.loop)
            self.ws.loop.run_until_complete(subscribe())

        self.ws_thread = threading.Thread(target=run_loop, daemon=True)
        self.ws_thread.start()

        time.sleep(2)

    def stop_websocket(self):
        if self.ws:
            self.ws.stop()
        if self.ws_thread:
            self.ws_thread.join(timeout=5)

    # Helpers

    def get_positions(self) -> Dict[str, float]:
        pos = {}
        try:
            arr = self.exchange.fetch_positions_for_market(self.market)
            for p in arr:
                pos[p.outcome] = p.size
        except Exception:
            pass
        return pos

    def get_open_orders(self) -> List:
        try:
            cid = self.market.metadata.get('conditionId', self.market.id)
            return self.exchange.fetch_open_orders(market_id=cid)
        except:
            return []

    def cancel_all_orders(self):
        orders = self.get_open_orders()
        if not orders:
            return
        logger.info(f"Cancelling {len(orders)} orders")
        if not self.live_mode:
            logger.info("  (test mode) skip cancel")
            return
        for o in orders:
            try:
                self.exchange.cancel_order(o.id, market_id=self.market.id)
            except:
                pass

    # Main Trading Logic

    def place_orders(self):
        """
        Overridden version of SpreadStrategy.place_orders()
        with VPIN gating: if VPIN is high, pull liquidity; otherwise join BBO.
        """

        vpin = self.get_vpin()
        logger.info(f"VPIN: {vpin:.4f}")

        # VPIN high -> withdraw liquidity
        if vpin >= self.vpin_threshold:
            logger.warning(f"VPIN {vpin:.3f} exceeds threshold ({self.vpin_threshold}) - withdrawing liquidity")
            self.cancel_all_orders()
            return

        # Otherwise -> normal market making (BBO join)
        positions = self.get_positions()
        open_orders = self.get_open_orders()

        max_position_size = max(positions.values()) if positions else 0
        min_position_size = min(positions.values()) if positions else 0
        delta = max_position_size - min_position_size

        delta_side = ""
        if delta > 0 and positions:
            max_outcome = max(positions, key=positions.get)
            delta_abbrev = max_outcome[0] if len(self.outcomes) == 2 else max_outcome
            delta_side = f" {Colors.magenta(delta_abbrev)}"

        pos_compact = ""
        if positions:
            parts = []
            for outcome, size in positions.items():
                abbrev = outcome[0] if len(self.outcomes) == 2 else outcome
                parts.append(f"{Colors.blue(f'{size:.0f}')} {Colors.magenta(abbrev)}")
            pos_compact = " ".join(parts)
        else:
            pos_compact = Colors.gray("None")

        logger.info(
            f"\n[{time.strftime('%H:%M:%S')}] Pos: {pos_compact} | "
            f"Delta: {Colors.yellow(f'{delta:.1f}')}{delta_side} | "
            f"Orders: {Colors.cyan(str(len(open_orders)))}"
        )

        if open_orders:
            for order in open_orders:
                side_colored = (
                    Colors.green(order.side.value.upper())
                    if order.side == OrderSide.BUY
                    else Colors.red(order.side.value.upper())
                )
                size_display = (
                    order.original_size if hasattr(order, "original_size") and order.original_size else order.size
                )
                logger.info(
                    f"  {Colors.gray('Open:')} {Colors.magenta(order.outcome)} {side_colored} "
                    f"{size_display:.0f} @ {Colors.yellow(f'{order.price:.4f}')}"
                )

        if delta > self.max_delta:
            logger.warning(f"Delta ({delta:.2f}) > max ({self.max_delta:.2f}) - reducing exposure")

        for i, (outcome, token_id) in enumerate(zip(self.outcomes, self.token_ids)):
            if len(self.token_ids) == 2 and i == 1:
                first_bid, first_ask = self.orderbook_manager.get_best_bid_ask(self.token_ids[0])
                if first_bid is None or first_ask is None:
                    logger.warning(f"  {outcome}: No orderbook data, skipping...")
                    continue
                best_bid = 1.0 - first_ask
                best_ask = 1.0 - first_bid
            else:
                best_bid, best_ask = self.orderbook_manager.get_best_bid_ask(token_id)
                if best_bid is None or best_ask is None:
                    logger.warning(f"  {outcome}: No orderbook data, skipping...")
                    continue

            our_bid = self.exchange.round_to_tick_size(best_bid, self.tick_size)
            our_ask = self.exchange.round_to_tick_size(best_ask, self.tick_size)

            our_bid = max(0.01, min(0.99, our_bid))
            our_ask = max(0.01, min(0.99, our_ask))

            if our_bid >= our_ask:
                logger.warning(f"  {outcome}: Spread too tight (bid={our_bid:.4f} >= ask={our_ask:.4f}), skipping")
                continue

            position_size = positions.get(outcome, 0)

            outcome_orders = [o for o in open_orders if o.outcome == outcome]
            buy_orders = [o for o in outcome_orders if o.side == OrderSide.BUY]
            sell_orders = [o for o in outcome_orders if o.side == OrderSide.SELL]

            if delta > self.max_delta and position_size == max_position_size:
                logger.info(f"    {outcome}: Skip (delta mgmt)")
                continue

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
                                    f"    {Colors.gray('✕ Cancel')} {Colors.green('BUY')} "
                                    f"@ {Colors.yellow(f'{o.price:.4f}')}"
                                )
                            else:
                                logger.info(
                                    f"    (test) {Colors.gray('✕ Cancel')} {Colors.green('BUY')} "
                                    f"@ {Colors.yellow(f'{o.price:.4f}')}"
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
                                    f"    {Colors.gray('✕ Cancel')} {Colors.red('SELL')} "
                                    f"@ {Colors.yellow(f'{o.price:.4f}')}"
                                )
                            else:
                                logger.info(
                                    f"    (test) {Colors.gray('✕ Cancel')} {Colors.red('SELL')} "
                                    f"@ {Colors.yellow(f'{o.price:.4f}')}"
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

    # Run

    def run(self, duration_minutes: Optional[int] = None):
        logger.info("Starting VPIN Market Maker")

        if not self.fetch_market():
            return

        self.is_running = True

        self.setup_websocket()
        self.start_websocket()
        self.trade_thread = threading.Thread(target=self._poll_trades_loop, daemon=True)
        self.trade_thread.start()

        time.sleep(4)

        tokens = [self.token_ids[0]] if len(self.token_ids) == 2 else self.token_ids
        if not self.orderbook_manager.has_all_data(tokens):
            logger.warning("Missing orderbook")

        start = time.time()
        end = start + (duration_minutes * 60) if duration_minutes else None

        try:
            while self.is_running:
                if end and time.time() >= end:
                    break

                self.place_orders()
                time.sleep(self.check_interval)

        except KeyboardInterrupt:
            logger.info("Stopping...")

        finally:
            self.is_running = False
            self.trade_thread_running = False
            if self.trade_thread:
                self.trade_thread.join(timeout=5)
            self.cancel_all_orders()
            self.stop_websocket()
            logger.info("Stopped (VPIN strategy)")


# CLI Entrypoint

def main():
    load_dotenv()

    private_key = os.getenv('POLYMARKET_PRIVATE_KEY')
    funder = os.getenv('POLYMARKET_FUNDER')

    if not private_key:
        print("Missing POLYMARKET_PRIVATE_KEY")
        return

    market_slug = os.getenv("MARKET_SLUG", "")
    mode = os.getenv("MODE", "live")
    # Args: [market_slug] [--mode=live|test] or --test
    for arg in sys.argv[1:]:
        if arg.startswith("--mode="):
            mode = arg.split("=", 1)[1]
        elif arg == "--test":
            mode = "test"
        elif not market_slug:
            market_slug = arg

    exchange = dr_manhattan.Polymarket({
        "private_key": private_key,
        "funder": funder,
        "cache_ttl": 2.0,
        "verbose": True,
    })

    bot = VPINStrategy(
        exchange=exchange,
        market_slug=market_slug,
        max_position=5,
        order_size=1,
        max_delta=3,
        check_interval=5,
        bucket_volume=50,
        vpin_threshold=0.8,
        bucket_count=50,
        flow_log_interval=5.0,  
        mode=mode,
    )

    bot.run()


if __name__ == "__main__":
    main()
