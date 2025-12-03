"""
VPIN + ΔVPIN Percentile-Based Liquidity Withdrawal Strategy

Logic:
    - Maintain VPIN buckets (50 buckets, bucket_volume V)
    - Compute bucket-level VPIN
    - Compute ΔVPIN = VPIN(t) - VPIN(t-1)
    - Maintain rolling window of ΔVPIN values (size W)
    - Compute percentile threshold (e.g., 95th percentile)
    - If ΔVPIN >= percentile_threshold → withdraw liquidity
    - Else → normal BBO join market making
"""

import os
import sys
import time
import asyncio
import numpy as np
from typing import List, Dict, Optional
from dotenv import load_dotenv

import dr_manhattan
from dr_manhattan.models import OrderSide
from dr_manhattan.utils import setup_logger
from dr_manhattan.utils.logger import Colors

logger = setup_logger(__name__)


class VPINDerivativeStrategy:
    def __init__(
        self,
        exchange: dr_manhattan.Polymarket,
        market_slug: str,
        check_interval: float = 5.0,
        max_position: float = 100.0,
        order_size: float = 5.0,
        max_delta: float = 20.0,

        # VPIN
        bucket_volume: float = 100.0,
        bucket_count: int = 50,

        # ΔVPIN percentile-based gating
        delta_window: int = 300,
        percentile_cutoff: float = 95.0,
    ):
        self.exchange = exchange
        self.market_slug = market_slug
        self.check_interval = check_interval
        self.max_position = max_position
        self.order_size = order_size
        self.max_delta = max_delta

        # VPIN parameters
        self.bucket_volume = bucket_volume
        self.bucket_count = bucket_count

        # VPIN state
        self.buckets = []
        self.current_vol = 0.0
        self.current_buy = 0.0
        self.current_sell = 0.0

        # ΔVPIN parameters
        self.delta_window = delta_window
        self.percentile_cutoff = percentile_cutoff

        # Rolling ΔVPIN storage
        self.delta_history = []
        self.prev_vpin = None

        # market state
        self.market = None
        self.token_ids = []
        self.outcomes = []
        self.tick_size = 0.01

        # websocket state
        self.ws = None
        self.orderbook_manager = None
        self.ws_thread = None
        self.is_running = False

    # ---------------------------------------------------
    # VPIN ingestion
    # ---------------------------------------------------

    def ingest_trade(self, price: float, size: float, is_buy: bool):
        """Feed each trade into the VPIN bucket logic."""
        self.current_vol += size
        if is_buy:
            self.current_buy += size
        else:
            self.current_sell += size

        # bucket complete?
        if self.current_vol >= self.bucket_volume:
            imbalance = abs(self.current_buy - self.current_sell)
            bucket_vpin = imbalance / max(self.current_vol, 1e-9)

            self.buckets.append(bucket_vpin)
            if len(self.buckets) > self.bucket_count:
                self.buckets.pop(0)

            # ΔVPIN update
            if self.prev_vpin is not None:
                delta = bucket_vpin - self.prev_vpin
                self.delta_history.append(delta)
                if len(self.delta_history) > self.delta_window:
                    self.delta_history.pop(0)

            self.prev_vpin = bucket_vpin

            # reset bucket
            self.current_vol = 0
            self.current_buy = 0
            self.current_sell = 0

    def get_vpin(self) -> float:
        """VPIN = mean of last bucket_count VPIN values."""
        if len(self.buckets) < self.bucket_count:
            return 0.0
        return np.mean(self.buckets)

    def get_delta_vpin(self) -> float:
        """Return the most recent ΔVPIN."""
        if not self.delta_history:
            return 0.0
        return self.delta_history[-1]

    def get_delta_threshold(self) -> float:
        """Compute percentile threshold (e.g., 95th percentile)."""
        if len(self.delta_history) < self.delta_window:
            return float("inf")     # threshold disabled until enough data
        return np.percentile(self.delta_history, self.percentile_cutoff)

    # ---------------------------------------------------
    # Market + websocket
    # ---------------------------------------------------

    def fetch_market(self):
        logger.info(f"Fetching market: {self.market_slug}")
        self.market = self.exchange.fetch_market_by_slug(self.market_slug)

        if not self.market:
            logger.error("Failed to fetch market")
            return False

        self.token_ids = self.market.metadata.get('clobTokenIds', [])
        self.outcomes = self.market.outcomes

        self.tick_size = self.exchange.get_tick_size(self.market)

        return True

    def setup_websocket(self):
        self.ws = self.exchange.get_websocket()
        self.orderbook_manager = self.ws.get_orderbook_manager()

    def start_websocket(self):
        tokens = [self.token_ids[0]] if len(self.token_ids) == 2 else self.token_ids

        if self.ws.loop is None:
            self.ws.loop = asyncio.new_event_loop()

        async def subscribe():
            await self.ws.connect()
            await self.ws.watch_orderbook_by_market(self.market.id, tokens)
            await self.ws._receive_loop()

        import threading

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

    # ---------------------------------------------------
    # Helpers
    # ---------------------------------------------------

    def get_positions(self) -> Dict[str, float]:
        pos = {}
        try:
            arr = self.exchange.fetch_positions_for_market(self.market)
            for p in arr:
                pos[p.outcome] = p.size
        except:
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
        logger.warning(f"Cancelling {len(orders)} open orders...")
        for o in orders:
            try:
                self.exchange.cancel_order(o.id, market_id=self.market.id)
            except:
                pass

    # ---------------------------------------------------
    # Main trading logic
    # ---------------------------------------------------

    def place_orders(self):
        vpin = self.get_vpin()
        delta_vpin = self.get_delta_vpin()
        delta_threshold = self.get_delta_threshold()

        logger.info(
            f"VPIN={vpin:.4f} | ΔVPIN={delta_vpin:.4f} | "
            f"Δ-threshold(P{self.percentile_cutoff})={delta_threshold:.4f}"
        )

        # --------------------
        # Gating logic
        # --------------------
        if delta_vpin > delta_threshold:
            logger.warning(
                f"ΔVPIN {delta_vpin:.4f} > percentile threshold "
                f"{delta_threshold:.4f} → withdrawing liquidity"
            )
            self.cancel_all_orders()
            return

        # --------------------
        # NORMAL SPREAD STRATEGY
        # --------------------
        positions = self.get_positions()
        open_orders = self.get_open_orders()

        max_pos = max(positions.values()) if positions else 0
        min_pos = min(positions.values()) if positions else 0
        delta = max_pos - min_pos

        logger.info(f"Delta: {delta:.2f} | OpenOrders: {len(open_orders)}")

        for i, (outcome, token_id) in enumerate(zip(self.outcomes, self.token_ids)):

            # price discovery (same as SpreadStrategy)
            if len(self.token_ids) == 2 and i == 1:
                yes_bid, yes_ask = self.orderbook_manager.get_best_bid_ask(self.token_ids[0])
                if yes_bid is None:
                    continue
                best_bid = 1.0 - yes_ask
                best_ask = 1.0 - yes_bid
            else:
                best_bid, best_ask = self.orderbook_manager.get_best_bid_ask(token_id)
                if best_bid is None:
                    continue

            # join BBO
            our_bid = self.exchange.round_to_tick_size(best_bid, self.tick_size)
            our_ask = self.exchange.round_to_tick_size(best_ask, self.tick_size)

            if our_bid >= our_ask:
                continue

            size = positions.get(outcome, 0)

            # delta management
            if delta > self.max_delta and size == max_pos:
                continue

            # stale order cleanup
            outcome_orders = [o for o in open_orders if o.outcome == outcome]
            buy_orders = [o for o in outcome_orders if o.side == OrderSide.BUY]
            sell_orders = [o for o in outcome_orders if o.side == OrderSide.SELL]

            # BUY
            place_buy = True
            for o in buy_orders:
                if abs(o.price - our_bid) < 0.001:
                    place_buy = False
                else:
                    try:
                        self.exchange.cancel_order(o.id)
                    except:
                        pass
            if size + self.order_size > self.max_position:
                place_buy = False
            if place_buy:
                try:
                    self.exchange.create_order(
                        market_id=self.market.id,
                        outcome=outcome,
                        side=OrderSide.BUY,
                        price=our_bid,
                        size=self.order_size,
                        params={'token_id': token_id}
                    )
                except Exception as e:
                    logger.error(e)

            # SELL
            place_sell = True
            for o in sell_orders:
                if abs(o.price - our_ask) < 0.001:
                    place_sell = False
                else:
                    try:
                        self.exchange.cancel_order(o.id)
                    except:
                        pass
            if size < self.order_size:
                place_sell = False
            if place_sell:
                try:
                    self.exchange.create_order(
                        market_id=self.market.id,
                        outcome=outcome,
                        side=OrderSide.SELL,
                        price=our_ask,
                        size=self.order_size,
                        params={'token_id': token_id}
                    )
                except Exception as e:
                    logger.error(e)

    # ---------------------------------------------------
    # Run loop
    # ---------------------------------------------------

    def run(self, duration_minutes: Optional[int] = None):
        logger.info("Starting VPIN-Δ Percentile Market Maker")

        if not self.fetch_market():
            return

        self.setup_websocket()
        self.start_websocket()

        time.sleep(4)

        # run
        self.is_running = True
        start = time.time()
        end = start + (duration_minutes * 60) if duration_minutes else None

        try:
            while self.is_running:
                if end and time.time() >= end:
                    break

                self.place_orders()
                time.sleep(self.check_interval)

        finally:
            self.is_running = False
            self.cancel_all_orders()
            self.stop_websocket()
            logger.info("Stopped VPIN-Δ strategy")


# ---------------------------------------------------
# CLI
# ---------------------------------------------------

def main():
    load_dotenv()

    private_key = os.getenv("POLYMARKET_PRIVATE_KEY")
    funder = os.getenv("POLYMARKET_FUNDER")

    market_slug = os.getenv("MARKET_SLUG", "")
    if len(sys.argv) > 1:
        market_slug = sys.argv[1]

    exchange = dr_manhattan.Polymarket({
        "private_key": private_key,
        "funder": funder,
        "cache_ttl": 2.0,
        "verbose": True,
    })

    bot = VPINDerivativeStrategy(
        exchange=exchange,
        market_slug=market_slug,
        percentile_cutoff=95.0,
        delta_window=300,  # 300 buckets history
    )

    bot.run()


if __name__ == "__main__":
    main()
