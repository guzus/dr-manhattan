#!/usr/bin/env python3
"""
Simplified Market Making Strategy for Polymarket

This example shows how to use the MarketMakingStrategy base class
to build a strategy with minimal boilerplate.

Usage:
    uv run examples/simple_spread_strategy.py
"""

import os
from dotenv import load_dotenv

import two_face
from two_face.strategies import MarketMakingStrategy
from two_face.models import OrderSide
from two_face.utils import setup_logger

logger = setup_logger(__name__)


class SimpleSpreadStrategy(MarketMakingStrategy):
    """
    Simple spread strategy: places orders inside the bid-ask spread.
    If no position, buy NO at 1-price.
    """

    def on_tick(self, market):
        """Called every 2 seconds with updated market data"""

        # Get account state (balance + positions) - fully managed by exchange
        # Pass market object for Polymarket position fetching
        account = self.get_account_state(market=market)
        positions = account['positions']
        balance = account['balance'].get('USDC', 0.0)

        # Get market data
        tokens_data = market.metadata.get('tokens', [])
        if not tokens_data or len(tokens_data) < 2:
            logger.warning("No token price data")
            return

        # Get YES price and calculate spread
        yes_token = tokens_data[0] if tokens_data[0].get('outcome') == 'Yes' else tokens_data[1]
        mid_price = float(yes_token.get('price', 0))

        if mid_price <= 0 or mid_price >= 1:
            logger.warning(f"Invalid mid price: {mid_price}")
            return

        # Calculate spread
        spread_pct = 2.0
        spread = mid_price * (spread_pct / 100)
        best_bid = max(0.01, min(0.99, mid_price - (spread / 2)))
        best_ask = max(0.01, min(0.99, mid_price + (spread / 2)))

        # Calculate order size
        size = self.calculate_order_size(market, mid_price, max_exposure=500.0)

        # Get token IDs
        token_ids = market.metadata.get('clobTokenIds', [])
        if len(token_ids) < 2:
            logger.error("Need 2 token IDs")
            return

        yes_token_id = token_ids[0]
        no_token_id = token_ids[1]

        # Check if we have YES position
        yes_position = next((p for p in positions if p.outcome == 'Yes' and p.size > 0), None)

        logger.info(f"\n{'='*80}")
        logger.info(f"LIVE MARKET MAKING")
        logger.info(f"{'='*80}")
        logger.info(f"Market: {market.question[:70]}...")
        logger.info(f"Mid price: {mid_price:.4f} | Spread: {spread:.4f}")
        logger.info(f"USDC: ${balance:.2f}")

        if yes_position:
            # Market making: place both sides
            our_bid = best_bid + (spread * 0.3)
            our_ask = best_ask - (spread * 0.3)

            logger.info(f"\nStrategy: Market making (have YES position)")
            logger.info(f"  BUY YES:  {size:.2f} @ {our_bid:.4f}")
            logger.info(f"  SELL YES: {size:.2f} @ {our_ask:.4f}")

            try:
                buy_order = self.exchange.create_order(
                    market_id=market.id,
                    outcome='Yes',
                    side=OrderSide.BUY,
                    price=our_bid,
                    size=size,
                    params={'token_id': yes_token_id}
                )
                logger.info(f"BUY YES placed: {buy_order.id}")
                self.placed_orders.append(buy_order)
            except Exception as e:
                logger.error(f"Failed to place BUY order: {e}")
                return

            try:
                sell_order = self.exchange.create_order(
                    market_id=market.id,
                    outcome='Yes',
                    side=OrderSide.SELL,
                    price=our_ask,
                    size=size,
                    params={'token_id': yes_token_id}
                )
                logger.info(f"SELL YES placed: {sell_order.id}")
                self.placed_orders.append(sell_order)
            except Exception as e:
                logger.error(f"Failed to place SELL order: {e}")

        else:
            # No position: buy NO at 1-price
            no_price = 1 - mid_price
            our_no_bid = max(0.01, min(0.99, no_price + (spread * 0.3)))

            logger.info(f"\nStrategy: Buy NO (no YES position)")
            logger.info(f"  BUY NO: {size:.2f} @ {our_no_bid:.4f}")

            try:
                buy_no_order = self.exchange.create_order(
                    market_id=market.id,
                    outcome='No',
                    side=OrderSide.BUY,
                    price=our_no_bid,
                    size=size,
                    params={'token_id': no_token_id}
                )
                logger.info(f"BUY NO placed: {buy_no_order.id}")
                self.placed_orders.append(buy_no_order)
            except Exception as e:
                logger.error(f"Failed to place order: {e}")

        logger.info(f"{'='*80}\n")


def main():
    # Load environment
    load_dotenv()

    private_key = os.getenv('POLYMARKET_PRIVATE_KEY')
    funder = os.getenv('POLYMARKET_FUNDER')

    if not private_key or not funder:
        logger.error("Missing environment variables!")
        logger.error("Set POLYMARKET_PRIVATE_KEY and POLYMARKET_FUNDER in .env")
        return

    # Create exchange
    exchange = two_face.Polymarket({
        'private_key': private_key,
        'funder': funder,
        'cache_ttl': 2.0,  # Polygon block time
        'verbose': True
    })

    # Create and run strategy (that's it!)
    strategy = SimpleSpreadStrategy(
        exchange=exchange,
        max_exposure=500.0,
        check_interval=2.0  # 2 seconds = Polygon block time
    )

    # Run for 2 minutes
    strategy.run(duration_minutes=2)


if __name__ == "__main__":
    main()
