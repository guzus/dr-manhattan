"""
WebSocket Manager

실시간 업데이트를 위한 WebSocket 연결 관리자
"""

import asyncio
import json
from datetime import datetime
from typing import Dict, List, Set, Any, Optional
from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel
import structlog

logger = structlog.get_logger()


class WebSocketMessage(BaseModel):
    """WebSocket 메시지 형식"""
    type: str  # portfolio, positions, trades, decisions, status, equity
    data: Any
    timestamp: str


class ConnectionManager:
    """WebSocket 연결 관리자"""

    def __init__(self):
        # 모든 활성 연결
        self.active_connections: Set[WebSocket] = set()
        # 토픽별 구독자
        self.subscriptions: Dict[str, Set[WebSocket]] = {
            "portfolio": set(),
            "positions": set(),
            "trades": set(),
            "decisions": set(),
            "status": set(),
            "equity": set(),
            "all": set(),  # 모든 업데이트 수신
        }
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, topics: Optional[List[str]] = None):
        """클라이언트 연결"""
        await websocket.accept()

        async with self._lock:
            self.active_connections.add(websocket)

            # 토픽 구독 (기본값: all)
            if topics is None:
                topics = ["all"]

            for topic in topics:
                if topic in self.subscriptions:
                    self.subscriptions[topic].add(websocket)

        logger.info(
            "WebSocket client connected",
            topics=topics,
            total_connections=len(self.active_connections),
        )

    async def disconnect(self, websocket: WebSocket):
        """클라이언트 연결 해제"""
        async with self._lock:
            self.active_connections.discard(websocket)

            # 모든 구독에서 제거
            for topic_subscribers in self.subscriptions.values():
                topic_subscribers.discard(websocket)

        logger.info(
            "WebSocket client disconnected",
            total_connections=len(self.active_connections),
        )

    async def subscribe(self, websocket: WebSocket, topics: List[str]):
        """토픽 구독"""
        async with self._lock:
            for topic in topics:
                if topic in self.subscriptions:
                    self.subscriptions[topic].add(websocket)

    async def unsubscribe(self, websocket: WebSocket, topics: List[str]):
        """토픽 구독 해제"""
        async with self._lock:
            for topic in topics:
                if topic in self.subscriptions:
                    self.subscriptions[topic].discard(websocket)

    async def send_personal_message(self, websocket: WebSocket, message: dict):
        """특정 클라이언트에게 메시지 전송"""
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error(f"Failed to send personal message: {e}")
            await self.disconnect(websocket)

    async def broadcast(self, topic: str, data: Any):
        """토픽 구독자들에게 브로드캐스트"""
        message = WebSocketMessage(
            type=topic,
            data=data,
            timestamp=datetime.utcnow().isoformat(),
        )

        # 해당 토픽 구독자 + all 구독자
        recipients = self.subscriptions.get(topic, set()) | self.subscriptions.get("all", set())

        disconnected = []
        for websocket in recipients:
            try:
                await websocket.send_json(message.model_dump())
            except Exception as e:
                logger.error(f"Failed to broadcast to client: {e}")
                disconnected.append(websocket)

        # 연결 실패한 클라이언트 정리
        for ws in disconnected:
            await self.disconnect(ws)

    async def broadcast_all(self, message: dict):
        """모든 클라이언트에게 브로드캐스트"""
        disconnected = []
        for websocket in self.active_connections.copy():
            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.error(f"Failed to broadcast: {e}")
                disconnected.append(websocket)

        for ws in disconnected:
            await self.disconnect(ws)

    @property
    def connection_count(self) -> int:
        """현재 연결 수"""
        return len(self.active_connections)


# Global instance
manager = ConnectionManager()


async def broadcast_portfolio_update(portfolio_data: dict):
    """포트폴리오 업데이트 브로드캐스트"""
    await manager.broadcast("portfolio", portfolio_data)


async def broadcast_positions_update(positions_data: list):
    """포지션 업데이트 브로드캐스트"""
    await manager.broadcast("positions", positions_data)


async def broadcast_trade(trade_data: dict):
    """새 거래 브로드캐스트"""
    await manager.broadcast("trades", trade_data)


async def broadcast_decision(decision_data: dict):
    """AI 결정 브로드캐스트"""
    await manager.broadcast("decisions", decision_data)


async def broadcast_status_update(status_data: dict):
    """상태 업데이트 브로드캐스트"""
    await manager.broadcast("status", status_data)


async def broadcast_equity_update(equity_data: dict):
    """Equity 업데이트 브로드캐스트"""
    await manager.broadcast("equity", equity_data)
