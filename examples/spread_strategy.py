#!/usr/bin/env python3
"""
Market Making Strategy for Polymarket - LIVE TRADING

⚠️  WARNING: This script places REAL orders with REAL money on Polymarket!

This strategy provides liquidity (market making) on a random market
by placing bid and ask orders inside the spread.

Requirements:
- Install dependencies: uv sync
- Create .env file in project root with your credentials
- Ensure you have USDC balance on Polygon network

Usage:
    1. Create .env in project root:
       POLYMARKET_PRIVATE_KEY=0x...
       POLYMARKET_FUNDER=0x...
    
    2. Run from project root:
       uv run examples/spread_strategy.py
"""

import time
import os
from typing import Dict, Any, Optional
from dotenv import load_dotenv

import two_face
from two_face.models import Market, Order, OrderSide
from two_face.base.errors import ExchangeError, InsufficientFunds
from two_face.utils import setup_logger

# Setup logger
logger = setup_logger(__name__)

class PolymarketMarketMaker:
    """Market making strategy for Polymarket"""

    def __init__(self, exchange_config: Dict, max_exposure: float = 1000.0):
        self.max_exposure = max_exposure

        config = {
            **exchange_config,
            'rate_limit': 5,
            'max_retries': 3,
            'verbose': True  # Enable verbose to see token ID fetching
        }

        self.exchange = two_face.Polymarket(config)
        self.target_market: Optional[Market] = None
        self.trades_executed = 0
        self.placed_orders = []  # Track all placed orders

    def find_suitable_market(self, markets: list) -> Optional[Market]:
        """Find any suitable market for market making"""
        logger.info(f"\nSearching for suitable market among {len(markets)} markets...")
        logger.info("="*80)

        # Debug counters
        debug_stats = {
            'total': len(markets),
            'not_binary': 0,
            'not_open': 0,
            'no_token_ids': 0,
            'not_accepting': 0,
            'suitable': 0
        }

        # Filter for binary, open markets with token IDs
        suitable_markets = []
        for market in markets:
            # Check if binary and open  
            if not market.is_binary:
                debug_stats['not_binary'] += 1
                continue
            
            if not market.is_open:
                debug_stats['not_open'] += 1
                continue
            
            # Check if has token IDs (required for trading)
            if 'clobTokenIds' not in market.metadata:
                debug_stats['no_token_ids'] += 1
                continue
            
            token_ids = market.metadata.get('clobTokenIds', [])
            if not token_ids or len(token_ids) < 1:
                debug_stats['no_token_ids'] += 1
                continue
            
            # Market is suitable (is_open already checks accepting_orders)
            debug_stats['suitable'] += 1
            suitable_markets.append(market)
        
        # Log debug stats
        logger.info(f"\n📊 Market Filtering Results:")
        logger.info(f"   Total markets: {debug_stats['total']}")
        logger.info(f"   Not binary: {debug_stats['not_binary']}")
        logger.info(f"   Not open: {debug_stats['not_open']}")
        logger.info(f"   No token IDs: {debug_stats['no_token_ids']}")
        logger.info(f"   Not accepting orders: {debug_stats['not_accepting']}")
        logger.info(f"   ✓ Suitable: {debug_stats['suitable']}")
        
        if not suitable_markets:
            logger.warning("\n⚠ No suitable markets found")
            
            # Show sample market for debugging
            if markets:
                sample = markets[0]
                logger.info(f"\n🔍 Sample market for debugging:")
                logger.info(f"   ID: {sample.id[:20]}...")
                logger.info(f"   Outcomes: {sample.outcomes}")
                logger.info(f"   Is binary: {sample.is_binary}")
                logger.info(f"   Is open: {sample.is_open}")
                logger.info(f"   Has clobTokenIds: {'clobTokenIds' in sample.metadata}")
                logger.info(f"   Metadata keys: {list(sample.metadata.keys())[:10]}")
            
            return None
        
        # Pick a random market
        import random
        selected_market = random.choice(suitable_markets)
        
        logger.info(f"\n✓ Selected market for trading!")
        logger.info(f"   Market ID: {selected_market.id[:16]}...")
        logger.info(f"   Outcomes: {', '.join(selected_market.outcomes)}")
        logger.info(f"   Token IDs: {len(selected_market.metadata.get('clobTokenIds', []))} tokens")
        logger.info(f"   Status: {'Active' if selected_market.is_open else 'Closed'}")
        
        return selected_market

    def get_market_data(self, market: Market) -> Optional[Dict[str, Any]]:
        """Get current bid-ask data for the market"""
        # Get token ID from metadata (should already be there from CLOB API)
        token_ids = market.metadata.get('clobTokenIds', [])
        if not token_ids or len(token_ids) < 1:
            logger.warning(f"⚠️  No token IDs for market {market.id}")
            return None
        
        token_id = token_ids[0]  # Use first token for trading
        
        # Get token prices from metadata (from sampling-markets)
        tokens_data = market.metadata.get('tokens', [])
        if not tokens_data or len(tokens_data) < 2:
            logger.warning(f"⚠️  No token price data")
            return None
        
        # Get the YES token price (usually index 0)
        yes_token = tokens_data[0] if tokens_data[0].get('outcome') == 'Yes' else tokens_data[1]
        mid_price = float(yes_token.get('price', 0))
        
        if mid_price <= 0 or mid_price >= 1:
            logger.warning(f"⚠️  Invalid mid price: {mid_price}")
            return None
        
        # Simulate a 2% spread around mid price for market making
        # In real trading, you'd fetch actual orderbook
        spread_pct = 2.0
        spread = mid_price * (spread_pct / 100)
        best_bid = mid_price - (spread / 2)
        best_ask = mid_price + (spread / 2)
        
        # Clamp to valid range [0.01, 0.99]
        best_bid = max(0.01, min(0.99, best_bid))
        best_ask = max(0.01, min(0.99, best_ask))
        
        # Ensure bid < ask
        if best_bid >= best_ask:
            logger.warning(f"⚠️  Invalid bid/ask after clamping")
            return None
        
        return {
            'spread': best_ask - best_bid,
            'best_bid': best_bid,
            'best_ask': best_ask,
            'mid_price': mid_price,
            'spread_pct': spread_pct,
            'spread_bps': spread_pct * 100,  # basis points
            'token_id': token_id
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
            base_size = min(20.0, self.target_market.liquidity * 0.01) if self.target_market.liquidity > 0 else 10.0

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

            # Get token ID from market data
            token_id = data.get('token_id')
            if not token_id:
                logger.error("❌ Token ID not available")
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
        
        consecutive_failures = 0
        max_consecutive_failures = 5

        iteration = 0
        try:
            while time.time() < end_time:
                iteration += 1
                logger.info(f"\n{'─'*80}")
                logger.info(f"⏰ Iteration #{iteration} - {time.strftime('%H:%M:%S')}")
                logger.info(f"{'─'*80}")

                # Get current market data (fetches fresh orderbook)
                market_data = self.get_market_data(self.target_market)

                if market_data:
                    consecutive_failures = 0  # Reset counter on success
                    logger.info(f"\n📈 Current Market Status:")
                    logger.info(f"   Spread: {market_data['spread']:.4f} ({market_data['spread_pct']:.2f}%)")
                    logger.info(f"   Best Bid: {market_data['best_bid']:.4f}")
                    logger.info(f"   Best Ask: {market_data['best_ask']:.4f}")
                    logger.info(f"   Mid Price: {market_data['mid_price']:.4f}")

                    # Execute market making
                    self.execute_market_making(market_data)
                else:
                    consecutive_failures += 1
                    logger.warning(f"⚠ No valid market data available for this iteration (failure {consecutive_failures}/{max_consecutive_failures})")
                    
                    # If too many failures, try to find a new market
                    if consecutive_failures >= max_consecutive_failures:
                        logger.warning(f"\n⚠️  Too many consecutive failures with current market")
                        logger.info("🔄 Attempting to find a new market...")
                        
                        new_market = self.find_suitable_market(markets)
                        if new_market and new_market.id != self.target_market.id:
                            self.target_market = new_market
                            consecutive_failures = 0
                            logger.info("✓ Switched to new market!")
                        else:
                            logger.warning("⚠️  No alternative market found, continuing with current market...")

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
    logger.warning("="*80 + "\n")
    
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
