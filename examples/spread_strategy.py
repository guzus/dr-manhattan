#!/usr/bin/env python3
"""
Simple Spread Strategy Example for Polymarket using Two-Face

This strategy identifies arbitrage opportunities in binary prediction markets
by exploiting price inefficiencies between complementary outcomes.
"""

import time
import logging
from typing import List, Dict, Tuple
import two_face
from two_face.models import Market, Order, OrderSide
from two_face.base.errors import ExchangeError, InsufficientFunds

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SpreadStrategy:
    """Simple spread strategy for binary prediction markets"""
    
    def __init__(self, exchange_config: Dict, min_spread: float = 0.02, max_exposure: float = 1000.0):
        self.min_spread = min_spread
        self.max_exposure = max_exposure
        
        # Initialize exchange with retry and rate limiting
        config = {
            **exchange_config,
            'rate_limit': 5,
            'max_retries': 3,
            'verbose': True
        }
        
        self.exchange = two_face.Polymarket(config)
        self.positions: Dict[str, Dict] = {}
    
    def find_spread_opportunities(self, markets: List[Market]) -> List[Tuple[Market, float, Dict[str, float]]]:
        """Find markets with profitable spread opportunities"""
        opportunities = []
        
        for market in markets:
            if not market.is_binary or not market.is_open:
                continue
            
            if len(market.outcomes) != 2 or len(market.prices) != 2:
                continue
            
            price_values = list(market.prices.values())
            if any(p <= 0 or p >= 1 for p in price_values):
                continue
            
            # Calculate spread (1 - sum of prices)
            spread = 1.0 - sum(price_values)
            
            if spread > self.min_spread:
                opportunities.append((market, spread, market.prices))
                logger.info(f"Found opportunity: {market.question[:50]}... - Spread: {spread:.2%}")
        
        return opportunities
    
    def execute_spread_trade(self, market: Market, spread: float, prices: Dict[str, float]) -> bool:
        """Execute a spread trade by buying both outcomes"""
        try:
            # Calculate position sizes based on spread and liquidity
            base_size = self.exchange.get_optimal_order_size(market, 100.0)
            spread_multiplier = min(spread / self.min_spread, 2.0)
            position_size = base_size * spread_multiplier
            
            # Ensure we don't exceed maximum exposure
            total_cost = sum(position_size * price for price in prices.values())
            if total_cost > self.max_exposure:
                position_size *= self.max_exposure / total_cost
            
            orders = []
            for outcome, price in prices.items():
                order = self.exchange.create_order(
                    market_id=market.id,
                    outcome=outcome,
                    side=OrderSide.BUY,
                    price=price,
                    size=position_size,
                    params={'token_id': f"token_{market.id}_{outcome.lower()}"}
                )
                orders.append(order)
                logger.info(f"Placed order: BUY {position_size} @ {price:.4f} for {outcome}")
            
            # Store position information
            self.positions[market.id] = {
                'market': market,
                'orders': orders,
                'expected_profit': sum(position_size * (1 - price) for price in prices.values())
            }
            
            logger.info(f"Spread trade executed for {market.question[:50]}...")
            return True
            
        except (ExchangeError, InsufficientFunds) as e:
            logger.error(f"Failed to execute spread trade: {e}")
            return False
    
    def run_strategy(self, duration_minutes: int = 60, check_interval_seconds: int = 30):
        """Run the spread strategy for a specified duration"""
        start_time = time.time()
        end_time = start_time + (duration_minutes * 60)
        
        logger.info(f"Starting spread strategy for {duration_minutes} minutes")
        
        try:
            while time.time() < end_time:
                # Fetch all markets
                markets = self.exchange.fetch_markets()
                logger.info(f"Fetched {len(markets)} markets")
                
                # Find and execute opportunities
                opportunities = self.find_spread_opportunities(markets)
                for market, spread, prices in opportunities[:3]:  # Limit to top 3
                    if market.id not in self.positions:
                        self.execute_spread_trade(market, spread, prices)
                
                # Wait for next check
                time.sleep(check_interval_seconds)
                
        except KeyboardInterrupt:
            logger.info("Strategy interrupted by user")
        finally:
            logger.info("Strategy completed. Final positions:")
            for market_id, position_info in self.positions.items():
                logger.info(f"  {market_id[:8]}... - Expected profit: ${position_info['expected_profit']:.2f}")

# Usage example
def main():
    exchange_config = {
        # 'private_key': 'your_private_key_here',
        'dry_run': True  # Set to False for live trading
    }
    
    strategy = SpreadStrategy(
        exchange_config=exchange_config,
        min_spread=0.03,  # 3% minimum spread
        max_exposure=500.0  # $500 total exposure
    )
    
    # Run for 2 minutes for testing
    strategy.run_strategy(duration_minutes=2, check_interval_seconds=30)

if __name__ == "__main__":
    main()
