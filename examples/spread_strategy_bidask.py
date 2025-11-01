#!/usr/bin/env python3
"""
Market Making Strategy for Polymarket - LIVE TRADING

⚠️  WARNING: This script places REAL orders with REAL money on Polymarket!

This strategy provides liquidity (market making) on a random market
by placing bid and ask orders inside the spread.

Requirements:
- Install dependencies: pip install python-dotenv eth-account
- Create a .env file with your credentials (see env.example)
- Ensure you have USDC balance on Polygon network

Usage:
    1. Copy env.example to .env:
       cp env.example .env
    
    2. Edit .env with your credentials:
       POLYMARKET_PRIVATE_KEY=your_private_key_here
       POLYMARKET_FUNDER=0xYourFunderAddressHere
    
    3. Run: python spread_strategy_bidask.py
"""

import time
import logging
import os
from typing import Dict, Any, Optional
from dotenv import load_dotenv

import two_face
from two_face.models import Market, Order, OrderSide
from two_face.base.errors import ExchangeError, InsufficientFunds

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class PolymarketMarketMaker:
    """Market making strategy for Polymarket"""

    def __init__(self, exchange_config: Dict, max_exposure: float = 1000.0):
        self.max_exposure = max_exposure

        config = {
            **exchange_config,
            'rate_limit': 5,
            'max_retries': 3,
            'verbose': False
        }

        self.exchange = two_face.Polymarket(config)
        self.target_market: Optional[Market] = None
        self.trades_executed = 0
        self.placed_orders = []  # Track all placed orders

    def find_suitable_market(self, markets: list) -> Optional[Market]:
        """Find any suitable market for market making"""
        logger.info(f"\nSearching for suitable market among {len(markets)} markets...")
        logger.info("="*80)

        # Filter for binary, open markets with good liquidity
        suitable_markets = []
        for market in markets:
            # Check if binary and open
            if not market.is_binary or not market.is_open:
                continue
            
            # Check if has orderbook data
            if 'spread' not in market.metadata or 'bestBid' not in market.metadata:
                continue
            
            # Require minimum liquidity
            if market.liquidity < 1000:
                continue
            
            suitable_markets.append(market)
        
        if not suitable_markets:
            logger.warning("⚠ No suitable markets found")
            return None
        
        # Pick the first suitable market (or random)
        import random
        selected_market = random.choice(suitable_markets)
        
        logger.info(f"\n✓ Selected market for trading!")
        logger.info(f"   Question: {selected_market.question}")
        logger.info(f"   Market ID: {selected_market.id}")
        logger.info(f"   Volume: ${selected_market.volume:,.0f}")
        logger.info(f"   Liquidity: ${selected_market.liquidity:,.0f}")
        
        return selected_market

    def get_market_data(self, market: Market) -> Optional[Dict[str, Any]]:
        """Get current bid-ask data for the market"""
        # Get bid-ask data from metadata
        if 'spread' not in market.metadata or 'bestBid' not in market.metadata or 'bestAsk' not in market.metadata:
            return None

        spread = float(market.metadata.get('spread', 0))
        best_bid = float(market.metadata.get('bestBid', 0))
        best_ask = float(market.metadata.get('bestAsk', 0))

        # Skip if no real orderbook
        if spread <= 0 or best_bid <= 0 or best_ask <= 0:
            return None

        # Calculate metrics
        mid_price = (best_bid + best_ask) / 2
        spread_pct = (spread / mid_price) * 100 if mid_price > 0 else 0

        return {
            'spread': spread,
            'best_bid': best_bid,
            'best_ask': best_ask,
            'mid_price': mid_price,
            'spread_pct': spread_pct,
            'spread_bps': spread_pct * 100  # basis points
        }

    def execute_market_making(self, data: Dict[str, Any]) -> bool:
        """Execute market making orders (LIVE TRADING)"""
        if not self.target_market:
            return False

        try:
            best_bid = data['best_bid']
            best_ask = data['best_ask']
            mid_price = data['mid_price']
            spread = data['spread']

            # Calculate position size based on liquidity
            base_size = min(100.0, self.target_market.liquidity * 0.01) if self.target_market.liquidity > 0 else 50.0

            # Limit exposure
            position_cost = base_size * mid_price
            if position_cost > self.max_exposure:
                base_size *= self.max_exposure / position_cost

            # Market making strategy: place orders inside the spread
            our_bid = best_bid + (spread * 0.3)  # 30% inside from bid
            our_ask = best_ask - (spread * 0.3)  # 30% inside from ask

            logger.info(f"\n{'='*80}")
            logger.info(f"*** 💰 LIVE MARKET MAKING ***")
            logger.info(f"{'='*80}")
            logger.info(f"Market: {self.target_market.question[:70]}...")
            logger.info(f"Current spread: {spread:.4f} ({data['spread_pct']:.2f}%)")
            logger.info(f"Current best bid: {best_bid:.4f} | best ask: {best_ask:.4f}")
            logger.info(f"Mid price: {mid_price:.4f}")
            logger.info(f"\n📊 PLACING ORDERS:")
            logger.info(f"  BUY order:  {base_size:.2f} shares @ {our_bid:.4f}")
            logger.info(f"  SELL order: {base_size:.2f} shares @ {our_ask:.4f}")

            # Get token ID
            token_id = self.target_market.metadata.get('token_id')
            if not token_id:
                logger.error("❌ Token ID not found in market metadata")
                return False
            
            # Place REAL BUY order
            try:
                buy_order = self.exchange.create_order(
                    market_id=self.target_market.id,
                    outcome='Yes',
                    side=OrderSide.BUY,
                    price=our_bid,
                    size=base_size,
                    params={'token_id': token_id}
                )
                logger.info(f"\n✅ BUY Order Placed!")
                logger.info(f"   Order ID: {buy_order.id}")
                logger.info(f"   Price: {buy_order.price:.4f}")
                logger.info(f"   Size: {buy_order.size:.2f}")
                logger.info(f"   Status: {buy_order.status.value}")
                self.placed_orders.append(('BUY', buy_order))
            except Exception as e:
                logger.error(f"❌ Failed to place BUY order: {e}")
                return False

            # Place REAL SELL order
            try:
                sell_order = self.exchange.create_order(
                    market_id=self.target_market.id,
                    outcome='Yes',
                    side=OrderSide.SELL,
                    price=our_ask,
                    size=base_size,
                    params={'token_id': token_id}
                )
                logger.info(f"\n✅ SELL Order Placed!")
                logger.info(f"   Order ID: {sell_order.id}")
                logger.info(f"   Price: {sell_order.price:.4f}")
                logger.info(f"   Size: {sell_order.size:.2f}")
                logger.info(f"   Status: {sell_order.status.value}")
                self.placed_orders.append(('SELL', sell_order))
            except Exception as e:
                logger.error(f"❌ Failed to place SELL order: {e}")
                # Try to cancel the buy order if sell fails
                try:
                    self.exchange.cancel_order(buy_order.id)
                    logger.info(f"⚠️  Cancelled BUY order {buy_order.id} due to SELL order failure")
                except:
                    pass
                return False

            self.trades_executed += 1

            logger.info(f"\n💰 POTENTIAL PROFIT:")
            logger.info(f"  If both fill: ${base_size * (our_ask - our_bid):.2f}")
            logger.info(f"  Capital required: ${base_size * our_bid:.2f}")
            logger.info(f"  ROI: {((our_ask - our_bid) / our_bid * 100):.2f}%")
            logger.info(f"\n*** 🔴 LIVE ORDERS PLACED - REAL MONEY AT RISK ***")
            logger.info(f"{'='*80}\n")

            return True

        except Exception as e:
            logger.error(f"❌ Error in market making: {e}")
            return False

    def run_strategy(self, duration_minutes: int = 2, check_interval_seconds: int = 30):
        """Run the market making strategy"""
        start_time = time.time()
        end_time = start_time + (duration_minutes * 60)

        logger.info(f"\n{'='*80}")
        logger.info(f"🚀 Polymarket Market Making Strategy - LIVE TRADING")
        logger.info(f"{'='*80}")
        logger.info(f"Mode: 🔴 PRODUCTION (Real Orders)")
        logger.info(f"Duration: {duration_minutes} minutes")
        logger.info(f"Check interval: {check_interval_seconds} seconds")
        logger.info(f"Maximum exposure: ${self.max_exposure:.2f}")
        logger.info(f"{'='*80}\n")
        
        logger.info("")

        # Find a suitable market to trade
        logger.info("Step 1: Finding a suitable market...")
        markets = self.exchange.fetch_markets({'limit': 100})
        self.target_market = self.find_suitable_market(markets)

        if not self.target_market:
            logger.error("❌ Cannot find a suitable market. Exiting.")
            return

        logger.info(f"\n✓ Market selected! Starting market making...\n")

        iteration = 0
        try:
            while time.time() < end_time:
                iteration += 1
                logger.info(f"\n{'─'*80}")
                logger.info(f"⏰ Iteration #{iteration} - {time.strftime('%H:%M:%S')}")
                logger.info(f"{'─'*80}")

                # Refresh market data
                try:
                    self.target_market = self.exchange.fetch_market(self.target_market.id)
                except Exception as e:
                    logger.error(f"Error refreshing market data: {e}")
                    time.sleep(check_interval_seconds)
                    continue

                # Get current market data
                market_data = self.get_market_data(self.target_market)

                if market_data:
                    logger.info(f"\n📈 Current Market Status:")
                    logger.info(f"   Spread: {market_data['spread']:.4f} ({market_data['spread_pct']:.2f}%)")
                    logger.info(f"   Best Bid: {market_data['best_bid']:.4f}")
                    logger.info(f"   Best Ask: {market_data['best_ask']:.4f}")
                    logger.info(f"   Mid Price: {market_data['mid_price']:.4f}")
                    logger.info(f"   Volume: ${self.target_market.volume:,.0f}")
                    logger.info(f"   Liquidity: ${self.target_market.liquidity:,.0f}")

                    # Execute market making
                    self.execute_market_making(market_data)
                else:
                    logger.warning("⚠ No valid market data available for this iteration")

                # Wait for next iteration
                if time.time() < end_time:
                    logger.info(f"\n⏳ Waiting {check_interval_seconds}s until next check...")
                    time.sleep(check_interval_seconds)

        except KeyboardInterrupt:
            logger.info("\n\n⚠ Strategy interrupted by user")
        finally:
            logger.info(f"\n{'='*80}")
            logger.info("✓ STRATEGY COMPLETED")
            logger.info(f"{'='*80}")
            logger.info(f"Market: {self.target_market.question if self.target_market else 'N/A'}")
            logger.info(f"Total iterations: {iteration}")
            logger.info(f"Market making executions: {self.trades_executed}")
            logger.info(f"Total orders placed: {len(self.placed_orders)}")
            
            if self.placed_orders:
                logger.info(f"\n📋 ORDER SUMMARY:")
                logger.info(f"{'─'*80}")
                for i, (side, order) in enumerate(self.placed_orders, 1):
                    logger.info(f"{i}. {side} Order - ID: {order.id}")
                    logger.info(f"   Price: {order.price:.4f} | Size: {order.size:.2f} | Status: {order.status.value}")
                
                # Check final balance
                try:
                    final_balance = self.exchange.fetch_balance()
                    final_usdc = final_balance.get('USDC', 0)
                    logger.info(f"\n💰 Final USDC Balance: ${final_usdc:,.2f}")
                except:
                    pass
                
                logger.info(f"\n⚠️  Remember to check and manage your open orders!")
                logger.info(f"   View orders at: https://polymarket.com/")
            
            logger.info(f"{'='*80}\n")

def main():
    """Main entry point for Polymarket market making strategy"""
    
    # Load environment variables from .env file
    load_dotenv()
    
    # Get credentials from environment variables (REQUIRED)
    private_key = os.getenv('POLYMARKET_PRIVATE_KEY')
    funder = os.getenv('POLYMARKET_FUNDER')
    
    # Validate required credentials
    missing_vars = []
    if not private_key:
        missing_vars.append('POLYMARKET_PRIVATE_KEY')
    if not funder:
        missing_vars.append('POLYMARKET_FUNDER')
    
    if missing_vars:
        logger.error("❌ ERROR: Required environment variables not set!")
        logger.error("")
        for var in missing_vars:
            logger.error(f"   Missing: {var}")
        logger.error("")
        logger.error("Create a .env file in the examples directory with:")
        logger.error("")
        logger.error("   POLYMARKET_PRIVATE_KEY=your_private_key_here")
        logger.error("   POLYMARKET_FUNDER=0xYourFunderAddressHere")
        logger.error("")
        logger.error("Or copy env.example to .env and edit it")
        return
    
    logger.info("\n" + "="*80)
    logger.info("📋 Configuration Check")
    logger.info("="*80)
    logger.info(f"✓ Private Key: {'*' * 10}...{private_key[-6:]}")
    logger.info(f"✓ Funder Address: {funder[:6]}...{funder[-4:]}")
    logger.info("="*80)
    
    logger.warning("\n" + "="*80)
    logger.warning("⚠️  WARNING: LIVE TRADING MODE - REAL MONEY WILL BE USED")
    logger.warning("="*80)
    logger.warning("This strategy will place REAL orders on Polymarket")
    logger.warning("You will be using REAL USDC and taking REAL market risk")
    logger.warning("Orders will be placed via proxy wallet with funder address")
    logger.warning("="*80)
    
    # Wait for user confirmation
    try:
        confirmation = input("\nType 'YES' to continue with LIVE trading: ")
        if confirmation != "YES":
            logger.info("❌ Trading cancelled by user")
            return
    except KeyboardInterrupt:
        logger.info("\n❌ Trading cancelled by user")
        return
    
    exchange_config = {
        'private_key': private_key,
        'funder': funder,  # Add funder address for proxy wallet
        'verbose': True
    }

    strategy = PolymarketMarketMaker(
        exchange_config=exchange_config,
        max_exposure=500.0
    )

    logger.info("\n🚀 Starting LIVE trading strategy...")
    
    # Run for 2 minutes with 30 second intervals
    strategy.run_strategy(duration_minutes=2, check_interval_seconds=30)

if __name__ == "__main__":
    main()
