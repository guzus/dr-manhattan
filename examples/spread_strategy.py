#!/usr/bin/env python3
"""
BTC Hourly Market Making Strategy for Polymarket

This example shows how to automatically find and trade on currently active
BTC hourly markets using the find_crypto_hourly_market() function.

The strategy:
1. Finds the currently active BTC hourly market
2. Places spread orders on Up/Down outcomes
3. Runs for 2 minutes (or until market expires)

Usage:
    uv run examples/spread_strategy.py
"""

import os
from dotenv import load_dotenv

import dr_manhattan
from dr_manhattan.strategies import MarketMakingStrategy
from dr_manhattan.models import OrderSide
from dr_manhattan.utils import setup_logger

logger = setup_logger(__name__)


class SimpleSpreadStrategy(MarketMakingStrategy):
    """
    Simple spread strategy: places orders inside the bid-ask spread.
    Handles both Yes/No and Up/Down markets.
    """

    def on_tick(self, market):
        """Called every 2 seconds with updated market data"""

        # Get account state (balance + positions) - fully managed by exchange
        # Pass market object for Polymarket position fetching
        account = self.get_account_state(market=market)
        positions = account['positions']
        balance = account['balance'].get('USDC', 0.0)

        # Detect market type from outcomes
        if not market.outcomes or len(market.outcomes) < 2:
            logger.warning("Invalid market outcomes")
            return

        first_outcome = market.outcomes[0]
        is_up_down_market = first_outcome in ['Up', 'Down']

        # Get primary outcome price (Yes or Up)
        primary_outcome = 'Up' if is_up_down_market else 'Yes'
        secondary_outcome = 'Down' if is_up_down_market else 'No'

        # Get price from market.prices dictionary
        mid_price = market.prices.get(primary_outcome, 0)

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

        # Get token IDs (parse from JSON string if needed)
        token_ids_raw = market.metadata.get('clobTokenIds', [])
        if isinstance(token_ids_raw, str):
            import json
            token_ids = json.loads(token_ids_raw)
        else:
            token_ids = token_ids_raw

        if len(token_ids) < 2:
            logger.error("Need 2 token IDs")
            return

        # Map outcomes to token IDs (assume order matches market.outcomes)
        primary_token_id = token_ids[0] if market.outcomes[0] == primary_outcome else token_ids[1]
        secondary_token_id = token_ids[1] if market.outcomes[0] == primary_outcome else token_ids[0]

        # Check if we have primary outcome position (Yes or Up)
        primary_position = next((p for p in positions if p.outcome == primary_outcome and p.size > 0), None)

        logger.info(f"\n{'='*80}")
        logger.info(f"LIVE MARKET MAKING - BTC HOURLY")
        logger.info(f"{'='*80}")
        logger.info(f"Market: {market.question[:70]}...")
        logger.info(f"{primary_outcome} price: {mid_price:.4f} | Spread: {spread:.4f}")
        logger.info(f"USDC: ${balance:.2f}")

        if primary_position:
            # Market making: place both sides
            our_bid = best_bid + (spread * 0.3)
            our_ask = best_ask - (spread * 0.3)

            logger.info(f"\nStrategy: Market making (have {primary_outcome} position)")
            logger.info(f"  BUY {primary_outcome}:  {size:.2f} @ {our_bid:.4f}")
            logger.info(f"  SELL {primary_outcome}: {size:.2f} @ {our_ask:.4f}")

            try:
                buy_order = self.exchange.create_order(
                    market_id=market.id,
                    outcome=primary_outcome,
                    side=OrderSide.BUY,
                    price=our_bid,
                    size=size,
                    params={'token_id': primary_token_id}
                )
                logger.info(f"BUY {primary_outcome} placed: {buy_order.id}")
                self.placed_orders.append(buy_order)
            except Exception as e:
                logger.error(f"Failed to place BUY order: {e}")
                return

            try:
                sell_order = self.exchange.create_order(
                    market_id=market.id,
                    outcome=primary_outcome,
                    side=OrderSide.SELL,
                    price=our_ask,
                    size=size,
                    params={'token_id': primary_token_id}
                )
                logger.info(f"SELL {primary_outcome} placed: {sell_order.id}")
                self.placed_orders.append(sell_order)
            except Exception as e:
                logger.error(f"Failed to place SELL order: {e}")

        else:
            # No position: buy secondary outcome (No or Down) at 1-price
            secondary_price = 1 - mid_price
            our_secondary_bid = max(0.01, min(0.99, secondary_price + (spread * 0.3)))

            logger.info(f"\nStrategy: Buy {secondary_outcome} (no {primary_outcome} position)")
            logger.info(f"  BUY {secondary_outcome}: {size:.2f} @ {our_secondary_bid:.4f}")

            try:
                buy_order = self.exchange.create_order(
                    market_id=market.id,
                    outcome=secondary_outcome,
                    side=OrderSide.BUY,
                    price=our_secondary_bid,
                    size=size,
                    params={'token_id': secondary_token_id}
                )
                logger.info(f"BUY {secondary_outcome} placed: {buy_order.id}")
                self.placed_orders.append(buy_order)
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
    exchange = dr_manhattan.Polymarket({
        'private_key': private_key,
        'funder': funder,
        'cache_ttl': 2.0,  # Polygon block time
        'verbose': True
    })

    # Find currently active BTC hourly market
    logger.info("Finding currently active BTC hourly market...")
    result = exchange.find_crypto_hourly_market(
        token_symbol='BTC',
        is_active=True,
        is_expired=False
    )

    if not result:
        logger.error("No active BTC hourly market found!")
        return

    market, crypto_info = result
    logger.info(f"Found market: {crypto_info}")
    logger.info(f"Question: {market.question}")
    logger.info(f"Expiry: {crypto_info.expiry_time}")
    logger.info(f"Market ID: {market.id}")

    # Log Polymarket URL
    slug = market.metadata.get('slug', '')
    if slug:
        market_url = f"https://polymarket.com/event/{slug}"
        logger.info(f"Market URL: {market_url}")

    logger.info(f"UP price: {market.prices.get('Up', 0):.4f}")
    logger.info(f"DOWN price: {market.prices.get('Down', 0):.4f}")
    logger.info(f"Liquidity: ${market.liquidity:,.2f}")
    logger.info("")

    # Create and run strategy on this market
    strategy = SimpleSpreadStrategy(
        exchange=exchange,
        max_exposure=500.0,
        check_interval=2.0  # 2 seconds = Polygon block time
    )

    # Run strategy on the specific BTC hourly market for 2 minutes
    strategy.run(market=market, duration_minutes=2)


if __name__ == "__main__":
    main()
