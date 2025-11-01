#!/usr/bin/env python3
"""
Bid-Ask Spread Strategy for Polymarket

This strategy identifies markets with wide bid-ask spreads and could
potentially profit by providing liquidity (market making).
"""

import time
import logging
from typing import List, Dict, Tuple, Any
import two_face
from two_face.models import Market, Order, OrderSide
from two_face.base.errors import ExchangeError, InsufficientFunds

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class BidAskSpreadStrategy:
    """Strategy that looks for wide bid-ask spreads"""

    def __init__(self, exchange_config: Dict, min_spread: float = 0.005, max_exposure: float = 1000.0):
        self.min_spread = min_spread
        self.max_exposure = max_exposure

        config = {
            **exchange_config,
            'rate_limit': 5,
            'max_retries': 3,
            'verbose': False
        }

        self.exchange = two_face.Polymarket(config)
        self.opportunities: Dict[str, Dict] = {}

    def analyze_markets(self, markets: List[Market]) -> List[Tuple[Market, float, Dict[str, Any]]]:
        """Analyze markets for bid-ask spread opportunities"""
        opportunities = []
        spreads_info = []

        logger.info(f"\nAnalyzing {len(markets)} markets for bid-ask spreads...")
        logger.info("="*80)

        for market in markets:
            # Check if binary and open
            if not market.is_binary or not market.is_open:
                continue

            # Get bid-ask data from metadata
            if 'spread' not in market.metadata or 'bestBid' not in market.metadata or 'bestAsk' not in market.metadata:
                continue

            spread = float(market.metadata.get('spread', 0))
            best_bid = float(market.metadata.get('bestBid', 0))
            best_ask = float(market.metadata.get('bestAsk', 0))

            # Skip if no real orderbook
            if spread <= 0 or best_bid <= 0 or best_ask <= 0:
                continue

            # Calculate metrics
            mid_price = (best_bid + best_ask) / 2
            spread_pct = (spread / mid_price) * 100 if mid_price > 0 else 0

            spread_data = {
                'spread': spread,
                'best_bid': best_bid,
                'best_ask': best_ask,
                'mid_price': mid_price,
                'spread_pct': spread_pct,
                'spread_bps': spread_pct * 100  # basis points
            }

            spreads_info.append((market, spread, spread_data))

            if spread >= self.min_spread:
                opportunities.append((market, spread, spread_data))

        # Sort by spread descending
        spreads_info.sort(key=lambda x: x[1], reverse=True)

        # Show top 15 spreads
        logger.info(f"\nTop 15 Markets by Bid-Ask Spread:")
        logger.info("-"*80)
        for i, (market, spread, data) in enumerate(spreads_info[:15], 1):
            logger.info(f"{i}. Spread: {spread:.4f} ({data['spread_pct']:.2f}%) | Vol: ${market.volume:,.0f}")
            logger.info(f"   Q: {market.question[:60]}")
            logger.info(f"   Bid: {data['best_bid']:.4f} | Ask: {data['best_ask']:.4f} | Mid: {data['mid_price']:.4f}")

        logger.info(f"\n{len(opportunities)} markets above {self.min_spread:.4f} ({(self.min_spread/(spreads_info[0][2]['mid_price'] if spreads_info else 0.5))*100:.2f}%) threshold")
        logger.info("="*80)

        return opportunities

    def execute_market_making_trade(self, market: Market, spread: float, data: Dict[str, Any]) -> bool:
        """Simulate market making trade (DRY RUN)"""
        try:
            best_bid = data['best_bid']
            best_ask = data['best_ask']
            mid_price = data['mid_price']

            # Calculate position size based on liquidity
            base_size = min(100.0, market.liquidity * 0.01) if market.liquidity > 0 else 50.0

            # Limit exposure
            position_cost = base_size * mid_price
            if position_cost > self.max_exposure:
                base_size *= self.max_exposure / position_cost

            # Market making strategy: place orders inside the spread
            our_bid = best_bid + (spread * 0.3)  # 30% inside from bid
            our_ask = best_ask - (spread * 0.3)  # 30% inside from ask

            logger.info(f"\n*** MARKET MAKING OPPORTUNITY ***")
            logger.info(f"Market: {market.question[:60]}")
            logger.info(f"Current spread: {spread:.4f} ({data['spread_pct']:.2f}%)")
            logger.info(f"Current best bid: {best_bid:.4f} | best ask: {best_ask:.4f}")
            logger.info(f"\nWOULD PLACE:")
            logger.info(f"  BUY order:  {base_size:.2f} shares @ {our_bid:.4f} (better than ask)")
            logger.info(f"  SELL order: {base_size:.2f} shares @ {our_ask:.4f} (better than bid)")
            logger.info(f"\nPotential profit if both fill: ${base_size * (our_ask - our_bid):.2f}")
            logger.info(f"Capital required: ${base_size * our_bid:.2f}")
            logger.info("*** DRY RUN - NO ACTUAL TRADES ***\n")

            # Store opportunity
            self.opportunities[market.id] = {
                'market': market,
                'spread': spread,
                'spread_pct': data['spread_pct'],
                'our_bid': our_bid,
                'our_ask': our_ask,
                'size': base_size,
                'potential_profit': base_size * (our_ask - our_bid)
            }

            return True

        except Exception as e:
            logger.error(f"Error in market making calculation: {e}")
            return False

    def run_strategy(self, duration_minutes: int = 2, check_interval_seconds: int = 30):
        """Run the bid-ask spread strategy"""
        start_time = time.time()
        end_time = start_time + (duration_minutes * 60)

        logger.info(f"\nStarting Bid-Ask Spread Strategy")
        logger.info(f"Duration: {duration_minutes} minutes")
        logger.info(f"Minimum spread threshold: {self.min_spread:.4f}")
        logger.info(f"Maximum exposure: ${self.max_exposure:.2f}")

        iteration = 0
        try:
            while time.time() < end_time:
                iteration += 1
                logger.info(f"\n{'='*80}")
                logger.info(f"Iteration #{iteration} - {time.strftime('%H:%M:%S')}")
                logger.info(f"{'='*80}")

                # Fetch markets
                markets = self.exchange.fetch_markets({'limit': 100})

                # Analyze for spread opportunities
                opportunities = self.analyze_markets(markets)

                # Execute top 3 opportunities
                for market, spread, data in opportunities[:3]:
                    if market.id not in self.opportunities:
                        self.execute_market_making_trade(market, spread, data)

                # Wait for next iteration
                if time.time() < end_time:
                    logger.info(f"\nWaiting {check_interval_seconds}s until next check...")
                    time.sleep(check_interval_seconds)

        except KeyboardInterrupt:
            logger.info("\n\nStrategy interrupted by user")
        finally:
            logger.info(f"\n{'='*80}")
            logger.info("STRATEGY COMPLETED")
            logger.info(f"{'='*80}")
            logger.info(f"Total opportunities found: {len(self.opportunities)}")

            if self.opportunities:
                total_potential_profit = sum(o['potential_profit'] for o in self.opportunities.values())
                logger.info(f"Total potential profit: ${total_potential_profit:.2f}")
                logger.info(f"\nOpportunities:")
                for i, (market_id, opp) in enumerate(self.opportunities.items(), 1):
                    logger.info(f"  {i}. {opp['market'].question[:50]}")
                    logger.info(f"     Spread: {opp['spread']:.4f} ({opp['spread_pct']:.2f}%)")
                    logger.info(f"     Our bid/ask: {opp['our_bid']:.4f} / {opp['our_ask']:.4f}")
                    logger.info(f"     Potential profit: ${opp['potential_profit']:.2f}")
            else:
                logger.info("No spread opportunities found above threshold")

def main():
    exchange_config = {
        'dry_run': True
    }

    strategy = BidAskSpreadStrategy(
        exchange_config=exchange_config,
        min_spread=0.003,  # 0.3% minimum spread
        max_exposure=500.0
    )

    # Run for 2 minutes
    strategy.run_strategy(duration_minutes=2, check_interval_seconds=35)

if __name__ == "__main__":
    main()
