from datetime import datetime
from decimal import Decimal
from typing import Optional, List
from sqlalchemy import (
    String,
    Integer,
    Float,
    Boolean,
    DateTime,
    Text,
    ForeignKey,
    JSON,
    Index,
    Enum as SQLEnum,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
import enum


class Base(DeclarativeBase):
    pass


class PositionStatus(str, enum.Enum):
    OPEN = "open"
    CLOSED = "closed"
    RESOLVED = "resolved"


class TradeSide(str, enum.Enum):
    YES = "YES"
    NO = "NO"


class TradeAction(str, enum.Enum):
    BUY = "buy"
    SELL = "sell"


class AgentType(str, enum.Enum):
    RESEARCH = "research"
    PROBABILITY = "probability"
    SENTIMENT = "sentiment"
    RISK = "risk"
    EXECUTION = "execution"
    ARBITER = "arbiter"


class Event(Base):
    """Polymarket 이벤트 (상위 컨테이너)

    Event는 여러 Market(Submarket)을 포함합니다.
    예: "Which CEOs will be gone in 2025?" 이벤트에
        "Tim Cook out?" "Elon Musk out?" 등 여러 마켓이 포함됨
    """

    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    slug: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Event-level data
    liquidity: Mapped[float] = mapped_column(Float, default=0.0)
    volume: Mapped[float] = mapped_column(Float, default=0.0)

    # Timeline
    start_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    end_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    markets: Mapped[List["Market"]] = relationship(back_populates="event", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_events_category", "category"),
        Index("ix_events_is_active", "is_active"),
    )


class Market(Base):
    """Polymarket 시장 정보 (Submarket)

    Event 내의 개별 베팅 마켓입니다.
    """

    __tablename__ = "markets"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    event_id: Mapped[Optional[str]] = mapped_column(
        String(255), ForeignKey("events.id"), nullable=True
    )
    condition_id: Mapped[str] = mapped_column(String(255), nullable=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(100), nullable=True)
    end_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Token IDs
    yes_token_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    no_token_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Market Data
    liquidity: Mapped[float] = mapped_column(Float, default=0.0)
    volume_24h: Mapped[float] = mapped_column(Float, default=0.0)
    volume_total: Mapped[float] = mapped_column(Float, default=0.0)

    # Current Prices
    yes_price: Mapped[float] = mapped_column(Float, default=0.5)
    no_price: Mapped[float] = mapped_column(Float, default=0.5)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    resolution: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # YES/NO/NULL

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    event: Mapped[Optional["Event"]] = relationship(back_populates="markets")
    decisions: Mapped[list["Decision"]] = relationship(back_populates="market")

    __table_args__ = (
        Index("ix_markets_category", "category"),
        Index("ix_markets_is_active", "is_active"),
        Index("ix_markets_end_date", "end_date"),
        Index("ix_markets_event_id", "event_id"),
    )


class Agent(Base):
    """LLM Agent 정보"""

    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    type: Mapped[AgentType] = mapped_column(SQLEnum(AgentType), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Statistics
    total_decisions: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    total_cost: Mapped[float] = mapped_column(Float, default=0.0)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    positions: Mapped[list["Position"]] = relationship(back_populates="agent")
    trades: Mapped[list["Trade"]] = relationship(back_populates="agent")
    decisions: Mapped[list["Decision"]] = relationship(back_populates="agent")
    performance_metrics: Mapped[list["PerformanceMetric"]] = relationship(
        back_populates="agent"
    )


class Position(Base):
    """포지션 정보"""

    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("agents.id"), nullable=True)
    market_id: Mapped[str] = mapped_column(String(255), nullable=False)  # No FK for flexibility
    token_id: Mapped[str] = mapped_column(String(255), nullable=False)  # YES or NO token ID

    # Position Details
    side: Mapped[TradeSide] = mapped_column(SQLEnum(TradeSide), nullable=False)
    size: Mapped[float] = mapped_column(Float, nullable=False)  # Number of shares
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    current_price: Mapped[float] = mapped_column(Float, nullable=False)

    # Cost & PnL
    cost_basis: Mapped[float] = mapped_column(Float, nullable=False)  # Total cost
    unrealized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)

    # Status
    status: Mapped[PositionStatus] = mapped_column(
        SQLEnum(PositionStatus), default=PositionStatus.OPEN
    )

    # Timestamps
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Agent's reasoning
    entry_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    exit_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    agent: Mapped[Optional["Agent"]] = relationship(back_populates="positions")
    trades: Mapped[list["Trade"]] = relationship(back_populates="position")

    __table_args__ = (
        Index("ix_positions_status", "status"),
        Index("ix_positions_agent_id", "agent_id"),
        Index("ix_positions_token_id", "token_id"),
        Index("ix_positions_market_id", "market_id"),
    )


class Trade(Base):
    """거래 내역"""

    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)  # External trade ID
    position_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("positions.id"), nullable=True
    )
    agent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("agents.id"), nullable=True)
    market_id: Mapped[str] = mapped_column(String(255), nullable=False)  # No FK for flexibility
    token_id: Mapped[str] = mapped_column(String(255), nullable=False)

    # Trade Details
    action: Mapped[TradeAction] = mapped_column(SQLEnum(TradeAction), nullable=False)
    side: Mapped[TradeSide] = mapped_column(SQLEnum(TradeSide), nullable=False)
    size: Mapped[float] = mapped_column(Float, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)

    # Cost
    total_cost: Mapped[float] = mapped_column(Float, nullable=False)
    fee: Mapped[float] = mapped_column(Float, default=0.0)

    # Execution
    order_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)

    # Timestamps
    executed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    position: Mapped[Optional["Position"]] = relationship(back_populates="trades")
    agent: Mapped[Optional["Agent"]] = relationship(back_populates="trades")

    __table_args__ = (
        Index("ix_trades_executed_at", "executed_at"),
        Index("ix_trades_agent_id", "agent_id"),
        Index("ix_trades_trade_id", "trade_id"),
    )


class Decision(Base):
    """Agent 의사결정 로그"""

    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("agents.id"), nullable=True)
    market_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("markets.id"), nullable=True
    )

    # Decision Content
    decision_type: Mapped[str] = mapped_column(String(50), nullable=False)
    decision: Mapped[dict] = mapped_column(JSON, nullable=False)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Trading Decision Details
    action: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # BUY/SELL/HOLD
    side: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # YES/NO
    position_size_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    limit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    market_question: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Agent Analysis Summary
    research_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    probability_assessment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sentiment_analysis: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    risk_assessment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    arbiter_reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # LLM Details (optional for rule-based decisions)
    prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Token Usage
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0.0)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    agent: Mapped[Optional["Agent"]] = relationship(back_populates="decisions")
    market: Mapped[Optional["Market"]] = relationship(back_populates="decisions")

    __table_args__ = (Index("ix_decisions_created_at", "created_at"),)


class AccountSnapshot(Base):
    """계정 스냅샷 (시계열)"""

    __tablename__ = "account_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # Balances
    total_equity: Mapped[float] = mapped_column(Float, nullable=False)
    available_balance: Mapped[float] = mapped_column(Float, nullable=False)

    # PnL
    unrealized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    daily_pnl: Mapped[float] = mapped_column(Float, default=0.0)

    # Positions
    open_positions_count: Mapped[int] = mapped_column(Integer, default=0)
    total_positions_value: Mapped[float] = mapped_column(Float, default=0.0)

    # Mode
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (Index("ix_account_snapshots_timestamp", "timestamp"),)


class PerformanceMetric(Base):
    """Agent별 성과 지표 (시계열)"""

    __tablename__ = "performance_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # Performance
    total_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    total_trades: Mapped[int] = mapped_column(Integer, default=0)
    winning_trades: Mapped[int] = mapped_column(Integer, default=0)
    losing_trades: Mapped[int] = mapped_column(Integer, default=0)

    # Ratios
    win_rate: Mapped[float] = mapped_column(Float, default=0.0)
    profit_factor: Mapped[float] = mapped_column(Float, default=0.0)
    sharpe_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Risk
    max_drawdown: Mapped[float] = mapped_column(Float, default=0.0)
    current_drawdown: Mapped[float] = mapped_column(Float, default=0.0)

    # Relationships
    agent: Mapped["Agent"] = relationship(back_populates="performance_metrics")

    __table_args__ = (
        Index("ix_performance_metrics_timestamp", "timestamp"),
        Index("ix_performance_metrics_agent_id", "agent_id"),
    )


class DemoAccount(Base):
    """데모 계정 (모의투자)"""

    __tablename__ = "demo_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), default="default")

    # Balances
    initial_balance: Mapped[float] = mapped_column(Float, nullable=False)
    current_balance: Mapped[float] = mapped_column(Float, nullable=False)
    available_balance: Mapped[float] = mapped_column(Float, nullable=False)

    # PnL Tracking
    total_realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    total_unrealized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    high_water_mark: Mapped[float] = mapped_column(Float, nullable=False)

    # Statistics
    total_trades: Mapped[int] = mapped_column(Integer, default=0)
    winning_trades: Mapped[int] = mapped_column(Integer, default=0)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_suspended: Mapped[bool] = mapped_column(Boolean, default=False)
    suspension_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
