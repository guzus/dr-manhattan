#!/usr/bin/env python3
"""
FastAPI server for debugging dr-manhattan trading strategies.
Provides REST API endpoints to monitor positions, balances, orders, and markets.
"""

import os
from typing import List, Dict, Any
from datetime import datetime
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import dr_manhattan
from dr_manhattan.models import Market, Order, Position, OrderSide, OrderStatus


load_dotenv()


class BalanceResponse(BaseModel):
    exchange: str
    balances: Dict[str, float]


class PositionResponse(BaseModel):
    exchange: str
    market_id: str
    outcome: str
    size: float
    average_price: float
    current_price: float
    cost_basis: float
    current_value: float
    unrealized_pnl: float
    unrealized_pnl_percent: float


class OrderResponse(BaseModel):
    exchange: str
    id: str
    market_id: str
    outcome: str
    side: str
    price: float
    size: float
    filled: float
    status: str
    created_at: str
    updated_at: str | None


class MarketResponse(BaseModel):
    exchange: str
    id: str
    question: str
    outcomes: List[str]
    close_time: str | None
    volume: float
    liquidity: float
    prices: Dict[str, float]
    is_binary: bool
    is_open: bool
    spread: float | None


class ExchangeInfo(BaseModel):
    id: str
    name: str
    enabled: bool


app = FastAPI(
    title="Dr Manhattan Debug API",
    description="REST API for debugging prediction market trading strategies",
    version="0.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


exchanges = {}


def init_exchanges():
    """Initialize all configured exchanges"""
    global exchanges

    # Initialize Polymarket
    private_key = os.getenv('POLYMARKET_PRIVATE_KEY')
    funder = os.getenv('POLYMARKET_FUNDER')

    if private_key and funder:
        try:
            exchanges['polymarket'] = dr_manhattan.Polymarket({
                'private_key': private_key,
                'funder': funder,
                'cache_ttl': 2.0,
                'verbose': False
            })
            print("Polymarket exchange initialized")
        except Exception as e:
            print(f"Failed to initialize Polymarket: {e}")

    # Initialize Limitless (if configured)
    # Add Limitless initialization here when credentials are available


@app.on_event("startup")
async def startup_event():
    """Initialize exchanges on startup"""
    init_exchanges()


@app.get("/api/exchanges", response_model=List[ExchangeInfo])
async def get_exchanges():
    """Get list of configured exchanges"""
    result = []

    for exchange_id, exchange in exchanges.items():
        result.append(ExchangeInfo(
            id=exchange.id,
            name=exchange.name,
            enabled=True
        ))

    # Add disabled exchanges
    if 'limitless' not in exchanges:
        result.append(ExchangeInfo(
            id='limitless',
            name='Limitless',
            enabled=False
        ))

    return result


@app.get("/api/balances", response_model=List[BalanceResponse])
async def get_balances():
    """Get balances for all exchanges"""
    result = []

    for exchange_id, exchange in exchanges.items():
        try:
            balances = exchange.fetch_balance()
            result.append(BalanceResponse(
                exchange=exchange_id,
                balances=balances
            ))
        except Exception as e:
            print(f"Error fetching balances for {exchange_id}: {e}")
            result.append(BalanceResponse(
                exchange=exchange_id,
                balances={"error": str(e)}
            ))

    return result


@app.get("/api/positions", response_model=List[PositionResponse])
async def get_positions():
    """Get positions for all exchanges"""
    result = []

    for exchange_id, exchange in exchanges.items():
        try:
            positions = exchange.fetch_positions()

            for pos in positions:
                result.append(PositionResponse(
                    exchange=exchange_id,
                    market_id=pos.market_id,
                    outcome=pos.outcome,
                    size=pos.size,
                    average_price=pos.average_price,
                    current_price=pos.current_price,
                    cost_basis=pos.cost_basis,
                    current_value=pos.current_value,
                    unrealized_pnl=pos.unrealized_pnl,
                    unrealized_pnl_percent=pos.unrealized_pnl_percent
                ))
        except Exception as e:
            print(f"Error fetching positions for {exchange_id}: {e}")

    return result


@app.get("/api/orders", response_model=List[OrderResponse])
async def get_orders():
    """Get open orders for all exchanges"""
    result = []

    for exchange_id, exchange in exchanges.items():
        try:
            orders = exchange.fetch_open_orders()

            for order in orders:
                result.append(OrderResponse(
                    exchange=exchange_id,
                    id=order.id,
                    market_id=order.market_id,
                    outcome=order.outcome,
                    side=order.side.value,
                    price=order.price,
                    size=order.size,
                    filled=order.filled,
                    status=order.status.value,
                    created_at=order.created_at.isoformat(),
                    updated_at=order.updated_at.isoformat() if order.updated_at else None
                ))
        except Exception as e:
            print(f"Error fetching orders for {exchange_id}: {e}")

    return result


@app.get("/api/markets", response_model=List[MarketResponse])
async def get_markets(exchange_id: str | None = None, limit: int = 20):
    """Get markets for specified exchange or all exchanges"""
    result = []

    target_exchanges = {exchange_id: exchanges[exchange_id]} if exchange_id and exchange_id in exchanges else exchanges

    for exch_id, exchange in target_exchanges.items():
        try:
            markets = exchange.fetch_markets()

            # Limit the number of markets to avoid overwhelming the frontend
            for market in markets[:limit]:
                result.append(MarketResponse(
                    exchange=exch_id,
                    id=market.id,
                    question=market.question,
                    outcomes=market.outcomes,
                    close_time=market.close_time.isoformat() if market.close_time else None,
                    volume=market.volume,
                    liquidity=market.liquidity,
                    prices=market.prices,
                    is_binary=market.is_binary,
                    is_open=market.is_open,
                    spread=market.spread
                ))
        except Exception as e:
            print(f"Error fetching markets for {exch_id}: {e}")

    return result


@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "ok",
        "exchanges": list(exchanges.keys()),
        "timestamp": datetime.now().isoformat()
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
