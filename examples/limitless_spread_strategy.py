"""
Market Making Example for Limitless

High-performance market making using exchange interfaces and REST API orderbook updates.

Usage:
    # Using market slug
    uv run python examples/limitless_spread_strategy.py will-btc-reach-100k

    # Using environment variable
    LIMITLESS_MARKET_SLUG=will-btc-reach-100k uv run python examples/limitless_spread_strategy.py
"""

import os
import sys
import time
from typing import Dict, List, Optional

from dotenv import load_dotenv

import dr_manhattan
from dr_manhattan.models import OrderSide
from dr_manhattan.utils import setup_logger
from dr_manhattan.utils.logger import Colors

logger = setup_logger(__name__)


class LimitlessSpreadStrategy:
    """
    Market maker for Limitless prediction markets.

    Uses REST API for orderbook data and places orders to capture spread.
    Supports binary markets (Yes/No outcomes).
    """

    def __init__(
        self,
        exchange: dr_manhattan.Limitless,
        market_slug: str,
        max_position: float = 100.0,
        order_size: float = 5.0,
        max_delta: float = 20.0,
        check_interval: float = 10.0,
        spread_buffer: float = 0.01,
    ):
        """
        Initialize market maker.

        Args:
            exchange: Limitless exchange instance
            market_slug: Market slug to trade
            max_position: Maximum position size per outcome
            order_size: Size of each order
            max_delta: Maximum position imbalance
            check_interval: How often to check and adjust orders (seconds)
            spread_buffer: Minimum spread to maintain (e.g., 0.01 = 1%)
        """
        self.exchange = exchange
        self.market_slug = market_slug
        self.max_position = max_position
        self.order_size = order_size
        self.max_delta = max_delta
        self.check_interval = check_interval
        self.spread_buffer = spread_buffer

        # Market data
        self.market = None
        self.token_ids = []
        self.outcomes = []
        self.tick_size = 0.01

        self.is_running = False

    def fetch_market(self) -> bool:
        """
        Fetch market data using exchange interface.

        Returns:
            True if successful, False otherwise
        """
        logger.info(f"Fetching market: {self.market_slug}")

        try:
            markets = self.exchange.fetch_markets_by_slug(self.market_slug)

            if not markets:
                logger.error(f"Market not found: {self.market_slug}")
                return False

            self.market = markets[0]

        except Exception as e:
            logger.error(f"Failed to fetch market: {e}")
            return False

        # Check if market is CLOB (orderbook) type
        trade_type = self.market.metadata.get("tradeType", "")
        if trade_type != "clob":
            logger.error(
                f"Market is not CLOB type (tradeType={trade_type}). Only CLOB markets are supported."
            )
            return False

        # Extract token IDs and outcomes
        self.token_ids = self.market.metadata.get("clobTokenIds", [])
        self.outcomes = self.market.outcomes
        self.tick_size = self.market.metadata.get("tick_size", 0.01)

        if not self.token_ids:
            logger.warning("No token IDs found - orderbook features limited")

        # Display market info
        logger.info(f"\n{Colors.bold('Market:')} {Colors.cyan(self.market.question)}")
        logger.info(
            f"Outcomes: {Colors.magenta(str(self.outcomes))} | "
            f"Tick: {Colors.yellow(str(self.tick_size))} | "
            f"Vol: {Colors.cyan(f'${self.market.volume:,.0f}')}"
        )

        for i, outcome in enumerate(self.outcomes):
            price = self.market.prices.get(outcome, 0)
            token_id = self.token_ids[i] if i < len(self.token_ids) else "N/A"
            logger.info(
                f"  [{i}] {Colors.magenta(outcome)}: "
                f"{Colors.yellow(f'{price:.4f}')} "
                f"({Colors.gray(token_id[:16] + '...' if len(token_id) > 16 else token_id)})"
            )

        slug = self.market.metadata.get("slug", self.market.id)
        logger.info(f"URL: {Colors.gray(f'https://limitless.exchange/markets/{slug}')}")

        return True

    def get_orderbook_prices(self) -> Dict[str, tuple]:
        """
        Get best bid/ask prices from orderbook.

        Returns:
            Dictionary mapping outcome to (best_bid, best_ask) tuple
        """
        prices = {}

        try:
            orderbook = self.exchange.get_orderbook(self.market_slug)

            bids = orderbook.get("bids", [])
            asks = orderbook.get("asks", [])

            best_bid = float(bids[0]["price"]) if bids else None
            best_ask = float(asks[0]["price"]) if asks else None

            # For binary markets: Yes prices from orderbook, No = 1 - Yes
            prices["Yes"] = (best_bid, best_ask)

            if best_bid is not None and best_ask is not None:
                prices["No"] = (1.0 - best_ask, 1.0 - best_bid)
            else:
                prices["No"] = (None, None)

        except Exception as e:
            if self.exchange.verbose:
                logger.warning(f"Failed to fetch orderbook: {e}")

            # Fallback to market prices
            for outcome in self.outcomes:
                price = self.market.prices.get(outcome, 0.5)
                prices[outcome] = (price - 0.02, price + 0.02)

        return prices

    def get_positions(self) -> Dict[str, float]:
        """
        Get current positions.

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
        Get all open orders.

        Returns:
            List of open orders
        """
        try:
            return self.exchange.fetch_open_orders(market_id=self.market.id)
        except Exception as e:
            logger.warning(f"Failed to fetch open orders: {e}")
            return []

    def cancel_all_orders(self):
        """Cancel all open orders."""
        try:
            self.exchange.cancel_all_orders(market_id=self.market.id)
            logger.info("Cancelled all orders")
        except Exception as e:
            # Fallback: cancel individually
            orders = self.get_open_orders()
            if orders:
                logger.info(f"Cancelling {Colors.cyan(str(len(orders)))} orders...")
                for order in orders:
                    try:
                        self.exchange.cancel_order(order.id, market_id=self.market.id)
                    except Exception as cancel_err:
                        logger.warning(f"  Failed to cancel {order.id}: {cancel_err}")

    def round_price(self, price: float) -> float:
        """Round price to tick size."""
        return round(round(price / self.tick_size) * self.tick_size, 4)

    def liquidate_positions(self):
        """Liquidate all positions by selling at best bid."""
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

            # Get best bid from orderbook
            orderbook_prices = self.get_orderbook_prices()
            bid_ask = orderbook_prices.get(outcome, (None, None))
            best_bid = bid_ask[0]

            if best_bid is None or best_bid <= 0:
                logger.warning(f"  {outcome}: No bid available, cannot liquidate")
                continue

            # Sell at best bid
            try:
                # Floor the size to avoid insufficient balance errors
                sell_size = float(int(size))
                if sell_size <= 0:
                    continue
                order = self.exchange.create_order(
                    market_id=self.market.id,
                    outcome=outcome,
                    side=OrderSide.SELL,
                    price=self.round_price(best_bid),
                    size=sell_size,
                    params={"token_id": token_id},
                )
                logger.info(
                    f"  {Colors.red('SELL')} {sell_size:.0f} {Colors.magenta(outcome)} "
                    f"@ {Colors.yellow(f'{best_bid:.4f}')} (liquidate)"
                )
            except Exception as e:
                logger.error(f"  Failed to liquidate {outcome}: {e}")

    def place_orders(self):
        """Main market making logic."""
        # Refresh market data
        try:
            self.market = self.exchange.fetch_market(self.market_slug)
        except Exception as e:
            logger.warning(f"Failed to refresh market: {e}")

        # Get current state
        positions = self.get_positions()
        open_orders = self.get_open_orders()
        orderbook_prices = self.get_orderbook_prices()

        # Calculate position metrics
        max_position_size = max(positions.values()) if positions else 0
        min_position_size = min(positions.values()) if positions else 0
        delta = max_position_size - min_position_size

        # Find which outcome has higher position for delta display
        delta_side = ""
        if delta > 0 and positions:
            max_outcome = max(positions, key=positions.get)
            if max_outcome:
                delta_abbrev = max_outcome[0] if len(self.outcomes) == 2 else max_outcome
            else:
                delta_abbrev = "?"
            delta_side = f" {Colors.magenta(delta_abbrev)}"

        # Create compact position string
        pos_compact = ""
        if positions:
            parts = []
            for outcome, size in positions.items():
                if outcome:
                    abbrev = outcome[0] if len(self.outcomes) == 2 else outcome
                else:
                    abbrev = "?"
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
            nav = 0
            cash = 0

        logger.info(
            f"\n[{time.strftime('%H:%M:%S')}] "
            f"{Colors.bold('NAV:')} {Colors.green(f'${nav:,.2f}')} | "
            f"Cash: {Colors.cyan(f'${cash:,.2f}')} | "
            f"Pos: {pos_compact} | "
            f"Delta: {Colors.yellow(f'{delta:.1f}')}{delta_side} | "
            f"Orders: {Colors.cyan(str(len(open_orders)))}"
        )

        # Display open orders
        if open_orders:
            for order in open_orders:
                side_colored = (
                    Colors.green(order.side.value.upper())
                    if order.side == OrderSide.BUY
                    else Colors.red(order.side.value.upper())
                )
                logger.info(
                    f"  {Colors.gray('Open:')} "
                    f"{Colors.magenta(order.outcome)} {side_colored} "
                    f"{order.size:.0f} @ {Colors.yellow(f'{order.price:.4f}')}"
                )

        # Check delta risk
        if delta > self.max_delta:
            logger.warning(f"Delta ({delta:.2f}) > max ({self.max_delta:.2f}) - reducing exposure")

        # Place orders for each outcome
        for i, outcome in enumerate(self.outcomes):
            bid_ask = orderbook_prices.get(outcome, (None, None))
            best_bid, best_ask = bid_ask

            if best_bid is None or best_ask is None:
                logger.warning(f"  {outcome}: No orderbook data, skipping...")
                continue

            # Calculate our prices with spread buffer
            our_bid = self.round_price(best_bid - self.spread_buffer)
            our_ask = self.round_price(best_ask + self.spread_buffer)

            # Ensure valid spread
            if our_bid <= 0:
                our_bid = self.tick_size
            if our_ask >= 1:
                our_ask = 1 - self.tick_size

            if our_bid >= our_ask:
                logger.warning(
                    f"  {outcome}: Spread too tight "
                    f"(bid={our_bid:.4f} >= ask={our_ask:.4f}), skipping"
                )
                continue

            position_size = positions.get(outcome, 0)
            token_id = self.token_ids[i] if i < len(self.token_ids) else None

            # Check existing orders
            outcome_orders = [o for o in open_orders if o.outcome == outcome]
            buy_orders = [o for o in outcome_orders if o.side == OrderSide.BUY]
            sell_orders = [o for o in outcome_orders if o.side == OrderSide.SELL]

            # Delta management - skip if at max position
            if delta > self.max_delta and position_size == max_position_size:
                logger.info(f"  {outcome}: Skip - max position (delta mgmt)")
                continue

            # Place BUY order if needed
            should_place_buy = True

            # Check if we already have a similar buy order
            if buy_orders:
                for order in buy_orders:
                    if abs(order.price - our_bid) < self.tick_size * 2:
                        should_place_buy = False
                        break

                # Cancel stale buy orders
                if should_place_buy:
                    for order in buy_orders:
                        try:
                            self.exchange.cancel_order(order.id)
                            logger.info(
                                f"    {Colors.gray('x Cancel')} "
                                f"{Colors.green('BUY')} @ {Colors.yellow(f'{order.price:.4f}')}"
                            )
                        except Exception:
                            pass

            # Check position limit
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
                        params={"token_id": token_id} if token_id else None,
                    )
                    logger.info(
                        f"    {Colors.gray('->')} {Colors.green('BUY')} "
                        f"{self.order_size:.0f} {Colors.magenta(outcome)} "
                        f"@ {Colors.yellow(f'{our_bid:.4f}')}"
                    )
                except Exception as e:
                    logger.error(f"    BUY failed: {e}")

            # Place SELL order if needed
            should_place_sell = True

            # Check if we already have a similar sell order
            if sell_orders:
                for order in sell_orders:
                    if abs(order.price - our_ask) < self.tick_size * 2:
                        should_place_sell = False
                        break

                # Cancel stale sell orders
                if should_place_sell:
                    for order in sell_orders:
                        try:
                            self.exchange.cancel_order(order.id)
                            logger.info(
                                f"    {Colors.gray('x Cancel')} "
                                f"{Colors.red('SELL')} @ {Colors.yellow(f'{order.price:.4f}')}"
                            )
                        except Exception:
                            pass

            # Need position to sell
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
                        params={"token_id": token_id} if token_id else None,
                    )
                    logger.info(
                        f"    {Colors.gray('->')} {Colors.red('SELL')} "
                        f"{self.order_size:.0f} {Colors.magenta(outcome)} "
                        f"@ {Colors.yellow(f'{our_ask:.4f}')}"
                    )
                except Exception as e:
                    logger.error(f"    SELL failed: {e}")

    def run(self, duration_minutes: Optional[int] = None):
        """Run the market making bot."""
        logger.info(
            f"\n{Colors.bold('Market Maker:')} {Colors.cyan('Limitless Spread Strategy')} | "
            f"MaxPos: {Colors.blue(f'{self.max_position:.0f}')} | "
            f"Size: {Colors.yellow(f'{self.order_size:.0f}')} | "
            f"MaxDelta: {Colors.yellow(f'{self.max_delta:.0f}')} | "
            f"Interval: {Colors.gray(f'{self.check_interval}s')}"
        )

        # Fetch market
        if not self.fetch_market():
            logger.error("Failed to fetch market. Exiting.")
            return

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
            self.liquidate_positions()
            logger.info("Market maker stopped")


def main():
    load_dotenv()

    private_key = os.getenv("LIMITLESS_PRIVATE_KEY")

    if not private_key:
        logger.error("Missing environment variables!")
        logger.error("Set LIMITLESS_PRIVATE_KEY in .env")
        return 1

    # Parse command line arguments
    market_slug = os.getenv("MARKET_SLUG", "") or os.getenv("LIMITLESS_MARKET_SLUG", "")

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if not args[i].startswith("--"):
            market_slug = args[i]
            i += 1
        else:
            i += 1

    if not market_slug:
        logger.error("No market slug provided!")
        logger.error("\nUsage:")
        logger.error("  uv run python examples/limitless_spread_strategy.py MARKET_SLUG")
        logger.error("  MARKET_SLUG=xxx uv run python examples/limitless_spread_strategy.py")
        logger.error("\nExample:")
        logger.error("  uv run python examples/limitless_spread_strategy.py will-btc-reach-100k")
        logger.error(
            "  MARKET_SLUG=will-btc-reach-100k uv run python examples/limitless_spread_strategy.py"
        )
        return 1

    # Create exchange
    exchange = dr_manhattan.Limitless({"private_key": private_key, "verbose": True})

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
    mm = LimitlessSpreadStrategy(
        exchange=exchange,
        market_slug=market_slug,
        max_position=100.0,
        order_size=5.0,
        max_delta=20.0,
        check_interval=10.0,
        spread_buffer=0.01,
    )

    mm.run(duration_minutes=None)

    return 0


if __name__ == "__main__":
    sys.exit(main())
