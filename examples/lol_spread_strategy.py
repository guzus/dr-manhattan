#!/usr/bin/env python3
"""
League of Legends Spread Strategy Example

This example demonstrates a spread trading strategy for LoL match markets.
The strategy places orders inside the bid-ask spread for both outcomes.

Strategy Logic:
1. Searches for a LoL match market (T1 vs KT, or specify via MARKET_SLUG env var)
2. Calculates mid-price and spread based on current odds
3. Places buy orders slightly inside the spread
4. Adjusts orders based on current positions
5. Manages risk exposure (max $500 by default)

Usage:
    # Search for T1 vs KT match
    uv run examples/lol_spread_strategy.py

    # Or specify market slug from URL
    MARKET_SLUG="lol-t1-kt-2025-11-09" uv run examples/lol_spread_strategy.py

To find the slug:
    URL: https://polymarket.com/event/lol-t1-kt-2025-11-09
    Slug: lol-t1-kt-2025-11-09 (the part after /event/)
"""

import os
from dotenv import load_dotenv

import dr_manhattan
from dr_manhattan.strategies import MarketMakingStrategy
from dr_manhattan.models import OrderSide
from dr_manhattan.utils import setup_logger

logger = setup_logger(__name__)


class LoLSpreadStrategy(MarketMakingStrategy):
    """
    Spread strategy for League of Legends match markets.
    Places orders inside the bid-ask spread to capture value.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.active_buy_order = None
        self.active_sell_order = None

    def get_orderbook_prices(self, market, outcome):
        """Fetch best bid/ask from CLOB orderbook"""
        import requests

        token_ids_raw = market.metadata.get('clobTokenIds', [])
        if isinstance(token_ids_raw, str):
            import json
            token_ids = json.loads(token_ids_raw)
        else:
            token_ids = token_ids_raw

        outcome_index = market.outcomes.index(outcome) if outcome in market.outcomes else 0
        token_id = token_ids[outcome_index] if outcome_index < len(token_ids) else None

        if not token_id:
            return None, None

        try:
            response = requests.get(
                f"https://clob.polymarket.com/book",
                params={"token_id": token_id},
                timeout=5
            )

            if response.status_code == 200:
                book = response.json()
                bids = book.get('bids', [])
                asks = book.get('asks', [])

                best_bid = float(bids[0]['price']) if bids else None
                best_ask = float(asks[0]['price']) if asks else None

                return best_bid, best_ask
        except Exception as e:
            logger.warning(f"Failed to fetch orderbook: {e}")

        return None, None

    def on_tick(self, market):
        """Called every check interval with updated market data"""

        account = self.get_account_state(market=market)
        positions = account['positions']
        balance = account['balance'].get('USDC', 0.0)

        # Fetch open orders from CLOB using conditionId (hex format)
        try:
            condition_id = market.metadata.get('conditionId', market.id)
            open_orders = self.exchange.fetch_open_orders(market_id=condition_id)
            if open_orders:
                logger.info(f"\n  Fetched {len(open_orders)} open orders from CLOB")
        except Exception as e:
            logger.warning(f"Failed to fetch open orders: {e}")
            open_orders = []

        if not market.outcomes or len(market.outcomes) < 2:
            logger.warning("Invalid market outcomes")
            return

        team1_outcome = market.outcomes[0]
        team2_outcome = market.outcomes[1]

        team1_price = market.prices.get(team1_outcome, 0)
        team2_price = market.prices.get(team2_outcome, 0)

        if team1_price <= 0 or team1_price >= 1:
            logger.warning(f"Invalid {team1_outcome} price: {team1_price}")
            return

        TICK_SIZE = 0.01
        size = 5.0

        team1_bid, team1_ask = self.get_orderbook_prices(market, team1_outcome)
        team2_bid, team2_ask = self.get_orderbook_prices(market, team2_outcome)

        token_ids_raw = market.metadata.get('clobTokenIds', [])
        if isinstance(token_ids_raw, str):
            import json
            token_ids = json.loads(token_ids_raw)
        else:
            token_ids = token_ids_raw

        if len(token_ids) < 2:
            logger.error("Need 2 token IDs for binary market")
            return

        team1_token_id = token_ids[0] if market.outcomes[0] == team1_outcome else token_ids[1]
        team2_token_id = token_ids[1] if market.outcomes[0] == team1_outcome else token_ids[0]

        team1_position = next((p for p in positions if p.outcome == team1_outcome and p.size > 0), None)
        team2_position = next((p for p in positions if p.outcome == team2_outcome and p.size > 0), None)

        logger.info(f"\n{'='*80}")
        logger.info(f"LEAGUE OF LEGENDS - SPREAD STRATEGY")
        logger.info(f"{'='*80}")
        logger.info(f"Market: {market.question}")
        logger.info(f"{team1_outcome}: Mid={team1_price:.4f} Bid={team1_bid:.4f} Ask={team1_ask:.4f}" if team1_bid and team1_ask else f"{team1_outcome}: {team1_price:.4f}")
        logger.info(f"{team2_outcome}: Mid={team2_price:.4f} Bid={team2_bid:.4f} Ask={team2_ask:.4f}" if team2_bid and team2_ask else f"{team2_outcome}: {team2_price:.4f}")
        logger.info(f"USDC Balance: ${balance:.2f}")

        if team1_position:
            logger.info(f"\nCurrent Position: {team1_outcome} - {team1_position.size:.2f} shares")

        if team2_position:
            logger.info(f"Current Position: {team2_outcome} - {team2_position.size:.2f} shares")

        logger.info(f"\nStrategy: Market making (capital efficient)")

        favorite_outcome = team1_outcome if team1_price > 0.5 else team2_outcome
        underdog_outcome = team2_outcome if team1_price > 0.5 else team1_outcome
        favorite_token_id = team1_token_id if team1_price > 0.5 else team2_token_id
        underdog_token_id = team2_token_id if team1_price > 0.5 else team1_token_id
        favorite_bid, favorite_ask = (team1_bid, team1_ask) if team1_price > 0.5 else (team2_bid, team2_ask)
        underdog_bid, underdog_ask = (team2_bid, team2_ask) if team1_price > 0.5 else (team1_bid, team1_ask)
        favorite_price = team1_price if team1_price > 0.5 else team2_price
        underdog_price = team2_price if team1_price > 0.5 else team1_price

        favorite_position = team1_position if team1_price > 0.5 else team2_position
        underdog_position = team2_position if team1_price > 0.5 else team1_position

        if favorite_bid is None or favorite_ask is None or favorite_bid <= 0.01 or favorite_ask >= 0.99:
            estimated_fav_bid = favorite_price - TICK_SIZE
            estimated_fav_ask = favorite_price + TICK_SIZE
            fav_buy_price = max(0.01, min(0.99, estimated_fav_bid))
            fav_sell_price = max(0.01, min(0.99, estimated_fav_ask))
            logger.info(f"\n{favorite_outcome} (favorite): No orderbook, using estimates")
            logger.info(f"  Est Bid={estimated_fav_bid:.4f} Ask={estimated_fav_ask:.4f}")
        else:
            fav_buy_price = max(0.01, min(0.99, favorite_bid))
            fav_sell_price = max(0.01, min(0.99, favorite_ask))
            logger.info(f"\n{favorite_outcome} (favorite): Bid={favorite_bid:.4f} Ask={favorite_ask:.4f}")

        if underdog_bid is None or underdog_ask is None or underdog_bid <= 0.01 or underdog_ask >= 0.99:
            estimated_und_bid = underdog_price - TICK_SIZE
            estimated_und_ask = underdog_price + TICK_SIZE
            und_buy_price = max(0.01, min(0.99, estimated_und_bid))
            und_sell_price = max(0.01, min(0.99, estimated_und_ask))
            logger.info(f"\n{underdog_outcome} (underdog): No orderbook, using estimates")
            logger.info(f"  Est Bid={estimated_und_bid:.4f} Ask={estimated_und_ask:.4f}")
        else:
            und_buy_price = max(0.01, min(0.99, underdog_bid))
            und_sell_price = max(0.01, min(0.99, underdog_ask))
            logger.info(f"\n{underdog_outcome} (underdog): Bid={underdog_bid:.4f} Ask={underdog_ask:.4f}")

        # Check for existing orders (both in-memory and from CLOB)
        underdog_buy_orders = [o for o in open_orders if o.outcome == underdog_outcome and o.side == OrderSide.BUY]
        underdog_sell_orders = [o for o in open_orders if o.outcome == underdog_outcome and o.side == OrderSide.SELL]

        logger.info(f"\n  Target prices: BUY @ {und_buy_price:.4f}, SELL @ {und_sell_price:.4f}")

        if underdog_buy_orders:
            logger.info(f"  Existing BUY orders: {len(underdog_buy_orders)}")
            for order in underdog_buy_orders:
                logger.info(f"    {order.size:.0f} @ {order.price:.4f}")
            self.active_buy_order = underdog_buy_orders[0]  # Track the first one

        if underdog_sell_orders:
            logger.info(f"  Existing SELL orders: {len(underdog_sell_orders)}")
            for order in underdog_sell_orders:
                logger.info(f"    {order.size:.0f} @ {order.price:.4f}")
            self.active_sell_order = underdog_sell_orders[0]  # Track the first one

        # If we have both buy and sell orders, no action needed
        if underdog_buy_orders and underdog_sell_orders:
            logger.info(f"  ✓ Already have BUY and SELL orders, no action needed")
            logger.info(f"{'='*80}\n")
            return

        available_shares = underdog_position.size if underdog_position else 0

        # Place BUY order if we don't have one
        if not underdog_buy_orders:
            logger.info(f"\n  Placing BUY order: {size:.0f} @ {und_buy_price:.4f}")
            try:
                buy_order = self.exchange.create_order(
                    market_id=market.id,
                    outcome=underdog_outcome,
                    side=OrderSide.BUY,
                    price=und_buy_price,
                    size=size,
                    params={'token_id': underdog_token_id}
                )
                logger.info(f"  ✓ BUY order placed: {buy_order.id}")
                self.placed_orders.append(buy_order)
                self.active_buy_order = buy_order
            except Exception as e:
                logger.error(f"  ✗ Failed to place BUY: {e}")

        # Place SELL order if we don't have one
        if not underdog_sell_orders:
            if available_shares >= size:
                logger.info(f"\n  Placing SELL order: {size:.0f} @ {und_sell_price:.4f} (have {available_shares:.1f} available)")
                try:
                    sell_order = self.exchange.create_order(
                        market_id=market.id,
                        outcome=underdog_outcome,
                        side=OrderSide.SELL,
                        price=und_sell_price,
                        size=size,
                        params={'token_id': underdog_token_id}
                    )
                    logger.info(f"  ✓ SELL order placed: {sell_order.id}")
                    self.placed_orders.append(sell_order)
                    self.active_sell_order = sell_order
                except Exception as e:
                    logger.error(f"  ✗ Failed to place SELL: {e}")
            else:
                logger.info(f"\n  Cannot place SELL: need {size:.0f} shares, only have {available_shares:.1f} available")

        logger.info(f"{'='*80}\n")


def main():
    load_dotenv()

    private_key = os.getenv('POLYMARKET_PRIVATE_KEY')
    funder = os.getenv('POLYMARKET_FUNDER')
    market_slug = "lol-t1-kt-2025-11-09"

    if not private_key or not funder:
        logger.error("Missing environment variables!")
        logger.error("Set POLYMARKET_PRIVATE_KEY and POLYMARKET_FUNDER in .env")
        return

    exchange = dr_manhattan.Polymarket({
        'private_key': private_key,
        'funder': funder,
        'cache_ttl': 2.0,
        'verbose': True
    })

    import requests
    import re

    target_market = None

    if market_slug:
        logger.info(f"Fetching market by slug: {market_slug}")
        try:
            response = requests.get(
                f"https://gamma-api.polymarket.com/events?slug={market_slug}",
                timeout=10
            )

            if response.status_code == 200:
                event_data = response.json()
                if event_data and len(event_data) > 0:
                    event = event_data[0]
                    markets_data = event.get('markets', [])

                    if markets_data:
                        market_data = markets_data[0]
                        target_market = exchange._parse_market(market_data)

                        try:
                            token_ids = exchange.fetch_token_ids(target_market.id)
                            target_market.metadata['clobTokenIds'] = token_ids
                        except Exception as token_error:
                            logger.warning(f"Could not fetch token IDs: {token_error}")
                            clobTokenIds = market_data.get('clobTokenIds', [])
                            if clobTokenIds:
                                target_market.metadata['clobTokenIds'] = clobTokenIds
                                logger.info(f"Using token IDs from market data: {len(clobTokenIds)} tokens")

                        logger.info(f"Found market: {target_market.question}")
                    else:
                        logger.error(f"No markets found for slug: {market_slug}")
                else:
                    logger.error(f"Event not found: {market_slug}")
        except Exception as e:
            logger.error(f"Failed to fetch by slug: {e}")

    if not target_market:
        logger.info("Searching for T1 vs KT League of Legends market...")
        logger.info("Trying sports-specific API endpoint...")

        try:
            response = requests.get(
                "https://gamma-api.polymarket.com/markets",
                params={
                    "active": "true",
                    "closed": "false",
                    "limit": 1000,
                    "tag_id": "sports"
                },
                timeout=10
            )

            if response.status_code == 200:
                sports_data = response.json()
                logger.info(f"Fetched {len(sports_data)} sports markets")

                for market_data in sports_data:
                    question = market_data.get('question', '')
                    question_lower = question.lower()

                    if re.search(r'\bt1\b', question_lower) and re.search(r'\bkt\b', question_lower):
                        logger.info(f"Found match in sports: {question}")
                        market = exchange._parse_market(market_data)
                        token_ids = exchange.fetch_token_ids(market.id)
                        market.metadata['clobTokenIds'] = token_ids
                        target_market = market
                        break

        except Exception as e:
            logger.warning(f"Sports API failed: {e}")

    if not target_market:
        logger.info("Searching all markets...")
        markets = exchange.fetch_markets({'limit': 50000, 'active': True, 'closed': False})
        logger.info(f"Fetched {len(markets)} total markets")

        lol_markets = []

        for market in markets:
            question_lower = market.question.lower()

            if re.search(r'\bt1\b', question_lower) and re.search(r'\bkt\b', question_lower):
                logger.info(f"Found potential match: {market.question}")
                target_market = market
                break

            if any(keyword in question_lower for keyword in ['league of legends', 'lck', 'esports']):
                if any(team in question_lower for team in ['t1', 'kt', 'gen', 'dk', 'hle']):
                    lol_markets.append(market.question)

        if not target_market and lol_markets:
            logger.info(f"\nFound {len(lol_markets)} LoL esports markets:")
            for q in lol_markets[:20]:
                logger.info(f"  - {q}")

    if not target_market:
        logger.error("Could not find T1 vs KT market!")
        logger.error("The market may not be active yet or may have closed")
        logger.error("\nTo use a specific market:")
        logger.error("  1. Find the market URL: https://polymarket.com/event/YOUR-SLUG")
        logger.error("  2. Run: MARKET_SLUG=YOUR-SLUG uv run examples/lol_spread_strategy.py")
        return

    logger.info(f"\nFound market!")
    logger.info(f"Question: {target_market.question}")
    logger.info(f"Market ID: {target_market.id}")
    logger.info(f"Outcomes: {target_market.outcomes}")

    if target_market.outcomes:
        for outcome in target_market.outcomes:
            price = target_market.prices.get(outcome, 0)
            logger.info(f"  {outcome}: {price:.4f} ({price*100:.2f}%)")

    logger.info(f"Volume: ${target_market.volume:,.2f}")
    logger.info(f"Liquidity: ${target_market.liquidity:,.2f}")

    slug = target_market.metadata.get('slug', '')
    if slug:
        market_url = f"https://polymarket.com/event/{slug}"
        logger.info(f"Market URL: {market_url}")

    logger.info("")

    strategy = LoLSpreadStrategy(
        exchange=exchange,
        max_exposure=500.0,
        check_interval=2.0
    )

    strategy.run(market=target_market, duration_minutes=None)


if __name__ == "__main__":
    main()
