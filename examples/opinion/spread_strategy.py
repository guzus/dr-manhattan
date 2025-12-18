"""
Market Making Example for Opinion

Simple spread strategy using REST API polling (no WebSocket).

Usage:
    uv run python examples/opinion/spread_strategy.py MARKET_ID

    # Via environment variable
    OPINION_MARKET_ID="123" uv run python examples/opinion/spread_strategy.py
"""

import os
import sys
import time
from typing import Dict, List, Optional

from dotenv import load_dotenv

import dr_manhattan
from dr_manhattan.models import OrderSide
from dr_manhattan.base.order_tracker import OrderTracker, OrderEvent, create_fill_logger
from dr_manhattan.utils import setup_logger
from dr_manhattan.utils.logger import Colors

logger = setup_logger(__name__)


class SpreadStrategy:
    """
    Simple market maker using REST API polling.

    Note: Opinion does not provide WebSocket API yet.
    This strategy polls orderbook via REST API.
    """

    def __init__(
        self,
        exchange: dr_manhattan.Opinion,
        market_id: str,
        max_position: float = 100.0,
        order_size: float = 5.0,
        max_delta: float = 20.0,
        check_interval: float = 5.0,
        track_fills: bool = True,
    ):
        """
        Initialize market maker

        Args:
            exchange: Opinion exchange instance
            market_id: Market ID (numeric)
            max_position: Maximum position size per outcome
            order_size: Size of each order
            max_delta: Maximum position imbalance
            check_interval: How often to check and adjust orders
            track_fills: Enable order fill tracking and logging
        """
        self.exchange = exchange
        self.market_id = market_id
        self.max_position = max_position
        self.order_size = order_size
        self.max_delta = max_delta
        self.check_interval = check_interval
        self.track_fills = track_fills

        self.market = None
        self.token_ids = []
        self.outcomes = []
        self.tick_size = 0.01
        self.child_market_ids = {}  # outcome -> child market_id

        # Order tracking
        self.order_tracker: Optional[OrderTracker] = None

        self.is_running = False

    def fetch_market(self) -> bool:
        """Fetch market data"""
        logger.info(f"Fetching market: {self.market_id}")

        try:
            self.market = self.exchange.fetch_market(self.market_id)
        except Exception as e:
            logger.error(f"Failed to fetch market: {e}")
            return False

        if not self.market:
            logger.error(f"Market not found: {self.market_id}")
            return False

        self.token_ids = self.market.metadata.get("clobTokenIds", [])
        self.outcomes = self.market.outcomes

        if not self.token_ids:
            logger.error("No token IDs found in market")
            return False

        # Opinion tick_size = 0.001
        self.tick_size = 0.001

        # For multi-outcome markets, map outcome -> child market_id
        child_markets = self.market.metadata.get("child_markets", [])
        if child_markets:
            for child in child_markets:
                self.child_market_ids[child["title"]] = child["market_id"]
            logger.info(f"Multi-outcome market detected. Child markets: {self.child_market_ids}")

        # Display fetch confirmation
        question_short = self.market.question[:60] + "..." if len(self.market.question) > 60 else self.market.question
        logger.info(f"Fetched market: {question_short}")
        logger.info(f"  Market ID: {self.market_id}")
        logger.info(f"  Outcomes: {len(self.outcomes)}")
        logger.info(f"  Token IDs: {len(self.token_ids)}")
        logger.info(f"  Tick size: {self.tick_size}")

        # Display market info
        logger.info(f"\n{Colors.bold('Market:')} {Colors.cyan(self.market.question)}")
        logger.info(f"Outcomes: {Colors.magenta(str(self.outcomes))} | Tick: {Colors.yellow(str(self.tick_size))} | Vol: {Colors.cyan(f'${self.market.volume:,.0f}')}")

        for i, (outcome, token_id) in enumerate(zip(self.outcomes, self.token_ids)):
            price = self.market.prices.get(outcome, 0)
            # Truncate long outcome names
            outcome_display = outcome[:30] + "..." if len(outcome) > 30 else outcome
            logger.info(f"  [{i}] {Colors.magenta(outcome_display)}: {Colors.yellow(f'{price:.4f}')}")

        logger.info(f"URL: {Colors.gray(f'https://app.opinion.trade/detail?topicId={self.market_id}')}")

        return True

    def get_orderbook(self, token_id: str) -> Dict:
        """Fetch orderbook via REST API"""
        try:
            return self.exchange.get_orderbook(token_id)
        except Exception as e:
            logger.warning(f"Failed to fetch orderbook: {e}")
            return {"bids": [], "asks": []}

    def get_best_bid_ask(self, token_id: str) -> tuple:
        """Get best bid and ask from orderbook"""
        orderbook = self.get_orderbook(token_id)

        bids = orderbook.get("bids", [])
        asks = orderbook.get("asks", [])

        best_bid = float(bids[0]["price"]) if bids else None
        best_ask = float(asks[0]["price"]) if asks else None

        return best_bid, best_ask

    def get_positions(self) -> Dict[str, float]:
        """Get current positions"""
        positions = {}

        try:
            # For multi-outcome markets, fetch from all child markets
            if self.child_market_ids:
                for outcome, child_id in self.child_market_ids.items():
                    positions_list = self.exchange.fetch_positions(market_id=child_id)
                    for pos in positions_list:
                        positions[outcome] = pos.size
            else:
                positions_list = self.exchange.fetch_positions(market_id=self.market_id)
                for pos in positions_list:
                    positions[pos.outcome] = pos.size
        except Exception as e:
            logger.warning(f"Failed to fetch positions: {e}")

        return positions

    def get_open_orders(self) -> List:
        """Get all open orders"""
        try:
            # For multi-outcome markets, fetch from all child markets
            if self.child_market_ids:
                all_orders = []
                for outcome, child_id in self.child_market_ids.items():
                    orders = self.exchange.fetch_open_orders(market_id=child_id)
                    for order in orders:
                        order.outcome = outcome  # Set outcome for reference
                    all_orders.extend(orders)
                return all_orders
            return self.exchange.fetch_open_orders(market_id=self.market_id)
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
                self.exchange.cancel_order(order.id, market_id=self.market_id)
            except Exception as e:
                logger.warning(f"  Failed to cancel {order.id}: {e}")

    def liquidate_positions(self):
        """Liquidate all positions by selling at best bid"""
        positions = self.get_positions()

        if not positions:
            logger.info("No positions to liquidate")
            return

        logger.info(f"{Colors.bold('Liquidating positions...')}")

        for outcome, size in positions.items():
            if size <= 0:
                continue

            # Find token_id for this outcome
            token_id = None
            for i, out in enumerate(self.outcomes):
                if out == outcome and i < len(self.token_ids):
                    token_id = self.token_ids[i]
                    break

            if not token_id:
                logger.warning(f"  Cannot find token_id for {outcome}")
                continue

            # Get best bid
            best_bid, _ = self.get_best_bid_ask(token_id)

            if best_bid is None or best_bid <= 0:
                logger.warning(f"  {outcome}: No bid available, cannot liquidate")
                continue

            # Sell at best bid
            try:
                # Use child market_id for multi-outcome markets
                order_market_id = self.child_market_ids.get(outcome, self.market_id)
                # Floor the size to avoid insufficient balance errors
                sell_size = float(int(size))  # Floor to integer
                if sell_size <= 0:
                    continue
                order = self.exchange.create_order(
                    market_id=order_market_id,
                    outcome=outcome,
                    side=OrderSide.SELL,
                    price=self.round_price(best_bid),
                    size=sell_size,
                    params={"token_id": token_id},
                )
                outcome_display = outcome[:15] if len(outcome) > 15 else outcome
                logger.info(f"  {Colors.red('SELL')} {sell_size:.2f} {Colors.magenta(outcome_display)} @ {Colors.yellow(f'{best_bid:.4f}')} (liquidate)")
            except Exception as e:
                logger.error(f"  Failed to liquidate {outcome}: {e}")

    def round_price(self, price: float) -> float:
        """Round price to tick size"""
        return round(round(price / self.tick_size) * self.tick_size, 3)

    def setup_order_tracker(self):
        """Setup order fill tracking via polling (no WebSocket)"""
        if not self.track_fills:
            return

        self.order_tracker = OrderTracker(verbose=True)
        self.order_tracker.on_fill(create_fill_logger())
        logger.info(f"Order fill tracking {Colors.green('enabled')} (polling)")

    def place_orders(self):
        """Main market making logic"""
        positions = self.get_positions()
        open_orders = self.get_open_orders()

        # Calculate metrics
        total_position = sum(positions.values())
        max_pos = max(positions.values()) if positions else 0
        min_pos = min(positions.values()) if positions else 0
        delta = max_pos - min_pos

        # Find which outcome has higher position for delta display
        delta_side = ""
        if delta > 0 and positions:
            max_outcome = max(positions, key=positions.get)
            # For multi-outcome, show first few chars
            delta_abbrev = max_outcome[:8] if len(self.outcomes) > 2 else max_outcome[0]
            delta_side = f" {Colors.magenta(delta_abbrev)}"

        # Create compact position string
        pos_compact = ""
        if positions:
            parts = []
            for outcome, size in positions.items():
                # Abbreviate outcome names
                abbrev = outcome[:8] if len(self.outcomes) > 2 else outcome[0]
                parts.append(f"{Colors.blue(f'{size:.0f}')} {Colors.magenta(abbrev)}")
            pos_compact = " ".join(parts)
        else:
            pos_compact = Colors.gray("None")

        # Calculate NAV
        try:
            nav_data = self.exchange.calculate_nav(self.market)
            nav = nav_data.nav
            cash = nav_data.cash
        except Exception:
            nav = 0.0
            cash = 0.0

        logger.info(f"\n[{time.strftime('%H:%M:%S')}] {Colors.bold('NAV:')} {Colors.green(f'${nav:,.2f}')} | Cash: {Colors.cyan(f'${cash:,.2f}')} | Pos: {pos_compact} | Delta: {Colors.yellow(f'{delta:.1f}')}{delta_side} | Orders: {Colors.cyan(str(len(open_orders)))}")

        # Display open orders if any
        if open_orders:
            for order in open_orders:
                side_colored = Colors.green(order.side.value.upper()) if order.side == OrderSide.BUY else Colors.red(order.side.value.upper())
                outcome_display = order.outcome[:15] if len(order.outcome) > 15 else order.outcome
                logger.info(f"  {Colors.gray('Open:')} {Colors.magenta(outcome_display)} {side_colored} {order.size:.0f} @ {Colors.yellow(f'{order.price:.4f}')}")

        # Check delta risk
        if delta > self.max_delta:
            logger.warning(f"Delta ({delta:.2f}) > max ({self.max_delta:.2f}) - reducing exposure")

        for i, (outcome, token_id) in enumerate(zip(self.outcomes, self.token_ids)):
            # Opinion has separate orderbooks for each token, so fetch directly
            best_bid, best_ask = self.get_best_bid_ask(token_id)

            if best_bid is None or best_ask is None:
                outcome_display = outcome[:20] if len(outcome) > 20 else outcome
                logger.warning(f"  {outcome_display}: No orderbook data, skipping...")
                continue

            # Our prices (join BBO - round to tick size)
            our_bid = self.round_price(best_bid)
            our_ask = self.round_price(best_ask)

            # Validate (Opinion allows 0.001 ~ 0.999)
            our_bid = max(0.001, min(0.999, our_bid))
            our_ask = max(0.001, min(0.999, our_ask))

            if our_bid >= our_ask:
                logger.warning(f"  {outcome}: Spread too tight (bid={our_bid:.4f} >= ask={our_ask:.4f}), skipping")
                continue

            position_size = positions.get(outcome, 0)

            # Check existing orders
            outcome_orders = [o for o in open_orders if o.outcome == outcome]
            buy_orders = [o for o in outcome_orders if o.side == OrderSide.BUY]
            sell_orders = [o for o in outcome_orders if o.side == OrderSide.SELL]

            # Delta management
            if delta > self.max_delta and position_size == max_pos:
                logger.info(f"    Skip: max position (delta mgmt)")
                continue

            # Place BUY
            should_buy = True
            for order in buy_orders:
                if abs(order.price - our_bid) < 0.001:
                    should_buy = False
                    break

            if should_buy and buy_orders:
                for order in buy_orders:
                    try:
                        self.exchange.cancel_order(order.id)
                        logger.info(f"    {Colors.gray('✕ Cancel')} {Colors.green('BUY')} @ {Colors.yellow(f'{order.price:.4f}')}")
                    except:
                        pass

            if position_size + self.order_size > self.max_position:
                should_buy = False

            if should_buy:
                try:
                    # Use child market_id for multi-outcome markets
                    order_market_id = self.child_market_ids.get(outcome, self.market_id)
                    # BUY size is in USDT (makerAmountInQuoteToken)
                    # Minimum order amount is 1.30 USDT
                    min_order_amount = 1.30
                    buy_amount = max(self.order_size, min_order_amount)
                    # Don't exceed available cash
                    if buy_amount > cash:
                        continue
                    order = self.exchange.create_order(
                        market_id=order_market_id,
                        outcome=outcome,
                        side=OrderSide.BUY,
                        price=our_bid,
                        size=buy_amount,
                        params={"token_id": token_id},
                    )
                    # Track the order for fill detection
                    if self.order_tracker:
                        self.order_tracker.track_order(order)
                    outcome_display = outcome[:15] if len(outcome) > 15 else outcome
                    logger.info(f"    {Colors.gray('→')} {Colors.green('BUY')} ${buy_amount:.2f} {Colors.magenta(outcome_display)} @ {Colors.yellow(f'{our_bid:.4f}')}")
                except Exception as e:
                    logger.error(f"    BUY failed: {e}")

            # Place SELL
            should_sell = True
            for order in sell_orders:
                if abs(order.price - our_ask) < 0.001:
                    should_sell = False
                    break

            if should_sell and sell_orders:
                for order in sell_orders:
                    try:
                        self.exchange.cancel_order(order.id)
                        logger.info(f"    {Colors.gray('✕ Cancel')} {Colors.red('SELL')} @ {Colors.yellow(f'{order.price:.4f}')}")
                    except:
                        pass

            if position_size < self.order_size:
                should_sell = False

            if should_sell:
                try:
                    # Use child market_id for multi-outcome markets
                    order_market_id = self.child_market_ids.get(outcome, self.market_id)
                    # Calculate size to meet minimum order amount (1.30 USDT)
                    min_order_amount = 1.30
                    sell_size = max(self.order_size, int(min_order_amount / our_ask) + 1)
                    # Don't sell more than we have
                    sell_size = min(sell_size, position_size)
                    order = self.exchange.create_order(
                        market_id=order_market_id,
                        outcome=outcome,
                        side=OrderSide.SELL,
                        price=our_ask,
                        size=sell_size,
                        params={"token_id": token_id},
                    )
                    # Track the order for fill detection
                    if self.order_tracker:
                        self.order_tracker.track_order(order)
                    outcome_display = outcome[:15] if len(outcome) > 15 else outcome
                    logger.info(f"    {Colors.gray('→')} {Colors.red('SELL')} {sell_size:.0f} {Colors.magenta(outcome_display)} @ {Colors.yellow(f'{our_ask:.4f}')}")
                except Exception as e:
                    logger.error(f"    SELL failed: {e}")

    def run(self, duration_minutes: Optional[int] = None):
        """Run the market making bot"""
        logger.info(f"\n{Colors.bold('Market Maker:')} {Colors.cyan('BBO Strategy')} | MaxPos: {Colors.blue(f'{self.max_position:.0f}')} | Size: {Colors.yellow(f'{self.order_size:.0f}')} | MaxDelta: {Colors.yellow(f'{self.max_delta:.0f}')} | Interval: {Colors.gray(f'{self.check_interval}s')}")

        if not self.fetch_market():
            logger.error("Failed to fetch market. Exiting.")
            return

        # Setup order fill tracking
        self.setup_order_tracker()

        self.is_running = True
        start_time = time.time()
        end_time = start_time + (duration_minutes * 60) if duration_minutes else None

        try:
            while self.is_running:
                if end_time and time.time() >= end_time:
                    break

                self.place_orders()
                time.sleep(self.check_interval)

        except KeyboardInterrupt:
            logger.info("\nStopping...")

        finally:
            self.is_running = False
            self.cancel_all_orders()
            self.liquidate_positions()
            if self.order_tracker:
                self.order_tracker.stop()
            logger.info("Market maker stopped")


def find_market_by_slug(exchange: dr_manhattan.Opinion, slug: str) -> Optional[str]:
    """
    Find market ID by searching with slug/keyword.

    Args:
        exchange: Opinion exchange instance
        slug: Search keyword or slug (e.g., "bnb-all-time-high-by-december-31")

    Returns:
        Market ID if found, None otherwise
    """
    logger.info(f"Searching for market: {slug}")

    # Convert slug to search keywords (replace hyphens with spaces)
    keywords = slug.replace("-", " ").lower()

    # Search through multiple pages to find the market
    all_markets = []
    for page in range(1, 6):  # Search up to 5 pages
        try:
            markets = exchange.fetch_markets({"page": page, "limit": 20})
            if not markets:
                break
            all_markets.extend(markets)
        except Exception:
            break

    # Filter markets by keywords
    matching = []
    for m in all_markets:
        question_lower = m.question.lower()
        # Check if all significant keywords match
        keyword_parts = [k for k in keywords.split() if len(k) > 2]
        if all(k in question_lower for k in keyword_parts):
            matching.append(m)

    if not matching:
        logger.error(f"No markets found for: {slug}")
        logger.info(f"Searched {len(all_markets)} markets")
        return None

    # If only one result, use it
    if len(matching) == 1:
        logger.info(f"Found market: {matching[0].question}")
        return matching[0].id

    # Multiple results - show them and pick the first
    logger.info(f"Found {len(matching)} markets:")
    for i, m in enumerate(matching[:5]):
        question_short = m.question[:50] + "..." if len(m.question) > 50 else m.question
        logger.info(f"  [{i}] ID={m.id}: {question_short}")

    # Use the first one
    logger.info(f"Using first match: {matching[0].question}")
    return matching[0].id


def main():
    load_dotenv()

    api_key = os.getenv("OPINION_API_KEY")
    private_key = os.getenv("OPINION_PRIVATE_KEY")
    multi_sig_addr = os.getenv("OPINION_MULTI_SIG_ADDR")

    if not api_key or not private_key or not multi_sig_addr:
        logger.error("Missing environment variables!")
        logger.error("Set in .env file:")
        logger.error("  OPINION_API_KEY=...")
        logger.error("  OPINION_PRIVATE_KEY=...")
        logger.error("  OPINION_MULTI_SIG_ADDR=...")
        return 1

    # Get market ID or slug (support both OPINION_MARKET_ID and MARKET_SLUG)
    market_id = os.getenv("OPINION_MARKET_ID", "")
    market_slug = os.getenv("MARKET_SLUG", "") or os.getenv("OPINION_MARKET_SLUG", "")

    if len(sys.argv) > 1:
        arg = sys.argv[1]
        # If numeric, treat as market ID; otherwise treat as slug
        if arg.isdigit():
            market_id = arg
        else:
            market_slug = arg

    if not market_id and not market_slug:
        logger.error("No market ID or slug provided!")
        logger.error("\nUsage:")
        logger.error("  uv run python examples/opinion/spread_strategy.py MARKET_ID")
        logger.error("  uv run python examples/opinion/spread_strategy.py SEARCH_KEYWORD")
        logger.error("  OPINION_MARKET_ID=123 uv run python examples/opinion/spread_strategy.py")
        logger.error("  MARKET_SLUG=bnb-all-time-high uv run python examples/opinion/spread_strategy.py")
        logger.error("\nExamples:")
        logger.error("  OPINION_MARKET_ID=813 uv run python examples/opinion/spread_strategy.py")
        logger.error("  MARKET_SLUG=bitcoin uv run python examples/opinion/spread_strategy.py")
        return 1

    # Create exchange
    exchange = dr_manhattan.Opinion(
        {
            "api_key": api_key,
            "private_key": private_key,
            "multi_sig_addr": multi_sig_addr,
            "verbose": True,
        }
    )

    # If slug provided, search for market ID
    if market_slug and not market_id:
        market_id = find_market_by_slug(exchange, market_slug)
        if not market_id:
            return 1

    # Create and run
    mm = SpreadStrategy(
        exchange=exchange,
        market_id=market_id,
        max_position=100.0,
        order_size=5.0,
        max_delta=20.0,
        check_interval=5.0,
    )

    mm.run(duration_minutes=None)

    return 0


if __name__ == "__main__":
    sys.exit(main())
