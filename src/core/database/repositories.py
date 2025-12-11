from datetime import datetime, timedelta
from typing import Optional, List
from sqlalchemy import select, update, and_, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    Market,
    Agent,
    Position,
    Trade,
    Decision,
    AccountSnapshot,
    PerformanceMetric,
    DemoAccount,
    PositionStatus,
    AgentType,
    TradeSide,
    TradeAction,
)


class MarketRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, market_id: str) -> Optional[Market]:
        result = await self.session.execute(
            select(Market).where(Market.id == market_id)
        )
        return result.scalar_one_or_none()

    async def get_active_markets(
        self,
        categories: Optional[List[str]] = None,
        min_liquidity: float = 0,
        min_volume: float = 0,
        limit: int = 100,
    ) -> List[Market]:
        query = select(Market).where(
            and_(
                Market.is_active == True,
                Market.is_resolved == False,
                Market.liquidity >= min_liquidity,
                Market.volume_24h >= min_volume,
            )
        )

        if categories:
            query = query.where(Market.category.in_(categories))

        query = query.order_by(desc(Market.volume_24h)).limit(limit)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def upsert(self, market: Market) -> Market:
        existing = await self.get_by_id(market.id)
        if existing:
            for key, value in market.__dict__.items():
                if not key.startswith("_") and key != "id":
                    setattr(existing, key, value)
            existing.updated_at = datetime.utcnow()
            await self.session.commit()
            return existing
        else:
            self.session.add(market)
            await self.session.commit()
            await self.session.refresh(market)
            return market

    async def bulk_upsert(self, markets: List[Market]) -> List[Market]:
        result = []
        for market in markets:
            result.append(await self.upsert(market))
        return result

    async def update_prices(
        self, market_id: str, yes_price: float, no_price: float
    ) -> None:
        await self.session.execute(
            update(Market)
            .where(Market.id == market_id)
            .values(
                yes_price=yes_price,
                no_price=no_price,
                updated_at=datetime.utcnow(),
            )
        )
        await self.session.commit()


class AgentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, agent_id: int) -> Optional[Agent]:
        result = await self.session.execute(
            select(Agent).where(Agent.id == agent_id)
        )
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> Optional[Agent]:
        result = await self.session.execute(
            select(Agent).where(Agent.name == name)
        )
        return result.scalar_one_or_none()

    async def get_active_agents(self) -> List[Agent]:
        result = await self.session.execute(
            select(Agent).where(Agent.is_active == True)
        )
        return list(result.scalars().all())

    async def create(self, agent: Agent) -> Agent:
        self.session.add(agent)
        await self.session.commit()
        await self.session.refresh(agent)
        return agent

    async def update_stats(
        self, agent_id: int, tokens_used: int, cost: float
    ) -> None:
        await self.session.execute(
            update(Agent)
            .where(Agent.id == agent_id)
            .values(
                total_decisions=Agent.total_decisions + 1,
                total_tokens_used=Agent.total_tokens_used + tokens_used,
                total_cost=Agent.total_cost + cost,
                updated_at=datetime.utcnow(),
            )
        )
        await self.session.commit()


class PositionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, position_id: int) -> Optional[Position]:
        result = await self.session.execute(
            select(Position).where(Position.id == position_id)
        )
        return result.scalar_one_or_none()

    async def get_open_positions(
        self, agent_id: Optional[int] = None
    ) -> List[Position]:
        query = select(Position).where(Position.status == PositionStatus.OPEN)
        if agent_id:
            query = query.where(Position.agent_id == agent_id)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_position_by_market(
        self, agent_id: int, market_id: str, status: PositionStatus = PositionStatus.OPEN
    ) -> Optional[Position]:
        result = await self.session.execute(
            select(Position).where(
                and_(
                    Position.agent_id == agent_id,
                    Position.market_id == market_id,
                    Position.status == status,
                )
            )
        )
        return result.scalar_one_or_none()

    async def create(self, position: Position) -> Position:
        self.session.add(position)
        await self.session.commit()
        await self.session.refresh(position)
        return position

    async def update(self, position: Position) -> Position:
        await self.session.commit()
        await self.session.refresh(position)
        return position

    async def close_position(
        self,
        position_id: int,
        realized_pnl: float,
        exit_reason: Optional[str] = None,
    ) -> None:
        await self.session.execute(
            update(Position)
            .where(Position.id == position_id)
            .values(
                status=PositionStatus.CLOSED,
                realized_pnl=realized_pnl,
                exit_reason=exit_reason,
                closed_at=datetime.utcnow(),
            )
        )
        await self.session.commit()

    async def count_open_positions(self) -> int:
        result = await self.session.execute(
            select(func.count(Position.id)).where(
                Position.status == PositionStatus.OPEN
            )
        )
        return result.scalar() or 0


class TradeRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, trade: Trade) -> Trade:
        self.session.add(trade)
        await self.session.commit()
        await self.session.refresh(trade)
        return trade

    async def get_recent_trades(
        self,
        agent_id: Optional[int] = None,
        limit: int = 50,
    ) -> List[Trade]:
        query = select(Trade).order_by(desc(Trade.executed_at))
        if agent_id:
            query = query.where(Trade.agent_id == agent_id)
        query = query.limit(limit)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_trades_since(
        self, since: datetime, agent_id: Optional[int] = None
    ) -> List[Trade]:
        query = select(Trade).where(Trade.executed_at >= since)
        if agent_id:
            query = query.where(Trade.agent_id == agent_id)
        query = query.order_by(Trade.executed_at)
        result = await self.session.execute(query)
        return list(result.scalars().all())


class DecisionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, decision: Decision) -> Decision:
        self.session.add(decision)
        await self.session.commit()
        await self.session.refresh(decision)
        return decision

    async def get_recent_decisions(
        self,
        agent_id: Optional[int] = None,
        limit: int = 50,
    ) -> List[Decision]:
        query = select(Decision).order_by(desc(Decision.created_at))
        if agent_id:
            query = query.where(Decision.agent_id == agent_id)
        query = query.limit(limit)
        result = await self.session.execute(query)
        return list(result.scalars().all())


class AccountSnapshotRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, snapshot: AccountSnapshot) -> AccountSnapshot:
        self.session.add(snapshot)
        await self.session.commit()
        await self.session.refresh(snapshot)
        return snapshot

    async def get_latest(self, is_demo: bool = True) -> Optional[AccountSnapshot]:
        result = await self.session.execute(
            select(AccountSnapshot)
            .where(AccountSnapshot.is_demo == is_demo)
            .order_by(desc(AccountSnapshot.timestamp))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_history(
        self,
        is_demo: bool = True,
        hours: int = 24,
    ) -> List[AccountSnapshot]:
        since = datetime.utcnow() - timedelta(hours=hours)
        result = await self.session.execute(
            select(AccountSnapshot)
            .where(
                and_(
                    AccountSnapshot.is_demo == is_demo,
                    AccountSnapshot.timestamp >= since,
                )
            )
            .order_by(AccountSnapshot.timestamp)
        )
        return list(result.scalars().all())


class DemoAccountRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_or_create(
        self, name: str = "default", initial_balance: float = 1000.0
    ) -> DemoAccount:
        result = await self.session.execute(
            select(DemoAccount).where(DemoAccount.name == name)
        )
        account = result.scalar_one_or_none()

        if not account:
            account = DemoAccount(
                name=name,
                initial_balance=initial_balance,
                current_balance=initial_balance,
                available_balance=initial_balance,
                high_water_mark=initial_balance,
            )
            self.session.add(account)
            await self.session.commit()
            await self.session.refresh(account)

        return account

    async def update_balance(
        self,
        account_id: int,
        current_balance: float,
        available_balance: float,
        realized_pnl_delta: float = 0,
        unrealized_pnl: float = 0,
    ) -> None:
        # Get current account to check high water mark
        result = await self.session.execute(
            select(DemoAccount).where(DemoAccount.id == account_id)
        )
        account = result.scalar_one()

        high_water_mark = max(account.high_water_mark, current_balance)

        await self.session.execute(
            update(DemoAccount)
            .where(DemoAccount.id == account_id)
            .values(
                current_balance=current_balance,
                available_balance=available_balance,
                total_realized_pnl=DemoAccount.total_realized_pnl + realized_pnl_delta,
                total_unrealized_pnl=unrealized_pnl,
                high_water_mark=high_water_mark,
                updated_at=datetime.utcnow(),
            )
        )
        await self.session.commit()

    async def increment_trades(
        self, account_id: int, is_winner: bool = False
    ) -> None:
        update_values = {
            "total_trades": DemoAccount.total_trades + 1,
            "updated_at": datetime.utcnow(),
        }
        if is_winner:
            update_values["winning_trades"] = DemoAccount.winning_trades + 1

        await self.session.execute(
            update(DemoAccount)
            .where(DemoAccount.id == account_id)
            .values(**update_values)
        )
        await self.session.commit()

    async def suspend(self, account_id: int, reason: str) -> None:
        await self.session.execute(
            update(DemoAccount)
            .where(DemoAccount.id == account_id)
            .values(
                is_suspended=True,
                suspension_reason=reason,
                updated_at=datetime.utcnow(),
            )
        )
        await self.session.commit()
