"""
Polymarket CLOB API Client

실제 거래를 위한 클라이언트 (추후 실거래 연동 시 사용)
"""

import asyncio
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from datetime import datetime
import httpx
import structlog

from .models import (
    MarketData,
    OrderBook,
    OrderBookEntry,
    Order,
    OrderResult,
    TradeResult,
    PositionData,
    Side,
    OutcomeSide,
    OrderStatus,
)

logger = structlog.get_logger()

# 카테고리 매핑 (Polymarket 카테고리 -> 우리 카테고리)
CATEGORY_MAPPING = {
    "sports": ["Sports", "NBA Playoffs", "Olympics", "Chess", "Poker"],
    "politics": ["US-current-affairs", "Global Politics", "Ukraine & Russia"],
    "crypto": ["Crypto", "NFTs"],
    "entertainment": ["Pop-Culture", "Art"],
    "science": ["Science", "Coronavirus"],
    "business": ["Business"],
}


def normalize_category(raw_category: Optional[str]) -> Optional[str]:
    """Polymarket 카테고리를 정규화된 카테고리로 변환"""
    if not raw_category:
        return None

    for normalized, raw_list in CATEGORY_MAPPING.items():
        if raw_category in raw_list:
            return normalized

    return raw_category.lower()


class BasePolymarketClient(ABC):
    """Polymarket 클라이언트 기본 인터페이스"""

    @abstractmethod
    async def get_markets(
        self,
        categories: Optional[List[str]] = None,
        active_only: bool = True,
        limit: int = 100,
    ) -> List[MarketData]:
        """시장 목록 조회"""
        pass

    @abstractmethod
    async def get_market(self, market_id: str) -> Optional[MarketData]:
        """특정 시장 조회"""
        pass

    @abstractmethod
    async def get_order_book(
        self, token_id: str
    ) -> Optional[OrderBook]:
        """오더북 조회"""
        pass

    @abstractmethod
    async def get_price(self, token_id: str) -> Optional[float]:
        """현재 가격 조회"""
        pass

    @abstractmethod
    async def place_order(self, order: Order) -> OrderResult:
        """주문 실행"""
        pass

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """주문 취소"""
        pass

    @abstractmethod
    async def get_positions(self) -> List[PositionData]:
        """포지션 조회"""
        pass

    @abstractmethod
    async def get_balance(self) -> float:
        """잔고 조회"""
        pass


class PolymarketClient(BasePolymarketClient):
    """
    실제 Polymarket CLOB API 클라이언트

    py-clob-client 라이브러리를 래핑하여 사용
    """

    # Polymarket API endpoints
    GAMMA_API = "https://gamma-api.polymarket.com"
    CLOB_API = "https://clob.polymarket.com"

    def __init__(
        self,
        host: str = "https://clob.polymarket.com",
        private_key: Optional[str] = None,
        chain_id: int = 137,
    ):
        self.host = host
        self.private_key = private_key
        self.chain_id = chain_id
        self._client: Optional[httpx.AsyncClient] = None
        self._clob_client = None  # py-clob-client instance

    async def _ensure_client(self):
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)

    async def _init_clob_client(self):
        """Initialize py-clob-client for trading operations"""
        if self._clob_client is None and self.private_key:
            try:
                from py_clob_client.client import ClobClient

                self._clob_client = ClobClient(
                    self.host,
                    key=self.private_key,
                    chain_id=self.chain_id,
                )
                # Set API credentials
                creds = self._clob_client.create_or_derive_api_creds()
                self._clob_client.set_api_creds(creds)
                logger.info("CLOB client initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize CLOB client: {e}")

    async def get_markets(
        self,
        categories: Optional[List[str]] = None,
        active_only: bool = True,
        limit: int = 100,
    ) -> List[MarketData]:
        """
        시장 목록 조회 (Events API 사용)

        /events 엔드포인트를 사용하여 카테고리 정보를 포함한 시장 데이터 조회
        """
        await self._ensure_client()

        try:
            # Events API 사용 (카테고리 정보 포함)
            # closed=false를 추가해야 열린 이벤트만 가져옴 (정상적인 가격 데이터)
            params = {
                "limit": limit * 3,  # 필터링 후 충분한 수 확보
                "closed": "false",  # 종료되지 않은 이벤트만
            }
            if active_only:
                params["active"] = "true"

            response = await self._client.get(
                f"{self.GAMMA_API}/events",
                params=params,
            )
            response.raise_for_status()
            events = response.json()

            markets = []
            for event in events:
                raw_category = event.get("category")
                normalized_cat = normalize_category(raw_category)

                # Filter by category if specified
                if categories:
                    if not normalized_cat:
                        continue
                    if normalized_cat not in [c.lower() for c in categories]:
                        continue

                # 이벤트 내의 마켓들 처리
                event_markets = event.get("markets", [])
                if not event_markets:
                    # markets 필드가 없으면 이벤트 자체를 마켓으로 처리
                    market = self._parse_event_to_market(event)
                    if market:
                        markets.append(market)
                else:
                    for market_data in event_markets:
                        # 이벤트의 카테고리 정보와 이벤트 관계를 마켓에 추가
                        market_data["category"] = normalized_cat
                        market_data["event_id"] = str(event.get("id", ""))
                        market_data["event_title"] = event.get("title")
                        market = self._parse_market_data(market_data)
                        if market:
                            markets.append(market)

            # Sort by volume
            markets.sort(key=lambda m: m.volume_24h, reverse=True)
            return markets[:limit]

        except Exception as e:
            logger.error(f"Failed to get markets: {e}")
            return []

    async def get_all_categories(self) -> Dict[str, int]:
        """사용 가능한 모든 카테고리 조회"""
        await self._ensure_client()

        try:
            response = await self._client.get(
                f"{self.GAMMA_API}/events",
                params={"limit": 500, "active": "true"},
            )
            response.raise_for_status()
            events = response.json()

            category_counts: Dict[str, int] = {}
            for event in events:
                raw_cat = event.get("category")
                normalized = normalize_category(raw_cat)
                if normalized:
                    category_counts[normalized] = category_counts.get(normalized, 0) + 1

            return category_counts
        except Exception as e:
            logger.error(f"Failed to get categories: {e}")
            return {}

    async def get_market(self, market_id: str) -> Optional[MarketData]:
        """특정 시장 조회"""
        await self._ensure_client()

        try:
            response = await self._client.get(
                f"{self.GAMMA_API}/markets/{market_id}"
            )
            response.raise_for_status()
            data = response.json()
            return self._parse_market_data(data)
        except Exception as e:
            logger.error(f"Failed to get market {market_id}: {e}")
            return None

    async def get_order_book(self, token_id: str) -> Optional[OrderBook]:
        """오더북 조회"""
        await self._ensure_client()

        try:
            response = await self._client.get(
                f"{self.CLOB_API}/book",
                params={"token_id": token_id},
            )
            response.raise_for_status()
            data = response.json()

            bids = [
                OrderBookEntry(price=float(b["price"]), size=float(b["size"]))
                for b in data.get("bids", [])
            ]
            asks = [
                OrderBookEntry(price=float(a["price"]), size=float(a["size"]))
                for a in data.get("asks", [])
            ]

            return OrderBook(bids=bids, asks=asks)
        except Exception as e:
            logger.error(f"Failed to get order book for {token_id}: {e}")
            return None

    async def get_price(self, token_id: str) -> Optional[float]:
        """현재 가격 조회 (중간값)"""
        await self._ensure_client()

        try:
            response = await self._client.get(
                f"{self.CLOB_API}/midpoint",
                params={"token_id": token_id},
            )
            response.raise_for_status()
            data = response.json()
            return float(data.get("mid", 0.5))
        except Exception as e:
            logger.error(f"Failed to get price for {token_id}: {e}")
            return None

    async def get_prices(self, token_ids: List[str]) -> Dict[str, float]:
        """여러 토큰 가격 일괄 조회"""
        await self._ensure_client()

        try:
            response = await self._client.post(
                f"{self.CLOB_API}/prices",
                json={"token_ids": token_ids},
            )
            response.raise_for_status()
            data = response.json()
            return {k: float(v) for k, v in data.items()}
        except Exception as e:
            logger.error(f"Failed to get prices: {e}")
            return {}

    async def place_order(self, order: Order) -> OrderResult:
        """
        주문 실행

        실제 거래 시 py-clob-client 사용
        """
        await self._init_clob_client()

        if not self._clob_client:
            return OrderResult(
                success=False,
                error_message="Trading client not initialized. Set private key for live trading.",
            )

        try:
            from py_clob_client.order_builder.constants import BUY, SELL
            from py_clob_client.clob_types import OrderArgs, OrderType as ClobOrderType

            side = BUY if order.side == Side.BUY else SELL

            order_args = OrderArgs(
                price=order.price,
                size=order.size,
                side=side,
                token_id=order.token_id,
            )

            signed_order = self._clob_client.create_order(order_args)
            response = self._clob_client.post_order(
                signed_order, ClobOrderType.GTC
            )

            return OrderResult(
                success=True,
                order_id=response.get("orderID"),
                status=OrderStatus.OPEN,
                filled_size=0.0,
                average_price=order.price,
            )

        except Exception as e:
            logger.error(f"Failed to place order: {e}")
            return OrderResult(
                success=False,
                error_message=str(e),
            )

    async def cancel_order(self, order_id: str) -> bool:
        """주문 취소"""
        await self._init_clob_client()

        if not self._clob_client:
            return False

        try:
            self._clob_client.cancel(order_id)
            return True
        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            return False

    async def get_positions(self) -> List[PositionData]:
        """포지션 조회 (실거래용)"""
        # 실제 구현은 py-clob-client 또는 지갑 조회 필요
        logger.warning("Live positions not implemented yet")
        return []

    async def get_balance(self) -> float:
        """잔고 조회 (실거래용)"""
        # 실제 구현은 Polygon USDC 잔고 조회 필요
        logger.warning("Live balance not implemented yet")
        return 0.0

    def _parse_event_to_market(self, event: Dict[str, Any]) -> Optional[MarketData]:
        """Event를 MarketData로 변환"""
        try:
            # Parse end date
            end_date = None
            if event.get("endDate"):
                try:
                    end_date = datetime.fromisoformat(
                        event["endDate"].replace("Z", "+00:00")
                    )
                except:
                    pass

            # 가격 정보 추출
            yes_price = 0.5
            no_price = 0.5

            # outcomePrices가 있으면 사용
            outcome_prices = event.get("outcomePrices")
            if outcome_prices and isinstance(outcome_prices, str):
                try:
                    import json
                    prices = json.loads(outcome_prices)
                    if len(prices) >= 2:
                        yes_price = float(prices[0]) if prices[0] else 0.5
                        no_price = float(prices[1]) if prices[1] else 0.5
                except:
                    pass

            # clobTokenIds 파싱
            yes_token_id = None
            no_token_id = None
            clob_token_ids = event.get("clobTokenIds")
            if clob_token_ids and isinstance(clob_token_ids, str):
                try:
                    import json
                    token_ids = json.loads(clob_token_ids)
                    if len(token_ids) >= 2:
                        yes_token_id = token_ids[0]
                        no_token_id = token_ids[1]
                except:
                    pass

            return MarketData(
                id=str(event.get("id", "")),
                condition_id=event.get("conditionId", ""),
                question=event.get("title") or event.get("question", ""),
                description=event.get("description"),
                category=normalize_category(event.get("category")),
                yes_token_id=yes_token_id,
                no_token_id=no_token_id,
                yes_price=yes_price,
                no_price=no_price,
                liquidity=float(event.get("liquidity", 0) or 0),
                volume_24h=float(event.get("volume24hr", 0) or 0),
                volume_total=float(event.get("volume", 0) or 0),
                end_date=end_date,
                is_active=event.get("active", True),
                is_resolved=event.get("closed", False),
                resolution=event.get("resolution"),
                tags=[],
            )
        except Exception as e:
            logger.error(f"Failed to parse event: {e}")
            return None

    def _parse_market_data(self, data: Dict[str, Any]) -> MarketData:
        """API 응답을 MarketData로 변환"""
        import json as json_module

        # Parse tokens
        tokens = data.get("tokens", [])
        yes_token = next((t for t in tokens if t.get("outcome") == "Yes"), None)
        no_token = next((t for t in tokens if t.get("outcome") == "No"), None)

        # Parse end date
        end_date = None
        if data.get("endDate"):
            try:
                end_date = datetime.fromisoformat(
                    data["endDate"].replace("Z", "+00:00")
                )
            except:
                pass

        # 카테고리 - 이미 정규화된 값이면 그대로 사용, 아니면 정규화
        category = data.get("category")
        if category:
            # 이미 정규화된 값인지 확인 (소문자이고 CATEGORY_MAPPING의 key에 있으면 정규화됨)
            if category.lower() not in CATEGORY_MAPPING:
                category = normalize_category(category)
            # 소문자로 통일
            category = category.lower() if category else None

        # 가격 파싱 - outcomePrices 우선 사용
        yes_price = 0.5
        no_price = 0.5

        # 1. outcomePrices 문자열에서 파싱 시도
        outcome_prices = data.get("outcomePrices")
        if outcome_prices:
            try:
                if isinstance(outcome_prices, str):
                    prices = json_module.loads(outcome_prices)
                else:
                    prices = outcome_prices
                if isinstance(prices, list) and len(prices) >= 2:
                    yes_price = float(prices[0]) if prices[0] else 0.5
                    no_price = float(prices[1]) if prices[1] else 0.5
            except:
                pass

        # 2. tokens 배열에서 파싱 시도 (fallback)
        if yes_price == 0.5 and no_price == 0.5:
            if yes_token:
                yes_price = float(yes_token.get("price", 0.5))
            if no_token:
                no_price = float(no_token.get("price", 0.5))

        # 3. clobTokenIds 파싱
        yes_token_id = yes_token.get("token_id") if yes_token else None
        no_token_id = no_token.get("token_id") if no_token else None

        clob_token_ids = data.get("clobTokenIds")
        if clob_token_ids and not yes_token_id:
            try:
                if isinstance(clob_token_ids, str):
                    token_ids = json_module.loads(clob_token_ids)
                else:
                    token_ids = clob_token_ids
                if isinstance(token_ids, list) and len(token_ids) >= 2:
                    yes_token_id = token_ids[0]
                    no_token_id = token_ids[1]
            except:
                pass

        # Event relationship - extract event_id and event_title if available
        event_id = data.get("event_id") or data.get("eventId")
        event_title = data.get("event_title") or data.get("eventTitle")

        return MarketData(
            id=data.get("id", ""),
            condition_id=data.get("conditionId", ""),
            question=data.get("question", ""),
            description=data.get("description"),
            category=category,
            event_id=event_id,
            event_title=event_title,
            yes_token_id=yes_token_id,
            no_token_id=no_token_id,
            yes_price=yes_price,
            no_price=no_price,
            liquidity=float(data.get("liquidity", 0) or 0),
            volume_24h=float(data.get("volume24hr", 0) or 0),
            volume_total=float(data.get("volume", 0) or 0),
            end_date=end_date,
            is_active=data.get("active", True),
            is_resolved=data.get("closed", False),
            resolution=data.get("resolution"),
            tags=data.get("tags", []),
        )

    async def close(self):
        """클라이언트 종료"""
        if self._client:
            await self._client.aclose()
