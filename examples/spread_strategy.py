"""
Market Making Example for Polymarket

High-performance market making using exchange interfaces and WebSocket orderbook updates.

Usage:
    # Single market event - trades all tokens (Yes/No)
    uv run python examples/spread_strategy.py fed-decision-in-december

    # Multi-market event - shows interactive selection menu
    uv run python examples/spread_strategy.py what-day-will-openai-release-a-new-frontier-model

    # Multi-market event - select market by index (skip menu)
    uv run python examples/spread_strategy.py what-day-will-openai-release-a-new-frontier-model --market 0

    # Using full URL
    uv run python examples/spread_strategy.py https://polymarket.com/event/fed-decision-in-december
"""

import asyncio
import os
import sys
import threading
import time
from typing import Dict, List, Optional

from dotenv import load_dotenv

import dr_manhattan
from dr_manhattan.base.order_tracker import OrderEvent, OrderTracker, create_fill_logger
from dr_manhattan.models import OrderSide
from dr_manhattan.utils import setup_logger
from dr_manhattan.utils.logger import Colors

logger = setup_logger(__name__)


class SpreadStrategy:
    """
    High-performance market maker using exchange interfaces.
    Supports multi-token markets with delta management.

    For binary markets, only subscribes to first token (Yes) orderbook.
    Second token (No) prices are calculated as inverse (1 - Yes price).
    This reduces WebSocket bandwidth by 50% for binary markets.
    """

    def __init__(
        self,
        exchange: dr_manhattan.Polymarket,
        market_slug: str,
        max_position: float = 100.0,
        order_size: float = 5.0,
        max_delta: float = 20.0,
        check_interval: float = 5.0,
        track_fills: bool = True,
        token_filter: Optional[str] = None,
        market_index: Optional[int] = None,
    ):
        """
        Initialize market maker

        Args:
            exchange: Polymarket exchange instance
            market_slug: Market slug or URL
            max_position: Maximum position size per outcome
            order_size: Size of each order
            max_delta: Maximum position imbalance
            check_interval: How often to check and adjust orders
            track_fills: Enable order fill tracking and logging
            token_filter: Optional token index (e.g., "0") or name (e.g., "Monday") to trade only that token
            market_index: Optional market index for multi-market events (skip interactive selection)
        """
        self.exchange = exchange
        self.market_slug = market_slug
        self.max_position = max_position
        self.order_size = order_size
        self.max_delta = max_delta
        self.check_interval = check_interval
        self.track_fills = track_fills
        self.token_filter = token_filter
        self.market_index = market_index

        # Market data
        self.market = None
        self.token_ids = []
        self.outcomes = []

        # WebSocket
        self.ws = None
        self.user_ws = None
        self.orderbook_manager = None
        self.ws_thread = None

        # Order tracking
        self.order_tracker: Optional[OrderTracker] = None

        self.is_running = False

    def fetch_market(self) -> bool:
        """
        Fetch market data using exchange interface

        Returns:
            True if successful, False otherwise
        """
        logger.info(f"Fetching market: {self.market_slug}")

        # Fetch all markets from the event
        all_markets = self.exchange.fetch_markets_by_slug(self.market_slug)

        if not all_markets:
            logger.error(f"Failed to fetch market: {self.market_slug}")
            return False

        # If multiple markets in event, select or prompt
        if len(all_markets) > 1:
            if self.market_index is not None:
                # Use provided index
                if 0 <= self.market_index < len(all_markets):
                    selected_idx = self.market_index
                else:
                    logger.error(
                        f"Market index {self.market_index} out of range (0-{len(all_markets)-1})"
                    )
                    return False
            else:
                # Prompt for selection
                selected_idx = self._prompt_market_selection(all_markets)
                if selected_idx is None:
                    return False
            self.market = all_markets[selected_idx]
        else:
            self.market = all_markets[0]

        if not self.market:
            logger.error(f"Failed to fetch market: {self.market_slug}")
            return False

        # Extract token IDs and outcomes
        self.token_ids = self.market.metadata.get("clobTokenIds", [])
        self.outcomes = self.market.outcomes

        if not self.token_ids:
            logger.error("No token IDs found in market")
            return False

        # Get tick size from market
        self.tick_size = self.exchange.get_tick_size(self.market)

        # If tick size seems wrong (based on market prices), try to infer it
        # Check if prices use smaller increments
        for outcome, price in self.market.prices.items():
            if price > 0:
                # Check if price has more precision than tick_size
                price_str = f"{price:.4f}"
                if "." in price_str:
                    decimals = len(price_str.split(".")[1].rstrip("0"))
                    if decimals == 3:  # e.g., 0.021
                        self.tick_size = 0.001
                        logger.info("  Detected tick size: 0.001 (from market prices)")
                        break

        # Display market info
        logger.info(f"\n{Colors.bold('Market:')} {Colors.cyan(self.market.question)}")
        logger.info(
            f"Outcomes: {Colors.magenta(str(self.outcomes))} | Tick: {Colors.yellow(str(self.tick_size))} | Vol: {Colors.cyan(f'${self.market.volume:,.0f}')}"
        )

        for i, (outcome, token_id) in enumerate(zip(self.outcomes, self.token_ids)):
            price = self.market.prices.get(outcome, 0)
            logger.info(f"  [{i}] {Colors.magenta(outcome)}: {Colors.yellow(f'{price:.4f}')}")

        slug = self.market.metadata.get("slug", "")
        if slug:
            logger.info(f"URL: {Colors.gray(f'https://polymarket.com/event/{slug}')}")

        # Apply token filter or prompt for selection
        if self.token_filter is not None:
            filtered_idx = self._parse_token_filter(self.token_filter)
            if filtered_idx is None:
                return False
            self._apply_token_filter(filtered_idx)
        elif len(self.outcomes) > 2:
            # Multi-outcome market without filter - prompt user to select
            filtered_idx = self._prompt_token_selection()
            if filtered_idx is None:
                return False
            if filtered_idx >= 0:
                self._apply_token_filter(filtered_idx)
            # filtered_idx == -1 means "all tokens"

        return True

    def _parse_token_filter(self, token_filter: str) -> Optional[int]:
        """Parse token filter string and return index, or None if invalid"""
        # Try to parse as index first
        try:
            idx = int(token_filter)
            if 0 <= idx < len(self.outcomes):
                return idx
            else:
                logger.error(f"Token index {idx} out of range (0-{len(self.outcomes)-1})")
                return None
        except ValueError:
            # Not an index, try matching by name (case-insensitive)
            filter_lower = token_filter.lower()
            for i, outcome in enumerate(self.outcomes):
                if outcome.lower() == filter_lower or outcome.lower().startswith(filter_lower):
                    return i

            logger.error(f"Token '{token_filter}' not found. Available: {self.outcomes}")
            return None

    def _apply_token_filter(self, idx: int):
        """Filter to single token by index"""
        original_count = len(self.token_ids)
        self.outcomes = [self.outcomes[idx]]
        self.token_ids = [self.token_ids[idx]]
        logger.info(
            f"\n{Colors.bold('Token Filter:')} Trading only {Colors.magenta(self.outcomes[0])} (filtered from {original_count} tokens)"
        )

    def _prompt_market_selection(self, markets: List) -> Optional[int]:
        """Prompt user to select a market from multi-market event. Returns index or None for exit."""
        print(f"\n{Colors.bold('Event has multiple markets. Select one:')}")
        for i, market in enumerate(markets):
            question = market.question
            yes_price = market.prices.get("Yes", 0)
            print(f"  {Colors.cyan(str(i))} - Yes: {Colors.yellow(f'{yes_price:.2%}')}")
            print(f"      {Colors.magenta(question)}")
        print(f"  {Colors.cyan('q')} - Quit")

        while True:
            try:
                choice = input(f"\n{Colors.bold('Enter choice:')} ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                return None

            if choice == "q":
                return None

            try:
                idx = int(choice)
                if 0 <= idx < len(markets):
                    return idx
                print(f"  Invalid index. Enter 0-{len(markets)-1} or 'q' to quit.")
            except ValueError:
                print(f"  Invalid input. Enter 0-{len(markets)-1} or 'q' to quit.")

    def _prompt_token_selection(self) -> Optional[int]:
        """Prompt user to select a token interactively. Returns index or -1 for all, None for exit."""
        print(f"\n{Colors.bold('Select token to trade:')}")
        print(f"  {Colors.cyan('a')} - All tokens")
        for i, outcome in enumerate(self.outcomes):
            price = self.market.prices.get(outcome, 0)
            print(
                f"  {Colors.cyan(str(i))} - {Colors.magenta(outcome)} @ {Colors.yellow(f'{price:.4f}')}"
            )
        print(f"  {Colors.cyan('q')} - Quit")

        while True:
            try:
                choice = input(f"\n{Colors.bold('Enter choice:')} ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                return None

            if choice == "q":
                return None
            if choice == "a":
                return -1  # All tokens

            try:
                idx = int(choice)
                if 0 <= idx < len(self.outcomes):
                    return idx
                print(
                    f"  Invalid index. Enter 0-{len(self.outcomes)-1}, 'a' for all, or 'q' to quit."
                )
            except ValueError:
                print(
                    f"  Invalid input. Enter 0-{len(self.outcomes)-1}, 'a' for all, or 'q' to quit."
                )

    def setup_websocket(self):
        """Setup WebSocket connection using exchange interface"""
        # Get WebSocket from exchange
        self.ws = self.exchange.get_websocket()

        # Get orderbook manager
        self.orderbook_manager = self.ws.get_orderbook_manager()

    def setup_order_tracker(self):
        """Setup order fill tracking via WebSocket"""
        if not self.track_fills:
            return

        # Create order tracker
        self.order_tracker = OrderTracker(verbose=True)
        self.order_tracker.on_fill(create_fill_logger())

        # Get user WebSocket for trade notifications
        self.user_ws = self.exchange.get_user_websocket()
        self.user_ws.on_trade(self.order_tracker.handle_trade)
        self.user_ws.start()

        logger.info(f"Order fill tracking {Colors.green('enabled')} (WebSocket)")

    def on_order_fill(self, event: OrderEvent, order, fill_size: float):
        """Custom callback for order fills - override this for custom behavior"""
        pass

    def start_websocket(self):
        """Start WebSocket and subscribe to orderbooks"""
        # For binary markets, only subscribe to first token (Yes)
        # No token prices are calculated as inverse
        tokens_to_subscribe = [self.token_ids[0]] if len(self.token_ids) == 2 else self.token_ids

        logger.info(
            f"Starting WebSocket (subscribing to {len(tokens_to_subscribe)}/{len(self.token_ids)} tokens)..."
        )

        # Create event loop if needed
        if self.ws.loop is None:
            self.ws.loop = asyncio.new_event_loop()

        # Define subscription coroutine
        async def subscribe_all():
            await self.ws.connect()

            # Subscribe to market orderbooks (no callback needed, uses manager)
            await self.ws.watch_orderbook_by_market(self.market.id, tokens_to_subscribe)

            # Start receive loop
            await self.ws._receive_loop()

        # Run in background thread
        def run_loop():
            asyncio.set_event_loop(self.ws.loop)
            self.ws.loop.run_until_complete(subscribe_all())

        self.ws_thread = threading.Thread(target=run_loop, daemon=True)
        self.ws_thread.start()

        time.sleep(2)

    def stop_websocket(self):
        """Stop WebSocket connection"""
        if self.ws:
            self.ws.stop()
            if self.ws_thread:
                self.ws_thread.join(timeout=5)

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
            condition_id = self.market.metadata.get("conditionId", self.market.id)
            return self.exchange.fetch_open_orders(market_id=condition_id)
        except Exception as e:
            logger.warning(f"Failed to fetch open orders: {e}")
            return []

    def cancel_all_orders(self):
        """Cancel all open orders"""
        orders = self.get_open_orders()

        if not orders:
            return

        logger.info(f"Cancelling {Colors.cyan(str(len(orders)))} orders...")
        for order in orders:
            try:
                self.exchange.cancel_order(order.id, market_id=self.market.id)
            except Exception as e:
                logger.warning(f"  Failed to cancel {order.id}: {e}")

    def place_orders(self):
        """Main market making logic using orderbook manager"""
        # Get current positions
        positions = self.get_positions()
        open_orders = self.get_open_orders()

        # Calculate position metrics
        max_position_size = max(positions.values()) if positions else 0
        min_position_size = min(positions.values()) if positions else 0
        delta = max_position_size - min_position_size

        # Find which outcome has higher position for delta display
        delta_side = ""
        if delta > 0 and positions:
            max_outcome = max(positions, key=positions.get)
            delta_abbrev = max_outcome[0] if len(self.outcomes) == 2 else max_outcome
            delta_side = f" {Colors.magenta(delta_abbrev)}"

        # Create compact position string like "10 Y 5 N"
        pos_compact = ""
        if positions:
            # Abbreviate outcome names to first letter (Y/N for Yes/No, or full name if multi-outcome)
            parts = []
            for outcome, size in positions.items():
                abbrev = outcome[0] if len(self.outcomes) == 2 else outcome
                parts.append(f"{Colors.blue(f'{size:.0f}')} {Colors.magenta(abbrev)}")
            pos_compact = " ".join(parts)
        else:
            pos_compact = Colors.gray("None")

        # Calculate NAV
        nav_data = self.exchange.calculate_nav(self.market)
        nav = nav_data.nav
        cash = nav_data.cash

        logger.info(
            f"\n[{time.strftime('%H:%M:%S')}] {Colors.bold('NAV:')} {Colors.green(f'${nav:,.2f}')} | Cash: {Colors.cyan(f'${cash:,.2f}')} | Pos: {pos_compact} | Delta: {Colors.yellow(f'{delta:.1f}')}{delta_side} | Orders: {Colors.cyan(str(len(open_orders)))}"
        )

        # Display open orders if any
        if open_orders:
            for order in open_orders:
                side_colored = (
                    Colors.green(order.side.value.upper())
                    if order.side == OrderSide.BUY
                    else Colors.red(order.side.value.upper())
                )
                # Use original_size if available (some might show remaining size as 0)
                size_display = (
                    order.original_size
                    if hasattr(order, "original_size") and order.original_size
                    else order.size
                )
                logger.info(
                    f"  {Colors.gray('Open:')} {Colors.magenta(order.outcome)} {side_colored} {size_display:.0f} @ {Colors.yellow(f'{order.price:.4f}')}"
                )

        # Check delta risk
        if delta > self.max_delta:
            logger.warning(f"Delta ({delta:.2f}) > max ({self.max_delta:.2f}) - reducing exposure")

        for i, (outcome, token_id) in enumerate(zip(self.outcomes, self.token_ids)):
            # For binary markets, calculate inverse prices for second token
            if len(self.token_ids) == 2 and i == 1:
                # Get first token's orderbook
                first_bid, first_ask = self.orderbook_manager.get_best_bid_ask(self.token_ids[0])
                if first_bid is None or first_ask is None:
                    logger.warning(f"  {outcome}: No orderbook data, skipping...")
                    continue
                # Inverse prices: No bid = 1 - Yes ask, No ask = 1 - Yes bid
                best_bid = 1.0 - first_ask
                best_ask = 1.0 - first_bid
            else:
                # Get orderbook using manager
                best_bid, best_ask = self.orderbook_manager.get_best_bid_ask(token_id)

                if best_bid is None or best_ask is None:
                    logger.warning(f"  {outcome}: No orderbook data, skipping...")
                    continue

            # Calculate our prices (join the BBO - best bid/offer)
            # Market making strategy: match the best prices
            our_bid = best_bid  # Join the best bid
            our_ask = best_ask  # Join the best ask

            # Round to tick size (already should be, but ensure)
            our_bid = self.exchange.round_to_tick_size(our_bid, self.tick_size)
            our_ask = self.exchange.round_to_tick_size(our_ask, self.tick_size)

            # Sanity check: if bid >= ask, the spread is too tight
            if our_bid >= our_ask:
                logger.warning(
                    f"  {outcome}: Spread too tight (bid={our_bid:.4f} >= ask={our_ask:.4f}), skipping"
                )
                continue

            position_size = positions.get(outcome, 0)

            # Check existing orders
            outcome_orders = [o for o in open_orders if o.outcome == outcome]
            buy_orders = [o for o in outcome_orders if o.side == OrderSide.BUY]
            sell_orders = [o for o in outcome_orders if o.side == OrderSide.SELL]

            # Delta management
            if delta > self.max_delta and position_size == max_position_size:
                logger.info("    Skip: max position (delta mgmt)")
                continue

            # Place BUY order if needed
            should_place_buy = True
            if buy_orders:
                for order in buy_orders:
                    if abs(order.price - our_bid) < 0.001:
                        should_place_buy = False
                        break

                if should_place_buy:
                    for order in buy_orders:
                        try:
                            self.exchange.cancel_order(order.id)
                            logger.info(
                                f"    {Colors.gray('✕ Cancel')} {Colors.green('BUY')} @ {Colors.yellow(f'{order.price:.4f}')}"
                            )
                        except Exception:
                            pass

            if position_size + self.order_size > self.max_position:
                should_place_buy = False

            if should_place_buy:
                try:
                    order = self.exchange.create_order(
                        market_id=self.market.id,
                        outcome=outcome,
                        side=OrderSide.BUY,
                        price=our_bid,
                        size=self.order_size,
                        params={"token_id": token_id},
                    )
                    # Track the order for fill detection
                    if self.order_tracker:
                        self.order_tracker.track_order(order)
                    logger.info(
                        f"    {Colors.gray('→')} {Colors.green('BUY')} {self.order_size:.0f} {Colors.magenta(outcome)} @ {Colors.yellow(f'{our_bid:.4f}')}"
                    )
                except Exception as e:
                    logger.error(f"    BUY failed: {e}")

            # Place SELL order if needed
            should_place_sell = True
            if sell_orders:
                for order in sell_orders:
                    if abs(order.price - our_ask) < 0.001:
                        should_place_sell = False
                        break

                if should_place_sell:
                    for order in sell_orders:
                        try:
                            self.exchange.cancel_order(order.id)
                            logger.info(
                                f"    {Colors.gray('✕ Cancel')} {Colors.red('SELL')} @ {Colors.yellow(f'{order.price:.4f}')}"
                            )
                        except Exception:
                            pass

            if position_size < self.order_size:
                should_place_sell = False

            if should_place_sell:
                try:
                    order = self.exchange.create_order(
                        market_id=self.market.id,
                        outcome=outcome,
                        side=OrderSide.SELL,
                        price=our_ask,
                        size=self.order_size,
                        params={"token_id": token_id},
                    )
                    # Track the order for fill detection
                    if self.order_tracker:
                        self.order_tracker.track_order(order)
                    logger.info(
                        f"    {Colors.gray('→')} {Colors.red('SELL')} {self.order_size:.0f} {Colors.magenta(outcome)} @ {Colors.yellow(f'{our_ask:.4f}')}"
                    )
                except Exception as e:
                    logger.error(f"    SELL failed: {e}")

    def run(self, duration_minutes: Optional[int] = None):
        """Run the market making bot"""
        logger.info(
            f"\n{Colors.bold('Market Maker:')} {Colors.cyan('BBO Strategy')} | MaxPos: {Colors.blue(f'{self.max_position:.0f}')} | Size: {Colors.yellow(f'{self.order_size:.0f}')} | MaxDelta: {Colors.yellow(f'{self.max_delta:.0f}')} | Interval: {Colors.gray(f'{self.check_interval}s')}"
        )

        # Fetch market using exchange interface
        if not self.fetch_market():
            logger.error("Failed to fetch market. Exiting.")
            return

        # Setup order fill tracking
        self.setup_order_tracker()

        # Setup and start WebSocket
        self.setup_websocket()
        self.start_websocket()

        # Wait for initial orderbook data
        time.sleep(5)

        # For binary markets, only check first token
        tokens_to_check = [self.token_ids[0]] if len(self.token_ids) == 2 else self.token_ids

        # Check if we got data using manager
        if self.orderbook_manager.has_all_data(tokens_to_check):
            # Infer tick size from orderbook if needed
            if self.tick_size == 0.01:
                orderbook = self.orderbook_manager.get(self.token_ids[0])
                if orderbook:
                    bids = orderbook.get("bids", [])
                    asks = orderbook.get("asks", [])
                    for price, size in bids + asks:
                        # Check if price uses finer granularity
                        if price % 0.01 != 0:
                            self.tick_size = 0.001
                            logger.info("Detected tick size: 0.001 (from orderbook)")
                            break
        else:
            logger.warning("Missing orderbook data")

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
            logger.info("\nStopping...")

        finally:
            self.is_running = False
            self.cancel_all_orders()
            self.stop_websocket()
            if self.user_ws:
                self.user_ws.stop()
            if self.order_tracker:
                self.order_tracker.stop()
            logger.info("Market maker stopped")


def main():
    load_dotenv()

    private_key = os.getenv("POLYMARKET_PRIVATE_KEY")
    funder = os.getenv("POLYMARKET_FUNDER")

    if not private_key or not funder:
        logger.error("Missing environment variables!")
        logger.error("Set POLYMARKET_PRIVATE_KEY and POLYMARKET_FUNDER in .env")
        return 1

    # Parse command line arguments
    market_slug = os.getenv("MARKET_SLUG", "")
    market_index = None

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--market" and i + 1 < len(args):
            try:
                market_index = int(args[i + 1])
            except ValueError:
                logger.error(f"Invalid market index: {args[i + 1]}")
                return 1
            i += 2
        elif not args[i].startswith("--"):
            market_slug = args[i]
            i += 1
        else:
            i += 1

    if not market_slug:
        logger.error("No market slug provided!")
        logger.error("\nUsage:")
        logger.error("  uv run python examples/spread_strategy.py MARKET_SLUG")
        logger.error(
            "  uv run python examples/spread_strategy.py MARKET_SLUG --market 0  # select market in multi-market event"
        )
        logger.error("\nExample slugs:")
        logger.error("  fed-decision-in-december")
        logger.error("  what-day-will-openai-release-a-new-frontier-model")
        return 1

    # Create exchange
    exchange = dr_manhattan.Polymarket(
        {"private_key": private_key, "funder": funder, "cache_ttl": 2.0, "verbose": True}
    )

    # Display trader profile
    logger.info(f"\n{Colors.bold('Trader Profile')}")
    logger.info(f"Address: {Colors.cyan(exchange._address or 'Unknown')}")
    try:
        balance = exchange.fetch_balance()
        usdc = balance.get("USDC", 0.0)
        logger.info(f"Balance: {Colors.green(f'${usdc:,.2f}')} USDC")
    except Exception as e:
        logger.warning(f"Failed to fetch balance: {e}")

    # Create and run market maker
    mm = SpreadStrategy(
        exchange=exchange,
        market_slug=market_slug,
        max_position=100.0,
        order_size=5.0,
        max_delta=20.0,
        check_interval=5.0,
        market_index=market_index,
    )

    mm.run(duration_minutes=None)

    return 0


if __name__ == "__main__":
    sys.exit(main())
