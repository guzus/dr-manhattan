"""
Persistent Demo Polymarket Client

SQLite DB를 사용하여 데이터를 영속화하는 데모 클라이언트.
서버 재시작 시에도 포지션, 거래 내역, 잔고 등이 유지됩니다.
"""

import asyncio
import uuid
from datetime import datetime
from typing import List, Optional, Dict
from dataclasses import dataclass, field
import structlog

from sqlalchemy import select, update, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

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
from ..database.connection import get_db_session, init_db, AsyncSessionLocal
from ..database.models import (
    Position as DBPosition,
    Trade as DBTrade,
    DemoAccount,
    AccountSnapshot,
    PositionStatus,
    TradeSide,
    TradeAction,
)

logger = structlog.get_logger()


class PersistentDemoClient(BasePolymarketClient):
    """
    SQLite DB를 사용하는 영속적 데모 거래 클라이언트

    - 실제 Polymarket API에서 시장 데이터 조회
    - 거래는 로컬에서 시뮬레이션
    - 모든 데이터는 SQLite에 저장되어 서버 재시작 후에도 유지
    """

    def __init__(
        self,
        initial_balance: float = 1000.0,
        fee_rate: float = 0.0,
        account_name: str = "default",
    ):
        self.initial_balance = initial_balance
        self.fee_rate = fee_rate
        self.account_name = account_name

        # Live client for market data
        self._live_client = PolymarketClient()

        # Price cache (in-memory for performance)
        self.price_cache: Dict[str, float] = {}

        # DB session
        self._session: Optional[AsyncSession] = None
        self._account: Optional[DemoAccount] = None
        self._initialized = False

        logger.info(
            "Persistent demo client created",
            initial_balance=initial_balance,
            fee_rate=fee_rate,
            account_name=account_name,
        )

    async def initialize(self):
        """데이터베이스 초기화 및 계정 로드/생성"""
        if self._initialized:
            return

        # Initialize database tables
        await init_db()

        # Get or create demo account
        async with get_db_session() as session:
            result = await session.execute(
                select(DemoAccount).where(DemoAccount.name == self.account_name)
            )
            account = result.scalar_one_or_none()

            if not account:
                account = DemoAccount(
                    name=self.account_name,
                    initial_balance=self.initial_balance,
                    current_balance=self.initial_balance,
                    available_balance=self.initial_balance,
                    high_water_mark=self.initial_balance,
                )
                session.add(account)
                await session.commit()
                await session.refresh(account)
                logger.info("Created new demo account", name=self.account_name, balance=self.initial_balance)
            else:
                logger.info("Loaded existing demo account", name=self.account_name, balance=account.current_balance)

            self._account = account

        self._initialized = True

    async def _ensure_initialized(self):
        """초기화 확인"""
        if not self._initialized:
            await self.initialize()

    @property
    def balance(self) -> float:
        """현재 잔고 (동기적 접근용)"""
        return self._account.available_balance if self._account else self.initial_balance

    async def get_markets(
        self,
        categories: Optional[List[str]] = None,
        active_only: bool = True,
        limit: int = 100,
    ) -> List[MarketData]:
        """시장 목록 조회 (실제 API 사용)"""
        await self._ensure_initialized()

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
        await self._ensure_initialized()

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
        """데모 주문 실행 (DB에 영속화)"""
        await self._ensure_initialized()

        order_id = str(uuid.uuid4())

        # Get current price
        current_price = await self.get_price(order.token_id)
        if current_price is None:
            current_price = order.price

        # Calculate total cost/proceeds
        total_cost = order.size * current_price
        fee = total_cost * self.fee_rate

        async with get_db_session() as session:
            # Reload account
            result = await session.execute(
                select(DemoAccount).where(DemoAccount.id == self._account.id)
            )
            account = result.scalar_one()

            # Check balance for buy orders
            if order.side == Side.BUY:
                required = total_cost + fee
                if required > account.available_balance:
                    return OrderResult(
                        success=False,
                        error_message=f"Insufficient balance. Required: ${required:.2f}, Available: ${account.available_balance:.2f}",
                    )

            # Check position for sell orders
            if order.side == Side.SELL:
                pos_result = await session.execute(
                    select(DBPosition).where(
                        and_(
                            DBPosition.token_id == order.token_id,
                            DBPosition.status == PositionStatus.OPEN,
                        )
                    )
                )
                position = pos_result.scalar_one_or_none()

                if not position or position.size < order.size:
                    available = position.size if position else 0
                    return OrderResult(
                        success=False,
                        error_message=f"Insufficient position. Required: {order.size}, Available: {available}",
                    )

            # Execute trade
            try:
                if order.side == Side.BUY:
                    await self._execute_buy(session, account, order, current_price, fee)
                else:
                    await self._execute_sell(session, account, order, current_price, fee)

                # Record trade
                trade_id = str(uuid.uuid4())
                db_trade = DBTrade(
                    trade_id=trade_id,
                    order_id=order_id,
                    market_id=order.market_id,
                    token_id=order.token_id,
                    action=TradeAction.BUY if order.side == Side.BUY else TradeAction.SELL,
                    side=TradeSide.YES if order.outcome_side == OutcomeSide.YES else TradeSide.NO,
                    size=order.size,
                    price=current_price,
                    total_cost=total_cost,
                    fee=fee,
                    is_demo=True,
                    executed_at=datetime.utcnow(),
                )
                session.add(db_trade)

                await session.commit()

                # Refresh account
                await session.refresh(account)
                self._account = account

                logger.info(
                    "Demo trade executed and persisted",
                    order_id=order_id,
                    trade_id=trade_id,
                    side=order.side.value,
                    outcome=order.outcome_side.value,
                    size=order.size,
                    price=current_price,
                    fee=fee,
                    balance=account.available_balance,
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

    async def _execute_buy(
        self,
        session: AsyncSession,
        account: DemoAccount,
        order: Order,
        price: float,
        fee: float,
    ):
        """매수 실행"""
        total_cost = order.size * price + fee

        # Update account balance
        account.available_balance -= total_cost
        account.current_balance = account.available_balance

        # Check for existing position
        result = await session.execute(
            select(DBPosition).where(
                and_(
                    DBPosition.token_id == order.token_id,
                    DBPosition.status == PositionStatus.OPEN,
                )
            )
        )
        position = result.scalar_one_or_none()

        if position:
            # Average up/down
            total_size = position.size + order.size
            total_cost_basis = position.cost_basis + (order.size * price)
            position.entry_price = total_cost_basis / total_size
            position.size = total_size
            position.cost_basis = total_cost_basis
            position.current_price = price
        else:
            # Create new position
            position = DBPosition(
                market_id=order.market_id,
                token_id=order.token_id,
                side=TradeSide.YES if order.outcome_side == OutcomeSide.YES else TradeSide.NO,
                size=order.size,
                entry_price=price,
                current_price=price,
                cost_basis=order.size * price,
                status=PositionStatus.OPEN,
                opened_at=datetime.utcnow(),
            )
            session.add(position)

    async def _execute_sell(
        self,
        session: AsyncSession,
        account: DemoAccount,
        order: Order,
        price: float,
        fee: float,
    ):
        """매도 실행"""
        proceeds = order.size * price - fee

        # Update account balance
        account.available_balance += proceeds
        account.current_balance = account.available_balance

        # Update position
        result = await session.execute(
            select(DBPosition).where(
                and_(
                    DBPosition.token_id == order.token_id,
                    DBPosition.status == PositionStatus.OPEN,
                )
            )
        )
        position = result.scalar_one()

        # Calculate realized PnL
        cost_basis_for_sold = (position.cost_basis / position.size) * order.size
        realized_pnl = proceeds - cost_basis_for_sold

        position.size -= order.size
        position.cost_basis -= cost_basis_for_sold
        position.realized_pnl += realized_pnl

        # Close position if fully sold
        if position.size <= 0.0001:  # Small threshold for float comparison
            position.status = PositionStatus.CLOSED
            position.closed_at = datetime.utcnow()
            position.size = 0

        # Update account realized PnL
        account.total_realized_pnl += realized_pnl
        if realized_pnl > 0:
            account.winning_trades += 1
        account.total_trades += 1

        # Update high water mark
        if account.current_balance > account.high_water_mark:
            account.high_water_mark = account.current_balance

    async def cancel_order(self, order_id: str) -> bool:
        """주문 취소 (데모에서는 즉시 체결이므로 사실상 불필요)"""
        return False

    async def get_positions(self) -> List[PositionData]:
        """포지션 조회 (DB에서)"""
        await self._ensure_initialized()

        async with get_db_session() as session:
            result = await session.execute(
                select(DBPosition).where(DBPosition.status == PositionStatus.OPEN)
            )
            db_positions = result.scalars().all()

            positions = []
            for pos in db_positions:
                current_price = self.price_cache.get(pos.token_id, pos.current_price)

                positions.append(
                    PositionData(
                        market_id=pos.market_id,
                        token_id=pos.token_id,
                        outcome_side=OutcomeSide.YES if pos.side == TradeSide.YES else OutcomeSide.NO,
                        size=pos.size,
                        average_price=pos.entry_price,
                        current_price=current_price,
                    )
                )

            return positions

    async def get_balance(self) -> float:
        """잔고 조회"""
        await self._ensure_initialized()

        async with get_db_session() as session:
            result = await session.execute(
                select(DemoAccount).where(DemoAccount.id == self._account.id)
            )
            account = result.scalar_one()
            return account.available_balance

    async def get_equity(self) -> float:
        """총 자산 (잔고 + 포지션 가치)"""
        await self._ensure_initialized()

        balance = await self.get_balance()
        positions = await self.get_positions()
        position_value = sum(p.value for p in positions)
        return balance + position_value

    async def get_unrealized_pnl(self) -> float:
        """미실현 손익"""
        positions = await self.get_positions()
        return sum(p.unrealized_pnl for p in positions)

    async def get_realized_pnl(self) -> float:
        """실현 손익"""
        await self._ensure_initialized()

        async with get_db_session() as session:
            result = await session.execute(
                select(DemoAccount).where(DemoAccount.id == self._account.id)
            )
            account = result.scalar_one()
            return account.total_realized_pnl

    def get_trade_history(self, limit: int = 50) -> List[TradeResult]:
        """동기적 거래 내역 조회 (호환성을 위해)"""
        # 이 메서드는 동기적으로 호출되므로 async 버전을 사용해야 함
        # 기존 코드와의 호환성을 위해 빈 리스트 반환
        return []

    async def get_trade_history_async(self, limit: int = 50) -> List[TradeResult]:
        """거래 내역 조회 (DB에서)"""
        await self._ensure_initialized()

        async with get_db_session() as session:
            result = await session.execute(
                select(DBTrade)
                .order_by(desc(DBTrade.executed_at))
                .limit(limit)
            )
            db_trades = result.scalars().all()

            trades = []
            for t in db_trades:
                trades.append(
                    TradeResult(
                        trade_id=t.trade_id,
                        order_id=t.order_id or "",
                        market_id=t.market_id,
                        side=Side.BUY if t.action == TradeAction.BUY else Side.SELL,
                        outcome_side=OutcomeSide.YES if t.side == TradeSide.YES else OutcomeSide.NO,
                        size=t.size,
                        price=t.price,
                        fee=t.fee,
                        timestamp=t.executed_at,
                    )
                )

            return trades

    async def record_equity_snapshot(self):
        """현재 equity를 스냅샷으로 기록"""
        await self._ensure_initialized()

        equity = await self.get_equity()
        balance = await self.get_balance()
        unrealized_pnl = await self.get_unrealized_pnl()
        realized_pnl = await self.get_realized_pnl()
        positions = await self.get_positions()

        async with get_db_session() as session:
            snapshot = AccountSnapshot(
                timestamp=datetime.utcnow(),
                total_equity=equity,
                available_balance=balance,
                unrealized_pnl=unrealized_pnl,
                realized_pnl=realized_pnl,
                daily_pnl=0.0,  # TODO: calculate daily PnL
                open_positions_count=len(positions),
                total_positions_value=sum(p.value for p in positions),
                is_demo=True,
            )
            session.add(snapshot)
            await session.commit()

        logger.debug("Equity snapshot recorded", equity=equity)

    async def get_equity_history(self, limit: int = 1000) -> List[Dict]:
        """Equity 히스토리 조회"""
        await self._ensure_initialized()

        async with get_db_session() as session:
            result = await session.execute(
                select(AccountSnapshot)
                .where(AccountSnapshot.is_demo == True)
                .order_by(desc(AccountSnapshot.timestamp))
                .limit(limit)
            )
            snapshots = result.scalars().all()

            return [
                {
                    "timestamp": s.timestamp.isoformat(),
                    "equity": s.total_equity,
                }
                for s in reversed(snapshots)  # 오래된 것부터
            ]

    async def reset(self):
        """데모 계정 리셋"""
        await self._ensure_initialized()

        async with get_db_session() as session:
            # Close all open positions
            await session.execute(
                update(DBPosition)
                .where(DBPosition.status == PositionStatus.OPEN)
                .values(status=PositionStatus.CLOSED, closed_at=datetime.utcnow())
            )

            # Reset account
            result = await session.execute(
                select(DemoAccount).where(DemoAccount.id == self._account.id)
            )
            account = result.scalar_one()

            account.current_balance = account.initial_balance
            account.available_balance = account.initial_balance
            account.total_realized_pnl = 0.0
            account.total_unrealized_pnl = 0.0
            account.high_water_mark = account.initial_balance
            account.total_trades = 0
            account.winning_trades = 0

            await session.commit()
            self._account = account

        logger.info("Demo account reset", balance=self.initial_balance)

    async def close(self):
        """클라이언트 종료"""
        await self._live_client.close()
