"""
Market Making Example for Opinion

Simple spread strategy using REST API polling (no WebSocket).

Usage:
    uv run python examples/opinion/spread_strategy.py MARKET_ID

    # Via environment variable
    MARKET_ID="123" uv run python examples/opinion/spread_strategy.py
"""

import os
import sys
import time
from typing import Dict, List, Optional

from dotenv import load_dotenv

import dr_manhattan
from dr_manhattan.models import OrderSide


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
        """
        self.exchange = exchange
        self.market_id = market_id
        self.max_position = max_position
        self.order_size = order_size
        self.max_delta = max_delta
        self.check_interval = check_interval

        self.market = None
        self.token_ids = []
        self.outcomes = []
        self.tick_size = 0.01

        self.is_running = False

    def fetch_market(self) -> bool:
        """Fetch market data"""
        print(f"Fetching market: {self.market_id}")

        try:
            self.market = self.exchange.fetch_market(self.market_id)
        except Exception as e:
            print(f"Failed to fetch market: {e}")
            return False

        if not self.market:
            print(f"Market not found: {self.market_id}")
            return False

        self.token_ids = self.market.metadata.get("clobTokenIds", [])
        self.outcomes = self.market.outcomes

        if not self.token_ids:
            print("No token IDs found in market")
            return False

        self.tick_size = self.market.metadata.get("tick_size", 0.01)

        print(f"\nMarket: {self.market.question}")
        print(f"Outcomes: {self.outcomes}")
        print(f"Tick size: {self.tick_size}")
        print(f"Volume: ${self.market.volume:,.0f}")
        print(f"Liquidity: ${self.market.liquidity:,.0f}")

        for i, (outcome, token_id) in enumerate(zip(self.outcomes, self.token_ids)):
            price = self.market.prices.get(outcome, 0)
            print(f"  [{i}] {outcome}: {price:.4f} (token: {token_id})")

        return True

    def get_orderbook(self, token_id: str) -> Dict:
        """Fetch orderbook via REST API"""
        try:
            return self.exchange.get_orderbook(token_id)
        except Exception as e:
            print(f"Failed to fetch orderbook: {e}")
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
            positions_list = self.exchange.fetch_positions(market_id=self.market_id)
            for pos in positions_list:
                positions[pos.outcome] = pos.size
        except Exception as e:
            print(f"Failed to fetch positions: {e}")

        return positions

    def get_open_orders(self) -> List:
        """Get all open orders"""
        try:
            return self.exchange.fetch_open_orders(market_id=self.market_id)
        except Exception as e:
            print(f"Failed to fetch open orders: {e}")
            return []

    def cancel_all_orders(self):
        """Cancel all open orders"""
        orders = self.get_open_orders()

        if not orders:
            return

        print(f"Cancelling {len(orders)} orders...")
        for order in orders:
            try:
                self.exchange.cancel_order(order.id, market_id=self.market_id)
            except Exception as e:
                print(f"  Failed to cancel {order.id}: {e}")

    def round_price(self, price: float) -> float:
        """Round price to tick size"""
        return round(price / self.tick_size) * self.tick_size

    def place_orders(self):
        """Main market making logic"""
        positions = self.get_positions()
        open_orders = self.get_open_orders()

        # Calculate metrics
        total_position = sum(positions.values())
        max_pos = max(positions.values()) if positions else 0
        min_pos = min(positions.values()) if positions else 0
        delta = max_pos - min_pos

        # Position display
        pos_str = ", ".join([f"{o}: {positions.get(o, 0):.0f}" for o in self.outcomes])
        print(f"\n[{time.strftime('%H:%M:%S')}] Positions: {pos_str} | Delta: {delta:.1f} | Orders: {len(open_orders)}")

        if delta > self.max_delta:
            print(f"  Warning: Delta ({delta:.1f}) > max ({self.max_delta})")

        for i, (outcome, token_id) in enumerate(zip(self.outcomes, self.token_ids)):
            # Get orderbook
            best_bid, best_ask = self.get_best_bid_ask(token_id)

            if best_bid is None or best_ask is None:
                print(f"  {outcome}: No orderbook data, skipping...")
                continue

            # Our prices (join BBO)
            our_bid = self.round_price(best_bid)
            our_ask = self.round_price(best_ask)

            # Validate
            our_bid = max(0.01, min(0.99, our_bid))
            our_ask = max(0.01, min(0.99, our_ask))

            if our_bid >= our_ask:
                print(f"  {outcome}: Spread too tight (bid={our_bid:.4f} >= ask={our_ask:.4f})")
                continue

            position_size = positions.get(outcome, 0)

            # Check existing orders
            outcome_orders = [o for o in open_orders if o.outcome == outcome]
            buy_orders = [o for o in outcome_orders if o.side == OrderSide.BUY]
            sell_orders = [o for o in outcome_orders if o.side == OrderSide.SELL]

            # Delta management
            if delta > self.max_delta and position_size == max_pos:
                print(f"  {outcome}: Skipping (delta management)")
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
                        print(f"  {outcome}: Cancel BUY @ {order.price:.4f}")
                    except:
                        pass

            if position_size + self.order_size > self.max_position:
                should_buy = False

            if should_buy:
                try:
                    order = self.exchange.create_order(
                        market_id=self.market_id,
                        outcome=outcome,
                        side=OrderSide.BUY,
                        price=our_bid,
                        size=self.order_size,
                        params={"token_id": token_id},
                    )
                    print(f"  {outcome}: BUY {self.order_size:.0f} @ {our_bid:.4f}")
                except Exception as e:
                    print(f"  {outcome}: BUY failed: {e}")

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
                        print(f"  {outcome}: Cancel SELL @ {order.price:.4f}")
                    except:
                        pass

            if position_size < self.order_size:
                should_sell = False

            if should_sell:
                try:
                    order = self.exchange.create_order(
                        market_id=self.market_id,
                        outcome=outcome,
                        side=OrderSide.SELL,
                        price=our_ask,
                        size=self.order_size,
                        params={"token_id": token_id},
                    )
                    print(f"  {outcome}: SELL {self.order_size:.0f} @ {our_ask:.4f}")
                except Exception as e:
                    print(f"  {outcome}: SELL failed: {e}")

    def run(self, duration_minutes: Optional[int] = None):
        """Run the market making bot"""
        print(f"\nSpread Strategy | MaxPos: {self.max_position} | Size: {self.order_size} | MaxDelta: {self.max_delta} | Interval: {self.check_interval}s")

        if not self.fetch_market():
            print("Failed to fetch market. Exiting.")
            return

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
            print("\nStopping...")

        finally:
            self.is_running = False
            self.cancel_all_orders()
            print("Market maker stopped")


def main():
    load_dotenv()

    api_key = os.getenv("OPINION_API_KEY")
    private_key = os.getenv("OPINION_PRIVATE_KEY")
    multi_sig_addr = os.getenv("OPINION_MULTI_SIG_ADDR")

    if not api_key or not private_key or not multi_sig_addr:
        print("Missing environment variables!")
        print("Set in .env file:")
        print("  OPINION_API_KEY=...")
        print("  OPINION_PRIVATE_KEY=...")
        print("  OPINION_MULTI_SIG_ADDR=...")
        return 1

    # Get market ID
    market_id = os.getenv("MARKET_ID", "")

    if len(sys.argv) > 1:
        market_id = sys.argv[1]

    if not market_id:
        print("No market ID provided!")
        print("\nUsage:")
        print("  uv run python examples/opinion/spread_strategy.py MARKET_ID")
        print("  MARKET_ID=123 uv run python examples/opinion/spread_strategy.py")
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
