#!/usr/bin/env python3
"""
WebSocket-based Market Making Example for Polymarket

High-performance market making using exchange interfaces and WebSocket orderbook updates.

Usage:
    # Using market slug
    uv run python examples/market_making_websocket.py fed-decision-in-december

    # Using full URL
    uv run python examples/market_making_websocket.py https://polymarket.com/event/fed-decision-in-december

    # Via environment variable
    MARKET_SLUG="lol-t1-kt-2025-11-09" uv run python examples/market_making_websocket.py
"""

import os
import sys
import time
import asyncio
from typing import Dict, List, Optional
from dotenv import load_dotenv

import dr_manhattan
from dr_manhattan.models import OrderSide
from dr_manhattan.utils import setup_logger

logger = setup_logger(__name__)


class WebSocketMarketMaker:
    """
    High-performance market maker using exchange interfaces.
    Supports multi-token markets with delta management.
    """

    def __init__(
        self,
        exchange: dr_manhattan.Polymarket,
        market_slug: str,
        max_position: float = 100.0,
        order_size: float = 5.0,
        spread_offset: float = 0.01,
        max_delta: float = 20.0,
        check_interval: float = 5.0
    ):
        """
        Initialize market maker

        Args:
            exchange: Polymarket exchange instance
            market_slug: Market slug or URL
            max_position: Maximum position size per outcome
            order_size: Size of each order
            spread_offset: How far inside the spread to place orders
            max_delta: Maximum position imbalance
            check_interval: How often to check and adjust orders
        """
        self.exchange = exchange
        self.market_slug = market_slug
        self.max_position = max_position
        self.order_size = order_size
        self.spread_offset = spread_offset
        self.max_delta = max_delta
        self.check_interval = check_interval

        # Market data
        self.market = None
        self.token_ids = []
        self.outcomes = []

        # WebSocket
        self.ws = None
        self.orderbook_manager = None
        self.ws_thread = None

        self.is_running = False

    def fetch_market(self) -> bool:
        """
        Fetch market data using exchange interface

        Returns:
            True if successful, False otherwise
        """
        logger.info(f"Fetching market: {self.market_slug}")

        # Use exchange method to fetch by slug/URL
        self.market = self.exchange.fetch_market_by_slug(self.market_slug)

        if not self.market:
            logger.error(f"Failed to fetch market: {self.market_slug}")
            return False

        # Extract token IDs and outcomes
        self.token_ids = self.market.metadata.get('clobTokenIds', [])
        self.outcomes = self.market.outcomes

        if not self.token_ids:
            logger.error("No token IDs found in market")
            return False

        # Get tick size from market
        self.tick_size = self.exchange.get_tick_size(self.market)

        # Display market info
        logger.info(f"\n{'='*80}")
        logger.info(f"Market: {self.market.question}")
        logger.info(f"Market ID: {self.market.id}")
        logger.info(f"Outcomes: {self.outcomes}")
        logger.info(f"Token IDs: {len(self.token_ids)} tokens")
        logger.info(f"Tick size: {self.tick_size}")

        for i, (outcome, token_id) in enumerate(zip(self.outcomes, self.token_ids)):
            price = self.market.prices.get(outcome, 0)
            logger.info(f"  [{i}] {outcome}: {price:.4f} (Token: {token_id[:16]}...)")

        logger.info(f"Volume: ${self.market.volume:,.2f}")
        logger.info(f"Liquidity: ${self.market.liquidity:,.2f}")

        slug = self.market.metadata.get('slug', '')
        if slug:
            logger.info(f"URL: https://polymarket.com/event/{slug}")
        logger.info(f"{'='*80}\n")

        return True

    def setup_websocket(self):
        """Setup WebSocket connection using exchange interface"""
        logger.info("Setting up WebSocket connection...")

        # Get WebSocket from exchange
        self.ws = self.exchange.get_websocket()

        # Get orderbook manager
        self.orderbook_manager = self.ws.get_orderbook_manager()

        logger.info(f"Initialized WebSocket for {len(self.token_ids)} tokens")

    def start_websocket(self):
        """Start WebSocket and subscribe to orderbooks"""
        logger.info("Starting WebSocket...")

        # Create event loop if needed
        if self.ws.loop is None:
            self.ws.loop = asyncio.new_event_loop()

        # Define subscription coroutine
        async def subscribe_all():
            await self.ws.connect()

            # Subscribe to market orderbooks (no callback needed, uses manager)
            await self.ws.watch_orderbook_by_market(self.market.id, self.token_ids)

            logger.info(f"  Subscribed to {len(self.token_ids)} token orderbooks")

            # Start receive loop
            await self.ws._receive_loop()

        # Run in background thread
        import threading

        def run_loop():
            asyncio.set_event_loop(self.ws.loop)
            self.ws.loop.run_until_complete(subscribe_all())

        self.ws_thread = threading.Thread(target=run_loop, daemon=True)
        self.ws_thread.start()

        time.sleep(2)
        logger.info("WebSocket started\n")

    def stop_websocket(self):
        """Stop WebSocket connection"""
        if self.ws:
            logger.info("Stopping WebSocket...")
            self.ws.stop()
            if self.ws_thread:
                self.ws_thread.join(timeout=5)
            logger.info("WebSocket stopped")

    def get_positions(self) -> Dict[str, float]:
        """
        Get current positions using exchange interface

        Returns:
            Dictionary mapping outcome to position size
        """
        positions = {}

        try:
            positions_list = self.exchange.fetch_positions_for_market(self.market)
            for pos in positions_list:
                positions[pos.outcome] = pos.size
        except Exception as e:
            logger.warning(f"Failed to fetch positions: {e}")

        return positions

    def get_open_orders(self) -> List:
        """
        Get all open orders using exchange interface

        Returns:
            List of open orders
        """
        try:
            condition_id = self.market.metadata.get('conditionId', self.market.id)
            return self.exchange.fetch_open_orders(market_id=condition_id)
        except Exception as e:
            logger.warning(f"Failed to fetch open orders: {e}")
            return []

    def cancel_all_orders(self):
        """Cancel all open orders"""
        logger.info("Cancelling all orders...")
        orders = self.get_open_orders()

        for order in orders:
            try:
                self.exchange.cancel_order(order.id, market_id=self.market.id)
                logger.info(f"  Cancelled order {order.id}")
            except Exception as e:
                logger.warning(f"  Failed to cancel order {order.id}: {e}")

        logger.info(f"Cancelled {len(orders)} orders\n")

    def place_orders(self):
        """Main market making logic using orderbook manager"""
        # Get current positions
        positions = self.get_positions()
        open_orders = self.get_open_orders()

        # Calculate position metrics
        total_long = sum(positions.values())
        max_position_size = max(positions.values()) if positions else 0
        min_position_size = min(positions.values()) if positions else 0
        delta = max_position_size - min_position_size

        logger.info(f"\n{'='*80}")
        logger.info(f"MARKET MAKING ITERATION - {time.strftime('%H:%M:%S')}")
        logger.info(f"{'='*80}")

        # Display positions
        logger.info("\nCurrent Positions:")
        if positions:
            for outcome, size in positions.items():
                logger.info(f"  {outcome}: {size:.2f} shares")
        else:
            logger.info("  No positions")

        logger.info(f"\nPosition Metrics:")
        logger.info(f"  Total exposure: {total_long:.2f} shares")
        logger.info(f"  Delta (imbalance): {delta:.2f} shares")

        logger.info(f"\nOpen Orders: {len(open_orders)}")
        for order in open_orders:
            logger.info(f"  {order.outcome} {order.side.value.upper()}: {order.size:.0f} @ {order.price:.4f}")

        # Check delta risk
        if delta > self.max_delta:
            logger.warning(f"\n⚠️  Delta ({delta:.2f}) exceeds max ({self.max_delta:.2f})")
            logger.warning("  Reducing exposure on heavy side...")

        # Place orders for each outcome
        logger.info("\nPlacing orders:")

        for i, (outcome, token_id) in enumerate(zip(self.outcomes, self.token_ids)):
            # Get orderbook using manager
            best_bid, best_ask = self.orderbook_manager.get_best_bid_ask(token_id)

            if best_bid is None or best_ask is None:
                logger.warning(f"  {outcome}: No orderbook data yet, skipping...")
                continue

            # Calculate our prices (inside the spread)
            # Use tick_size instead of hardcoded spread_offset
            our_bid = best_bid + self.tick_size
            our_ask = best_ask - self.tick_size

            # Round to tick size
            our_bid = self.exchange.round_to_tick_size(our_bid, self.tick_size)
            our_ask = self.exchange.round_to_tick_size(our_ask, self.tick_size)

            # Ensure our bid < our ask and within valid range
            our_bid = max(0.01, min(0.99, our_bid))
            our_ask = max(0.01, min(0.99, our_ask))

            if our_bid >= our_ask:
                mid = (best_bid + best_ask) / 2
                our_bid = self.exchange.round_to_tick_size(max(0.01, mid - self.tick_size), self.tick_size)
                our_ask = self.exchange.round_to_tick_size(min(0.99, mid + self.tick_size), self.tick_size)

            position_size = positions.get(outcome, 0)

            # Check existing orders
            outcome_orders = [o for o in open_orders if o.outcome == outcome]
            buy_orders = [o for o in outcome_orders if o.side == OrderSide.BUY]
            sell_orders = [o for o in outcome_orders if o.side == OrderSide.SELL]

            logger.info(f"\n  {outcome} (Token: {token_id[:8]}...):")
            logger.info(f"    Orderbook: Bid={best_bid:.4f} Ask={best_ask:.4f}")
            logger.info(f"    Position: {position_size:.2f} shares")

            # Delta management
            if delta > self.max_delta and position_size == max_position_size:
                logger.info(f"    Skipping: Already at max position (delta management)")
                continue

            # Place BUY order if needed
            should_place_buy = True
            if buy_orders:
                for order in buy_orders:
                    if abs(order.price - our_bid) < 0.001:
                        should_place_buy = False
                        logger.info(f"    BUY: Already have order @ {order.price:.4f}")
                        break

                if should_place_buy:
                    for order in buy_orders:
                        try:
                            self.exchange.cancel_order(order.id)
                            logger.info(f"    Cancelled outdated BUY @ {order.price:.4f}")
                        except:
                            pass

            if position_size + self.order_size > self.max_position:
                should_place_buy = False
                logger.info(f"    BUY: Would exceed max position")

            if should_place_buy:
                try:
                    order = self.exchange.create_order(
                        market_id=self.market.id,
                        outcome=outcome,
                        side=OrderSide.BUY,
                        price=our_bid,
                        size=self.order_size,
                        params={'token_id': token_id}
                    )
                    logger.info(f"    ✓ BUY: {self.order_size:.0f} @ {our_bid:.4f} (ID: {order.id[:16]}...)")
                except Exception as e:
                    logger.error(f"    ✗ BUY failed: {e}")

            # Place SELL order if needed
            should_place_sell = True
            if sell_orders:
                for order in sell_orders:
                    if abs(order.price - our_ask) < 0.001:
                        should_place_sell = False
                        logger.info(f"    SELL: Already have order @ {order.price:.4f}")
                        break

                if should_place_sell:
                    for order in sell_orders:
                        try:
                            self.exchange.cancel_order(order.id)
                            logger.info(f"    Cancelled outdated SELL @ {order.price:.4f}")
                        except:
                            pass

            if position_size < self.order_size:
                should_place_sell = False
                logger.info(f"    SELL: Insufficient shares ({position_size:.2f} < {self.order_size:.2f})")

            if should_place_sell:
                try:
                    order = self.exchange.create_order(
                        market_id=self.market.id,
                        outcome=outcome,
                        side=OrderSide.SELL,
                        price=our_ask,
                        size=self.order_size,
                        params={'token_id': token_id}
                    )
                    logger.info(f"    ✓ SELL: {self.order_size:.0f} @ {our_ask:.4f} (ID: {order.id[:16]}...)")
                except Exception as e:
                    logger.error(f"    ✗ SELL failed: {e}")

        logger.info(f"\n{'='*80}\n")

    def run(self, duration_minutes: Optional[int] = None):
        """Run the market making bot"""
        logger.info(f"\n{'='*80}")
        logger.info("WEBSOCKET MARKET MAKER")
        logger.info(f"{'='*80}")
        logger.info(f"Max position per outcome: {self.max_position:.2f}")
        logger.info(f"Order size: {self.order_size:.2f}")
        logger.info(f"Spread offset: {self.spread_offset:.4f}")
        logger.info(f"Max delta: {self.max_delta:.2f}")
        logger.info(f"Check interval: {self.check_interval}s")
        if duration_minutes:
            logger.info(f"Duration: {duration_minutes} minutes")
        logger.info(f"{'='*80}\n")

        # Fetch market using exchange interface
        if not self.fetch_market():
            logger.error("Failed to fetch market. Exiting.")
            return

        # Setup and start WebSocket
        self.setup_websocket()
        self.start_websocket()

        # Wait for initial orderbook data
        logger.info("Waiting for initial orderbook data...")
        time.sleep(5)

        # Check if we got data using manager
        if self.orderbook_manager.has_all_data(self.token_ids):
            logger.info("Orderbook data received for all tokens\n")
        else:
            logger.warning("Some tokens missing orderbook data. Continuing anyway...\n")

        # Run main loop
        self.is_running = True
        start_time = time.time()
        end_time = start_time + (duration_minutes * 60) if duration_minutes else None

        try:
            while self.is_running:
                if end_time and time.time() >= end_time:
                    break

                self.place_orders()

                # Wait for next iteration
                if end_time is None or time.time() < end_time:
                    time.sleep(self.check_interval)

        except KeyboardInterrupt:
            logger.info("\n\nBot interrupted by user")

        finally:
            self.is_running = False
            self.cancel_all_orders()
            self.stop_websocket()

            logger.info(f"\n{'='*80}")
            logger.info("MARKET MAKER STOPPED")
            logger.info(f"{'='*80}\n")


def main():
    load_dotenv()

    private_key = os.getenv('POLYMARKET_PRIVATE_KEY')
    funder = os.getenv('POLYMARKET_FUNDER')

    if not private_key or not funder:
        logger.error("Missing environment variables!")
        logger.error("Set POLYMARKET_PRIVATE_KEY and POLYMARKET_FUNDER in .env")
        return 1

    # Get market slug from command line or environment
    market_slug = os.getenv('MARKET_SLUG', '')

    if len(sys.argv) > 1:
        market_slug = sys.argv[1]

    if not market_slug:
        logger.error("No market slug provided!")
        logger.error("\nUsage:")
        logger.error("  uv run python examples/market_making_websocket.py MARKET_SLUG")
        logger.error("  uv run python examples/market_making_websocket.py https://polymarket.com/event/MARKET_SLUG")
        logger.error("  MARKET_SLUG=fed-decision-in-december uv run python examples/market_making_websocket.py")
        logger.error("\nExample slugs:")
        logger.error("  fed-decision-in-december")
        logger.error("  lol-t1-kt-2025-11-09")
        return 1

    # Create exchange
    exchange = dr_manhattan.Polymarket({
        'private_key': private_key,
        'funder': funder,
        'cache_ttl': 2.0,
        'verbose': True
    })

    # Create and run market maker
    mm = WebSocketMarketMaker(
        exchange=exchange,
        market_slug=market_slug,
        max_position=100.0,
        order_size=5.0,
        spread_offset=0.01,
        max_delta=20.0,
        check_interval=5.0
    )

    mm.run(duration_minutes=None)

    return 0


if __name__ == "__main__":
    sys.exit(main())
