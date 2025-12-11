"""
Demo Polymarket Client

모의 거래를 위한 클라이언트
실제 Polymarket API에서 시장 데이터를 가져오지만,
거래는 로컬에서 시뮬레이션합니다.
"""

import asyncio
import uuid
from datetime import datetime
from typing import List, Optional, Dict
from dataclasses import dataclass, field
import structlog

from .client import PolymarketClient, BasePolymarketClient
from .models import (
    MarketData,
    OrderBook,
    Order,
    OrderResult,
    TradeResult,
    PositionData,
    Side,
    OutcomeSide,
    OrderStatus,
)

logger = structlog.get_logger()


@dataclass
class DemoPosition:
    """데모 포지션"""

    id: str
    market_id: str
    token_id: str
    outcome_side: OutcomeSide
    size: float
    average_price: float
    opened_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class DemoOrder:
    """데모 주문"""

    id: str
    market_id: str
    token_id: str
    side: Side
    outcome_side: OutcomeSide
    price: float
    size: float
    filled_size: float = 0.0
    status: OrderStatus = OrderStatus.OPEN
    created_at: datetime = field(default_factory=datetime.utcnow)


class DemoPolymarketClient(BasePolymarketClient):
    """
    데모 거래 클라이언트

    - 실제 Polymarket API에서 시장 데이터 조회
    - 거래는 로컬에서 시뮬레이션
    - 즉시 체결 가정 (시장가 주문처럼 처리)
    """

    def __init__(
        self,
        initial_balance: float = 1000.0,
        fee_rate: float = 0.0,  # Polymarket은 maker 수수료 없음
    ):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.fee_rate = fee_rate

        # Live client for market data
        self._live_client = PolymarketClient()

        # Demo state
        self.positions: Dict[str, DemoPosition] = {}  # token_id -> position
        self.orders: Dict[str, DemoOrder] = {}  # order_id -> order
        self.trades: List[TradeResult] = []
        self.price_cache: Dict[str, float] = {}

        logger.info(
            "Demo client initialized",
            initial_balance=initial_balance,
            fee_rate=fee_rate,
        )

    async def get_markets(
        self,
        categories: Optional[List[str]] = None,
        active_only: bool = True,
        limit: int = 100,
    ) -> List[MarketData]:
        """시장 목록 조회 (실제 API 사용)"""
        markets = await self._live_client.get_markets(
            categories=categories,
            active_only=active_only,
            limit=limit,
        )

        # Update price cache
        for market in markets:
            if market.yes_token_id:
                self.price_cache[market.yes_token_id] = market.yes_price
            if market.no_token_id:
                self.price_cache[market.no_token_id] = market.no_price

        return markets

    async def get_market(self, market_id: str) -> Optional[MarketData]:
        """특정 시장 조회"""
        market = await self._live_client.get_market(market_id)

        if market:
            if market.yes_token_id:
                self.price_cache[market.yes_token_id] = market.yes_price
            if market.no_token_id:
                self.price_cache[market.no_token_id] = market.no_price

        return market

    async def get_order_book(self, token_id: str) -> Optional[OrderBook]:
        """오더북 조회"""
        return await self._live_client.get_order_book(token_id)

    async def get_price(self, token_id: str) -> Optional[float]:
        """현재 가격 조회"""
        price = await self._live_client.get_price(token_id)
        if price:
            self.price_cache[token_id] = price
        return price

    async def refresh_prices(self, token_ids: List[str]) -> Dict[str, float]:
        """가격 일괄 갱신"""
        prices = await self._live_client.get_prices(token_ids)
        self.price_cache.update(prices)
        return prices

    async def place_order(self, order: Order) -> OrderResult:
        """
        데모 주문 실행

        즉시 체결로 시뮬레이션 (시장가 주문처럼)
        """
        order_id = str(uuid.uuid4())

        # Get current price
        current_price = await self.get_price(order.token_id)
        if current_price is None:
            current_price = order.price

        # Calculate total cost/proceeds
        total_cost = order.size * current_price
        fee = total_cost * self.fee_rate

        # Check balance for buy orders
        if order.side == Side.BUY:
            required = total_cost + fee
            if required > self.balance:
                return OrderResult(
                    success=False,
                    error_message=f"Insufficient balance. Required: ${required:.2f}, Available: ${self.balance:.2f}",
                )

        # Check position for sell orders
        if order.side == Side.SELL:
            position = self.positions.get(order.token_id)
            if not position or position.size < order.size:
                available = position.size if position else 0
                return OrderResult(
                    success=False,
                    error_message=f"Insufficient position. Required: {order.size}, Available: {available}",
                )

        # Execute trade
        try:
            if order.side == Side.BUY:
                self._execute_buy(order, current_price, fee)
            else:
                self._execute_sell(order, current_price, fee)

            # Record trade
            trade = TradeResult(
                trade_id=str(uuid.uuid4()),
                order_id=order_id,
                market_id=order.market_id,
                side=order.side,
                outcome_side=order.outcome_side,
                size=order.size,
                price=current_price,
                fee=fee,
            )
            self.trades.append(trade)

            logger.info(
                "Demo trade executed",
                order_id=order_id,
                side=order.side.value,
                outcome=order.outcome_side.value,
                size=order.size,
                price=current_price,
                fee=fee,
                balance=self.balance,
            )

            return OrderResult(
                success=True,
                order_id=order_id,
                status=OrderStatus.FILLED,
                filled_size=order.size,
                average_price=current_price,
            )

        except Exception as e:
            logger.error(f"Demo trade failed: {e}")
            return OrderResult(
                success=False,
                error_message=str(e),
            )

    def _execute_buy(self, order: Order, price: float, fee: float):
        """매수 실행"""
        total_cost = order.size * price + fee
        self.balance -= total_cost

        # Update or create position
        position = self.positions.get(order.token_id)
        if position:
            # Average up/down
            total_size = position.size + order.size
            total_cost_basis = (
                position.size * position.average_price + order.size * price
            )
            position.average_price = total_cost_basis / total_size
            position.size = total_size
        else:
            self.positions[order.token_id] = DemoPosition(
                id=str(uuid.uuid4()),
                market_id=order.market_id,
                token_id=order.token_id,
                outcome_side=order.outcome_side,
                size=order.size,
                average_price=price,
            )

    def _execute_sell(self, order: Order, price: float, fee: float):
        """매도 실행"""
        proceeds = order.size * price - fee
        self.balance += proceeds

        # Update position
        position = self.positions[order.token_id]
        position.size -= order.size

        # Remove position if fully closed
        if position.size <= 0:
            del self.positions[order.token_id]

    async def cancel_order(self, order_id: str) -> bool:
        """주문 취소 (데모에서는 즉시 체결이므로 사실상 불필요)"""
        order = self.orders.get(order_id)
        if order and order.status == OrderStatus.OPEN:
            order.status = OrderStatus.CANCELLED
            return True
        return False

    async def get_positions(self) -> List[PositionData]:
        """포지션 조회"""
        positions = []

        for token_id, pos in self.positions.items():
            current_price = self.price_cache.get(token_id, pos.average_price)

            positions.append(
                PositionData(
                    market_id=pos.market_id,
                    token_id=pos.token_id,
                    outcome_side=pos.outcome_side,
                    size=pos.size,
                    average_price=pos.average_price,
                    current_price=current_price,
                )
            )

        return positions

    async def get_balance(self) -> float:
        """잔고 조회"""
        return self.balance

    async def get_equity(self) -> float:
        """총 자산 (잔고 + 포지션 가치)"""
        positions = await self.get_positions()
        position_value = sum(p.value for p in positions)
        return self.balance + position_value

    async def get_unrealized_pnl(self) -> float:
        """미실현 손익"""
        positions = await self.get_positions()
        return sum(p.unrealized_pnl for p in positions)

    async def get_realized_pnl(self) -> float:
        """실현 손익"""
        equity = await self.get_equity()
        # 실현 손익 = 현재 자산 - 초기 자산 - 미실현 손익
        unrealized = await self.get_unrealized_pnl()
        return equity - self.initial_balance - unrealized

    def get_trade_history(self, limit: int = 50) -> List[TradeResult]:
        """거래 내역"""
        return sorted(
            self.trades, key=lambda t: t.timestamp, reverse=True
        )[:limit]

    async def simulate_resolution(
        self, market_id: str, winning_side: OutcomeSide
    ) -> float:
        """
        시장 결과 시뮬레이션

        승리한 쪽은 $1.00로 정산, 패배한 쪽은 $0.00으로 정산
        """
        pnl = 0.0

        positions_to_remove = []

        for token_id, position in self.positions.items():
            if position.market_id != market_id:
                continue

            if position.outcome_side == winning_side:
                # Winner: shares worth $1.00 each
                settlement = position.size * 1.0
            else:
                # Loser: shares worth $0.00
                settlement = 0.0

            cost_basis = position.size * position.average_price
            position_pnl = settlement - cost_basis

            self.balance += settlement
            pnl += position_pnl

            positions_to_remove.append(token_id)

            logger.info(
                "Position resolved",
                market_id=market_id,
                outcome=position.outcome_side.value,
                winning_side=winning_side.value,
                size=position.size,
                settlement=settlement,
                pnl=position_pnl,
            )

        # Remove resolved positions
        for token_id in positions_to_remove:
            del self.positions[token_id]

        return pnl

    def reset(self):
        """데모 계정 리셋"""
        self.balance = self.initial_balance
        self.positions.clear()
        self.orders.clear()
        self.trades.clear()
        logger.info("Demo account reset", balance=self.balance)

    async def close(self):
        """클라이언트 종료"""
        await self._live_client.close()
