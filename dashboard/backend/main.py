"""
FastAPI Dashboard Backend

트레이딩 봇 대시보드 API 서버
- WebSocket 실시간 업데이트 지원
- SQLite 데이터 영속화
"""

import asyncio
import sys
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import datetime
from typing import List, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi import FastAPI, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import structlog
from dotenv import load_dotenv

from config.settings import get_settings
from src.scheduler import TradingLoop
from src.core.polymarket.models import OutcomeSide
from src.core.database.connection import init_db
from .websocket_manager import (
    manager as ws_manager,
    broadcast_portfolio_update,
    broadcast_positions_update,
    broadcast_trade,
    broadcast_decision,
    broadcast_status_update,
    broadcast_equity_update,
)

# Load environment
load_dotenv()

logger = structlog.get_logger()

# Global state
trading_loop: Optional[TradingLoop] = None
background_task: Optional[asyncio.Task] = None
equity_update_task: Optional[asyncio.Task] = None

# In-memory decisions storage (also saved to file for persistence)
import json
from pathlib import Path as FilePath

DECISIONS_FILE = FilePath(__file__).parent.parent.parent / "data" / "decisions.json"

def load_decisions() -> List[dict]:
    """Load decisions from file"""
    try:
        if DECISIONS_FILE.exists():
            with open(DECISIONS_FILE, "r") as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load decisions: {e}")
    return []

def save_decisions(decisions: List[dict]):
    """Save decisions to file"""
    try:
        DECISIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(DECISIONS_FILE, "w") as f:
            json.dump(decisions[-100:], f)  # Keep last 100 decisions
    except Exception as e:
        logger.error(f"Failed to save decisions: {e}")

# Load existing decisions on startup
saved_decisions: List[dict] = load_decisions()


# Pydantic Models
class StatusResponse(BaseModel):
    running: bool
    demo_mode: bool
    cycle_count: int
    total_decisions: int
    total_trades: int
    last_run: Optional[str]
    interval_minutes: int
    ws_connections: int = 0


class PortfolioResponse(BaseModel):
    total_equity: float
    available_balance: float
    unrealized_pnl: float
    realized_pnl: float
    daily_pnl: float
    position_count: int
    drawdown_pct: float
    trading_status: str


class PositionResponse(BaseModel):
    market_id: str
    market_question: str
    event_title: Optional[str]
    slug: Optional[str]
    outcome_side: str
    size: float  # shares
    average_price: float  # entry price
    current_price: float
    entry_value: float  # size * average_price
    current_value: float  # size * current_price
    unrealized_pnl: float
    unrealized_pnl_pct: float


class TradeResponse(BaseModel):
    trade_id: str
    market_id: str
    market_question: Optional[str] = None
    event_title: Optional[str] = None
    slug: Optional[str] = None
    side: str
    outcome_side: str
    size: float
    price: float
    total: float
    fee: float
    timestamp: str


class MarketResponse(BaseModel):
    id: str
    question: str
    category: Optional[str]
    event_id: Optional[str] = None
    event_title: Optional[str] = None
    yes_price: float
    no_price: float
    volume_24h: float
    liquidity: float


class EventResponse(BaseModel):
    id: str
    title: str
    category: Optional[str]
    markets: List[MarketResponse]
    liquidity: float
    volume: float


class AgentStatsResponse(BaseModel):
    name: str
    type: str
    total_calls: int
    total_tokens_used: int
    total_cost: float


class DecisionResponse(BaseModel):
    market_id: str
    slug: Optional[str] = None
    decision: str
    confidence: str
    position_size_usd: float
    reasoning: str
    total_tokens: int
    total_cost: float
    timestamp: str


class EquityHistoryResponse(BaseModel):
    timestamp: str
    equity: float


class ManualTradeRequest(BaseModel):
    market_id: str
    side: str  # "YES" or "NO"
    action: str  # "BUY" or "SELL"
    size_usd: float


async def periodic_equity_update():
    """주기적으로 equity 업데이트 브로드캐스트 (5초마다)"""
    while True:
        try:
            if trading_loop and ws_manager.connection_count > 0:
                # Record equity snapshot
                await trading_loop.polymarket_client.record_equity_snapshot()

                # Get current portfolio data
                equity = await trading_loop.polymarket_client.get_equity()
                balance = await trading_loop.polymarket_client.get_balance()
                unrealized_pnl = await trading_loop.polymarket_client.get_unrealized_pnl()
                positions = await trading_loop.polymarket_client.get_positions()

                # Broadcast updates
                await broadcast_equity_update({
                    "timestamp": datetime.utcnow().isoformat(),
                    "equity": equity,
                })

                await broadcast_portfolio_update({
                    "total_equity": equity,
                    "available_balance": balance,
                    "unrealized_pnl": unrealized_pnl,
                    "position_count": len(positions),
                })

        except Exception as e:
            logger.error(f"Periodic equity update failed: {e}")

        await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler"""
    global trading_loop, equity_update_task

    settings = get_settings()

    # Initialize database
    await init_db()

    # Initialize trading loop with persistent client
    trading_loop = TradingLoop(
        openai_api_key=settings.openai_api_key,
        initial_balance=settings.demo_initial_balance,
        interval_minutes=settings.execution_interval_minutes,
        demo_mode=(settings.trading_mode == "demo"),
        use_persistent_client=True,  # Use SQLite-backed client
    )

    # Initialize the client
    await trading_loop.polymarket_client.initialize()

    logger.info("Dashboard backend started with persistent storage")

    # Record initial equity
    await trading_loop.polymarket_client.record_equity_snapshot()

    # Start periodic equity update task
    equity_update_task = asyncio.create_task(periodic_equity_update())

    yield

    # Cleanup
    if equity_update_task:
        equity_update_task.cancel()
        try:
            await equity_update_task
        except asyncio.CancelledError:
            pass

    if trading_loop:
        await trading_loop.close()

    logger.info("Dashboard backend stopped")


# Create FastAPI app
app = FastAPI(
    title="Prediction Market Trading Bot",
    description="AI Agent Trading Bot for Prediction Markets API with WebSocket support",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# WebSocket endpoint
@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    topics: Optional[str] = Query(default=None),
):
    """
    WebSocket 연결 엔드포인트

    Query params:
        topics: 구독할 토픽들 (콤마로 구분). 예: "portfolio,positions,trades"
               가능한 토픽: portfolio, positions, trades, decisions, status, equity, all
               기본값: all
    """
    topic_list = topics.split(",") if topics else ["all"]

    await ws_manager.connect(websocket, topic_list)

    try:
        # 연결 즉시 현재 상태 전송
        if trading_loop:
            equity = await trading_loop.polymarket_client.get_equity()
            balance = await trading_loop.polymarket_client.get_balance()
            positions = await trading_loop.polymarket_client.get_positions()

            await websocket.send_json({
                "type": "initial",
                "data": {
                    "portfolio": {
                        "total_equity": equity,
                        "available_balance": balance,
                        "position_count": len(positions),
                    },
                    "status": trading_loop.get_status(),
                },
                "timestamp": datetime.utcnow().isoformat(),
            })

        # 메시지 수신 대기 (클라이언트가 연결 유지)
        while True:
            data = await websocket.receive_json()

            # 클라이언트 명령 처리
            if data.get("action") == "subscribe":
                await ws_manager.subscribe(websocket, data.get("topics", []))
            elif data.get("action") == "unsubscribe":
                await ws_manager.unsubscribe(websocket, data.get("topics", []))
            elif data.get("action") == "ping":
                await websocket.send_json({"type": "pong", "timestamp": datetime.utcnow().isoformat()})

    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await ws_manager.disconnect(websocket)


# REST API Routes
@app.get("/")
async def root():
    return {"message": "Prediction Market Trading Bot API", "status": "running", "version": "2.0.0"}


@app.get("/api/status", response_model=StatusResponse)
async def get_status():
    """봇 상태 조회"""
    if not trading_loop:
        raise HTTPException(status_code=503, detail="Trading loop not initialized")

    status = trading_loop.get_status()
    return StatusResponse(
        running=status["running"],
        demo_mode=status["demo_mode"],
        cycle_count=status["cycle_count"],
        total_decisions=status["total_decisions"],
        total_trades=status["total_trades"],
        last_run=status["last_run"],
        interval_minutes=status["interval_minutes"],
        ws_connections=ws_manager.connection_count,
    )


@app.get("/api/portfolio", response_model=PortfolioResponse)
async def get_portfolio():
    """포트폴리오 상태 조회"""
    if not trading_loop:
        raise HTTPException(status_code=503, detail="Trading loop not initialized")

    equity = await trading_loop.polymarket_client.get_equity()
    balance = await trading_loop.polymarket_client.get_balance()
    unrealized_pnl = await trading_loop.polymarket_client.get_unrealized_pnl()
    realized_pnl = await trading_loop.polymarket_client.get_realized_pnl()
    positions = await trading_loop.polymarket_client.get_positions()

    metrics = trading_loop.risk_manager.get_portfolio_metrics()

    return PortfolioResponse(
        total_equity=equity,
        available_balance=balance,
        unrealized_pnl=unrealized_pnl,
        realized_pnl=realized_pnl,
        daily_pnl=metrics.daily_pnl,
        position_count=len(positions),
        drawdown_pct=metrics.current_drawdown_pct,
        trading_status=metrics.trading_status.value,
    )


@app.get("/api/positions", response_model=List[PositionResponse])
async def get_positions():
    """현재 포지션 조회"""
    if not trading_loop:
        raise HTTPException(status_code=503, detail="Trading loop not initialized")

    positions = await trading_loop.polymarket_client.get_positions()

    result = []
    for p in positions:
        # 마켓 정보 조회 (캐시 또는 API)
        market = await trading_loop.polymarket_client.get_market(p.market_id)
        market_question = market.question if market else f"Market {p.market_id[:8]}..."
        event_title = getattr(market, 'event_title', None) if market else None
        slug = getattr(market, 'slug', None) if market else None

        # Calculate values
        entry_value = p.size * p.average_price
        current_value = p.size * p.current_price

        result.append(
            PositionResponse(
                market_id=p.market_id,
                market_question=market_question,
                event_title=event_title,
                slug=slug,
                outcome_side=p.outcome_side.value,
                size=p.size,
                average_price=p.average_price,
                current_price=p.current_price,
                entry_value=entry_value,
                current_value=current_value,
                unrealized_pnl=p.unrealized_pnl,
                unrealized_pnl_pct=p.unrealized_pnl_pct,
            )
        )

    return result


@app.get("/api/trades", response_model=List[TradeResponse])
async def get_trades(limit: int = 50):
    """거래 내역 조회"""
    if not trading_loop:
        raise HTTPException(status_code=503, detail="Trading loop not initialized")

    # Use async method for persistent client
    if hasattr(trading_loop.polymarket_client, 'get_trade_history_async'):
        trades = await trading_loop.polymarket_client.get_trade_history_async(limit=limit)
    else:
        trades = trading_loop.polymarket_client.get_trade_history(limit=limit)

    # 중복 제거된 market_id 목록
    unique_market_ids = list(set(t.market_id for t in trades))

    # 병렬로 모든 market 정보 가져오기
    import asyncio
    markets_data = await asyncio.gather(
        *[trading_loop.polymarket_client.get_market(mid) for mid in unique_market_ids],
        return_exceptions=True
    )

    # market_id -> market 매핑 생성
    market_cache = {}
    for mid, market in zip(unique_market_ids, markets_data):
        if market and not isinstance(market, Exception):
            market_cache[mid] = market

    result = []
    for t in trades:
        market = market_cache.get(t.market_id)
        market_question = market.question if market else None
        event_title = getattr(market, 'event_title', None) if market else None
        slug = getattr(market, 'slug', None) if market else None

        result.append(
            TradeResponse(
                trade_id=t.trade_id,
                market_id=t.market_id,
                market_question=market_question,
                event_title=event_title,
                slug=slug,
                side=t.side.value,
                outcome_side=t.outcome_side.value,
                size=t.size,
                price=t.price,
                total=t.size * t.price,
                fee=t.fee,
                timestamp=t.timestamp.isoformat(),
            )
        )

    return result


@app.get("/api/markets", response_model=List[MarketResponse])
async def get_markets(category: Optional[str] = None, limit: int = 20):
    """시장 목록 조회"""
    if not trading_loop:
        raise HTTPException(status_code=503, detail="Trading loop not initialized")

    categories = [category] if category else None
    markets = await trading_loop.polymarket_client.get_markets(
        categories=categories,
        active_only=True,
        limit=limit,
    )

    return [
        MarketResponse(
            id=m.id,
            question=m.question,
            category=m.category,
            event_id=getattr(m, 'event_id', None),
            event_title=getattr(m, 'event_title', None),
            yes_price=m.yes_price,
            no_price=m.no_price,
            volume_24h=m.volume_24h,
            liquidity=m.liquidity,
        )
        for m in markets
    ]


@app.get("/api/events", response_model=List[EventResponse])
async def get_events(category: Optional[str] = None, limit: int = 20):
    """이벤트 목록 조회 (Event/Submarket 구조)"""
    if not trading_loop:
        raise HTTPException(status_code=503, detail="Trading loop not initialized")

    # Get markets and group by event
    categories = [category] if category else None
    markets = await trading_loop.polymarket_client.get_markets(
        categories=categories,
        active_only=True,
        limit=limit * 5,  # Get more markets to group
    )

    # Group markets by event
    events_dict = {}
    for m in markets:
        event_id = getattr(m, 'event_id', None) or m.id
        event_title = getattr(m, 'event_title', None) or m.question

        if event_id not in events_dict:
            events_dict[event_id] = {
                "id": event_id,
                "title": event_title,
                "category": m.category,
                "markets": [],
                "liquidity": 0,
                "volume": 0,
            }

        events_dict[event_id]["markets"].append(
            MarketResponse(
                id=m.id,
                question=m.question,
                category=m.category,
                event_id=event_id,
                event_title=event_title,
                yes_price=m.yes_price,
                no_price=m.no_price,
                volume_24h=m.volume_24h,
                liquidity=m.liquidity,
            )
        )
        events_dict[event_id]["liquidity"] += m.liquidity
        events_dict[event_id]["volume"] += m.volume_24h

    # Convert to list and sort by volume
    events = list(events_dict.values())
    events.sort(key=lambda e: e["volume"], reverse=True)

    return [EventResponse(**e) for e in events[:limit]]


@app.get("/api/agents", response_model=List[AgentStatsResponse])
async def get_agent_stats():
    """Agent 통계 조회"""
    if not trading_loop:
        raise HTTPException(status_code=503, detail="Trading loop not initialized")

    stats = trading_loop.orchestrator.get_agent_stats()

    return [
        AgentStatsResponse(
            name=s["name"],
            type=s["type"],
            total_calls=s["total_calls"],
            total_tokens_used=s["total_tokens_used"],
            total_cost=s["total_cost"],
        )
        for s in stats.values()
    ]


@app.get("/api/equity-history", response_model=List[EquityHistoryResponse])
async def get_equity_history():
    """Equity 히스토리 조회 (차트용)"""
    if not trading_loop:
        raise HTTPException(status_code=503, detail="Trading loop not initialized")

    # Use DB-backed history if available
    if hasattr(trading_loop.polymarket_client, 'get_equity_history'):
        history = await trading_loop.polymarket_client.get_equity_history()
        return [
            EquityHistoryResponse(timestamp=h["timestamp"], equity=h["equity"])
            for h in history
        ]

    return []


@app.get("/api/decisions", response_model=List[DecisionResponse])
async def get_decisions(limit: int = Query(default=50, le=100)):
    """최근 거래 결정 조회"""
    # Return most recent decisions first
    recent = saved_decisions[-limit:][::-1]
    return [
        DecisionResponse(
            market_id=d["market_id"],
            slug=d.get("slug"),
            decision=d["decision"],
            confidence=d["confidence"],
            position_size_usd=d.get("position_size_usd", 0),
            reasoning=d.get("reasoning", ""),
            total_tokens=d.get("total_tokens", 0),
            total_cost=d.get("total_cost", 0),
            timestamp=d["timestamp"],
        )
        for d in recent
    ]


@app.post("/api/run-cycle", response_model=List[DecisionResponse])
async def run_trading_cycle():
    """수동으로 트레이딩 사이클 실행"""
    if not trading_loop:
        raise HTTPException(status_code=503, detail="Trading loop not initialized")

    # Record equity before cycle
    await trading_loop.polymarket_client.record_equity_snapshot()

    decisions = await trading_loop.run_once()

    # Record equity after cycle
    await trading_loop.polymarket_client.record_equity_snapshot()

    # Broadcast updates
    equity = await trading_loop.polymarket_client.get_equity()
    positions = await trading_loop.polymarket_client.get_positions()

    await broadcast_equity_update({
        "timestamp": datetime.utcnow().isoformat(),
        "equity": equity,
    })

    await broadcast_status_update(trading_loop.get_status())

    # Get market slugs for decisions
    market_slugs = {}
    for d in decisions:
        try:
            market = await trading_loop.polymarket_client.get_market(d.market_id)
            if market and market.slug:
                market_slugs[d.market_id] = market.slug
        except Exception:
            pass

    # Broadcast decisions and save to persistent storage
    global saved_decisions
    for d in decisions:
        decision_data = {
            "market_id": d.market_id,
            "slug": market_slugs.get(d.market_id),
            "decision": d.decision,
            "confidence": d.confidence,
            "position_size_usd": d.position_size_usd,
            "reasoning": d.reasoning[:500] if d.reasoning else "",
            "total_tokens": d.total_tokens,
            "total_cost": d.total_cost,
            "timestamp": d.timestamp.isoformat(),
        }
        saved_decisions.append(decision_data)
        await broadcast_decision(decision_data)

    # Save to file
    save_decisions(saved_decisions)

    return [
        DecisionResponse(
            market_id=d.market_id,
            slug=market_slugs.get(d.market_id),
            decision=d.decision,
            confidence=d.confidence,
            position_size_usd=d.position_size_usd,
            reasoning=d.reasoning[:500] if d.reasoning else "",
            total_tokens=d.total_tokens,
            total_cost=d.total_cost,
            timestamp=d.timestamp.isoformat(),
        )
        for d in decisions
    ]


@app.post("/api/start")
async def start_trading(background_tasks: BackgroundTasks):
    """자동 트레이딩 시작"""
    global background_task

    if not trading_loop:
        raise HTTPException(status_code=503, detail="Trading loop not initialized")

    if trading_loop._running:
        return {"message": "Already running"}

    trading_loop._last_run = datetime.utcnow()

    async def run_loop():
        await trading_loop.run()

    background_task = asyncio.create_task(run_loop())

    # Broadcast status update
    await broadcast_status_update(trading_loop.get_status())

    return {"message": "Trading started"}


@app.post("/api/stop")
async def stop_trading():
    """자동 트레이딩 중지"""
    global background_task

    if not trading_loop:
        raise HTTPException(status_code=503, detail="Trading loop not initialized")

    trading_loop.stop()

    if background_task:
        background_task.cancel()
        try:
            await background_task
        except asyncio.CancelledError:
            pass

    # Broadcast status update
    await broadcast_status_update(trading_loop.get_status())

    return {"message": "Trading stopped"}


@app.post("/api/trade")
async def manual_trade(request: ManualTradeRequest):
    """수동 거래 실행"""
    if not trading_loop:
        raise HTTPException(status_code=503, detail="Trading loop not initialized")

    market = await trading_loop.polymarket_client.get_market(request.market_id)
    if not market:
        raise HTTPException(status_code=404, detail="Market not found")

    outcome_side = OutcomeSide.YES if request.side == "YES" else OutcomeSide.NO
    token_id = (
        market.yes_token_id if outcome_side == OutcomeSide.YES else market.no_token_id
    )

    if not token_id:
        raise HTTPException(status_code=400, detail="Token ID not found")

    from src.core.polymarket.models import Order, Side

    price = market.yes_price if outcome_side == OutcomeSide.YES else market.no_price
    size = request.size_usd / price

    order = Order(
        market_id=market.id,
        token_id=token_id,
        side=Side.BUY if request.action == "BUY" else Side.SELL,
        outcome_side=outcome_side,
        price=price,
        size=size,
    )

    result = await trading_loop.polymarket_client.place_order(order)

    if result.success:
        # Broadcast trade
        await broadcast_trade({
            "market_id": market.id,
            "side": request.action,
            "outcome_side": request.side,
            "size": size,
            "price": price,
            "timestamp": datetime.utcnow().isoformat(),
        })

        # Broadcast portfolio update
        equity = await trading_loop.polymarket_client.get_equity()
        balance = await trading_loop.polymarket_client.get_balance()
        positions = await trading_loop.polymarket_client.get_positions()

        await broadcast_portfolio_update({
            "total_equity": equity,
            "available_balance": balance,
            "position_count": len(positions),
        })

        return {
            "success": True,
            "order_id": result.order_id,
            "filled_size": result.filled_size,
            "price": result.average_price,
        }
    else:
        raise HTTPException(status_code=400, detail=result.error_message)


@app.post("/api/reset")
async def reset_demo():
    """데모 계정 리셋"""
    if not trading_loop:
        raise HTTPException(status_code=503, detail="Trading loop not initialized")

    if not trading_loop.demo_mode:
        raise HTTPException(status_code=400, detail="Cannot reset in live mode")

    await trading_loop.polymarket_client.reset()
    trading_loop.risk_manager.reset_daily_pnl()
    trading_loop.risk_manager.reset_weekly_pnl()

    # Broadcast updates
    await broadcast_portfolio_update({
        "total_equity": trading_loop.polymarket_client.initial_balance,
        "available_balance": trading_loop.polymarket_client.initial_balance,
        "position_count": 0,
    })

    await broadcast_positions_update([])

    return {"message": "Demo account reset", "balance": trading_loop.polymarket_client.initial_balance}


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
    )
