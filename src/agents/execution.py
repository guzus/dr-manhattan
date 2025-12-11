"""
Execution Agent

거래 실행 최적화 담당
"""

from typing import Any, Dict, Optional
from .base import BaseAgent
from src.core.polymarket.models import MarketData, OrderBook
from src.core.llm.prompts import EXECUTION_AGENT_PROMPT


class ExecutionAgent(BaseAgent):
    """실행 Agent - 주문 실행 최적화"""

    @property
    def agent_type(self) -> str:
        return "execution"

    @property
    def system_prompt(self) -> str:
        return """You are an expert trade execution specialist.
Your job is to determine optimal execution parameters to minimize slippage and market impact.
Consider order book depth, spread, and urgency when making recommendations.
Always respond with valid JSON matching the required schema."""

    def format_prompt(
        self,
        market: MarketData,
        side: str = "BUY",
        outcome: str = "YES",
        target_size: float = 100.0,
        max_price: float = 1.0,
        order_book: Optional[OrderBook] = None,
        **kwargs,
    ) -> str:
        # Default order book values
        best_bid = 0.45
        best_ask = 0.55
        bid_size = 1000.0
        ask_size = 1000.0

        if order_book:
            best_bid = order_book.best_bid or 0.45
            best_ask = order_book.best_ask or 0.55
            bid_size = order_book.bids[0].size if order_book.bids else 1000.0
            ask_size = order_book.asks[0].size if order_book.asks else 1000.0

        spread = best_ask - best_bid
        spread_pct = spread / ((best_bid + best_ask) / 2) if (best_bid + best_ask) > 0 else 0

        return EXECUTION_AGENT_PROMPT.format(
            market_data=self._format_market_data(market),
            best_bid=best_bid,
            bid_size=bid_size,
            best_ask=best_ask,
            ask_size=ask_size,
            spread=spread,
            spread_pct=spread_pct,
            side=side,
            outcome=outcome,
            target_size=target_size,
            max_price=max_price,
        )

    def _format_market_data(self, market: MarketData) -> str:
        return f"""
Market ID: {market.id}
Question: {market.question}
Liquidity: ${market.liquidity:,.2f}
24h Volume: ${market.volume_24h:,.2f}
YES Price: ${market.yes_price:.4f}
NO Price: ${market.no_price:.4f}
"""

    def parse_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """응답 파싱 및 검증"""
        # Normalize execution strategy
        execution_strategy = response.get("execution_strategy", "market")
        if execution_strategy not in ["market", "limit", "split"]:
            execution_strategy = "market"

        # Clamp price
        recommended_price = response.get("recommended_price", 0.5)
        recommended_price = max(0.01, min(0.99, float(recommended_price)))

        # Clamp slippage
        max_slippage = response.get("max_slippage", 0.02)
        max_slippage = max(0.0, min(0.1, float(max_slippage)))

        # Normalize urgency
        urgency = response.get("urgency", "medium")
        if urgency not in ["high", "medium", "low"]:
            urgency = "medium"

        # Clamp splits
        num_splits = response.get("num_splits", 1)
        num_splits = max(1, min(5, int(num_splits)))

        return {
            "market_id": response.get("market_id"),
            "execution_strategy": execution_strategy,
            "recommended_price": recommended_price,
            "size": float(response.get("size", 0)),
            "max_slippage": max_slippage,
            "urgency": urgency,
            "split_orders": response.get("split_orders", False),
            "num_splits": num_splits,
            "execution_notes": response.get("execution_notes", ""),
        }
