"""
Exit Manager

퀀트 현업 방식의 포지션 Exit 관리
- Take Profit (익절)
- Stop Loss (손절)
- Trailing Stop (트레일링 스탑)
- Time-based Exit (시간 기반)
- Rebalancing (리밸런싱)
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import List, Optional, Dict, Any
import structlog

from src.core.polymarket.models import PositionData, OutcomeSide

logger = structlog.get_logger()


class ExitReason(str, Enum):
    """Exit 사유"""
    TAKE_PROFIT = "take_profit"           # 목표 수익 달성
    STOP_LOSS = "stop_loss"               # 손절선 도달
    TRAILING_STOP = "trailing_stop"       # 트레일링 스탑 발동
    TIME_EXIT = "time_exit"               # 보유 기간 초과
    REBALANCE = "rebalance"               # 리밸런싱
    SIGNAL_REVERSAL = "signal_reversal"   # 시그널 반전
    MANUAL = "manual"                     # 수동 청산


@dataclass
class ExitSignal:
    """Exit 시그널"""
    position_id: str
    market_id: str
    token_id: str
    reason: ExitReason
    urgency: str  # "immediate", "next_cycle", "low"
    exit_size_pct: float  # 0.0 ~ 1.0 (전량이면 1.0)
    recommended_price: Optional[float] = None
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class PositionMetrics:
    """포지션 분석 메트릭"""
    position: PositionData
    entry_price: float
    current_price: float
    pnl_pct: float           # 손익률 (%)
    pnl_usd: float           # 손익 (USD)
    highest_price: float     # 최고가 (트레일링용)
    lowest_price: float      # 최저가
    holding_hours: float     # 보유 시간
    price_change_1h: float   # 1시간 가격 변동률
    volatility: float        # 변동성


class ExitManager:
    """
    포지션 Exit 관리자

    퀀트 현업에서 사용하는 방식:
    1. 고정 익절/손절 (Fixed TP/SL)
    2. 트레일링 스탑 (Trailing Stop)
    3. 시간 기반 Exit (Time-based)
    4. 동적 조정 (Dynamic Adjustment)
    """

    def __init__(
        self,
        # Take Profit 설정
        take_profit_pct: float = 20.0,          # 기본 익절선 (+20%)
        partial_take_profit_pct: float = 10.0,  # 부분 익절선 (+10%)
        partial_take_profit_size: float = 0.5,  # 부분 익절 비율 (50%)

        # Stop Loss 설정
        stop_loss_pct: float = -15.0,           # 기본 손절선 (-15%)
        hard_stop_loss_pct: float = -25.0,      # 강제 손절선 (-25%)

        # Trailing Stop 설정
        trailing_stop_activation_pct: float = 8.0,  # 트레일링 활성화 (+8%)
        trailing_stop_distance_pct: float = 5.0,    # 트레일링 거리 (5%)

        # Time-based 설정
        max_holding_hours: float = 72.0,        # 최대 보유 시간 (3일)
        warning_holding_hours: float = 48.0,    # 경고 보유 시간 (2일)

        # Rebalancing 설정
        max_position_weight_pct: float = 15.0,  # 최대 포지션 비중
        rebalance_threshold_pct: float = 5.0,   # 리밸런싱 임계값
    ):
        self.take_profit_pct = take_profit_pct
        self.partial_take_profit_pct = partial_take_profit_pct
        self.partial_take_profit_size = partial_take_profit_size

        self.stop_loss_pct = stop_loss_pct
        self.hard_stop_loss_pct = hard_stop_loss_pct

        self.trailing_stop_activation_pct = trailing_stop_activation_pct
        self.trailing_stop_distance_pct = trailing_stop_distance_pct

        self.max_holding_hours = max_holding_hours
        self.warning_holding_hours = warning_holding_hours

        self.max_position_weight_pct = max_position_weight_pct
        self.rebalance_threshold_pct = rebalance_threshold_pct

        # 포지션별 최고가 추적 (트레일링 스탑용)
        self._highest_prices: Dict[str, float] = {}
        # 부분 익절 기록
        self._partial_exits: Dict[str, bool] = {}

        logger.info(
            "Exit manager initialized",
            take_profit=take_profit_pct,
            stop_loss=stop_loss_pct,
            trailing_activation=trailing_stop_activation_pct,
        )

    def analyze_position(
        self,
        position: PositionData,
        entry_time: datetime,
        price_history: Optional[List[float]] = None,
    ) -> PositionMetrics:
        """
        포지션 분석
        """
        entry_price = position.average_price
        current_price = position.current_price

        # P&L 계산
        pnl_pct = ((current_price - entry_price) / entry_price) * 100
        pnl_usd = position.unrealized_pnl

        # 최고가 업데이트 (트레일링용)
        position_key = position.token_id
        highest = self._highest_prices.get(position_key, current_price)
        if current_price > highest:
            highest = current_price
            self._highest_prices[position_key] = highest

        # 최저가
        lowest = min(entry_price, current_price)

        # 보유 시간
        holding_hours = (datetime.utcnow() - entry_time).total_seconds() / 3600

        # 1시간 가격 변동률 (price_history가 있으면)
        price_change_1h = 0.0
        volatility = 0.0
        if price_history and len(price_history) >= 2:
            if len(price_history) >= 4:  # 최소 4개 데이터
                price_change_1h = ((price_history[-1] - price_history[-4]) / price_history[-4]) * 100
            # 변동성 계산
            returns = [(price_history[i] - price_history[i-1]) / price_history[i-1]
                      for i in range(1, len(price_history))]
            if returns:
                volatility = (sum(r**2 for r in returns) / len(returns)) ** 0.5 * 100

        return PositionMetrics(
            position=position,
            entry_price=entry_price,
            current_price=current_price,
            pnl_pct=pnl_pct,
            pnl_usd=pnl_usd,
            highest_price=highest,
            lowest_price=lowest,
            holding_hours=holding_hours,
            price_change_1h=price_change_1h,
            volatility=volatility,
        )

    def check_exit_signals(
        self,
        metrics: PositionMetrics,
        total_equity: float,
    ) -> List[ExitSignal]:
        """
        Exit 시그널 체크

        우선순위:
        1. Hard Stop Loss (즉시)
        2. Stop Loss (즉시)
        3. Take Profit (즉시)
        4. Trailing Stop (즉시)
        5. Partial Take Profit (다음 사이클)
        6. Time Exit (다음 사이클)
        7. Rebalancing (낮은 우선순위)
        """
        signals: List[ExitSignal] = []
        position = metrics.position
        position_key = position.token_id

        # 1. Hard Stop Loss Check (-25% 이하면 즉시 전량 청산)
        if metrics.pnl_pct <= self.hard_stop_loss_pct:
            signals.append(ExitSignal(
                position_id=position_key,
                market_id=position.market_id,
                token_id=position.token_id,
                reason=ExitReason.STOP_LOSS,
                urgency="immediate",
                exit_size_pct=1.0,
                details={
                    "type": "hard_stop",
                    "pnl_pct": metrics.pnl_pct,
                    "threshold": self.hard_stop_loss_pct,
                },
            ))
            logger.warning(
                "Hard stop loss triggered",
                market_id=position.market_id,
                pnl_pct=f"{metrics.pnl_pct:.1f}%",
            )
            return signals  # 즉시 리턴

        # 2. Regular Stop Loss Check (-15% 이하면 전량 청산)
        if metrics.pnl_pct <= self.stop_loss_pct:
            signals.append(ExitSignal(
                position_id=position_key,
                market_id=position.market_id,
                token_id=position.token_id,
                reason=ExitReason.STOP_LOSS,
                urgency="immediate",
                exit_size_pct=1.0,
                details={
                    "type": "regular_stop",
                    "pnl_pct": metrics.pnl_pct,
                    "threshold": self.stop_loss_pct,
                },
            ))
            logger.info(
                "Stop loss triggered",
                market_id=position.market_id,
                pnl_pct=f"{metrics.pnl_pct:.1f}%",
            )
            return signals

        # 3. Take Profit Check (+20% 이상이면 전량 익절)
        if metrics.pnl_pct >= self.take_profit_pct:
            signals.append(ExitSignal(
                position_id=position_key,
                market_id=position.market_id,
                token_id=position.token_id,
                reason=ExitReason.TAKE_PROFIT,
                urgency="immediate",
                exit_size_pct=1.0,
                details={
                    "pnl_pct": metrics.pnl_pct,
                    "threshold": self.take_profit_pct,
                },
            ))
            logger.info(
                "Take profit triggered",
                market_id=position.market_id,
                pnl_pct=f"{metrics.pnl_pct:.1f}%",
            )
            return signals

        # 4. Trailing Stop Check
        if metrics.pnl_pct >= self.trailing_stop_activation_pct:
            # 트레일링 스탑 활성화됨
            highest_pnl_pct = ((metrics.highest_price - metrics.entry_price) / metrics.entry_price) * 100
            drawdown_from_high = highest_pnl_pct - metrics.pnl_pct

            if drawdown_from_high >= self.trailing_stop_distance_pct:
                signals.append(ExitSignal(
                    position_id=position_key,
                    market_id=position.market_id,
                    token_id=position.token_id,
                    reason=ExitReason.TRAILING_STOP,
                    urgency="immediate",
                    exit_size_pct=1.0,
                    details={
                        "current_pnl_pct": metrics.pnl_pct,
                        "highest_pnl_pct": highest_pnl_pct,
                        "drawdown_from_high": drawdown_from_high,
                        "trailing_distance": self.trailing_stop_distance_pct,
                    },
                ))
                logger.info(
                    "Trailing stop triggered",
                    market_id=position.market_id,
                    pnl_pct=f"{metrics.pnl_pct:.1f}%",
                    highest_pnl=f"{highest_pnl_pct:.1f}%",
                )
                return signals

        # 5. Partial Take Profit (+10% 이상, 아직 부분 익절 안 했으면)
        if (metrics.pnl_pct >= self.partial_take_profit_pct and
            not self._partial_exits.get(position_key, False)):
            signals.append(ExitSignal(
                position_id=position_key,
                market_id=position.market_id,
                token_id=position.token_id,
                reason=ExitReason.TAKE_PROFIT,
                urgency="next_cycle",
                exit_size_pct=self.partial_take_profit_size,
                details={
                    "type": "partial_take_profit",
                    "pnl_pct": metrics.pnl_pct,
                    "exit_ratio": self.partial_take_profit_size,
                },
            ))
            logger.info(
                "Partial take profit signal",
                market_id=position.market_id,
                pnl_pct=f"{metrics.pnl_pct:.1f}%",
                exit_ratio=self.partial_take_profit_size,
            )

        # 6. Time-based Exit (최대 보유 시간 초과)
        if metrics.holding_hours >= self.max_holding_hours:
            signals.append(ExitSignal(
                position_id=position_key,
                market_id=position.market_id,
                token_id=position.token_id,
                reason=ExitReason.TIME_EXIT,
                urgency="next_cycle",
                exit_size_pct=1.0,
                details={
                    "holding_hours": metrics.holding_hours,
                    "max_hours": self.max_holding_hours,
                },
            ))
            logger.info(
                "Time exit signal",
                market_id=position.market_id,
                holding_hours=f"{metrics.holding_hours:.1f}h",
            )

        # 7. Rebalancing Check (포지션 비중이 너무 커졌을 때)
        position_value = metrics.position.value
        position_weight = (position_value / total_equity) * 100 if total_equity > 0 else 0

        if position_weight > self.max_position_weight_pct:
            excess_weight = position_weight - self.max_position_weight_pct
            exit_ratio = excess_weight / position_weight

            signals.append(ExitSignal(
                position_id=position_key,
                market_id=position.market_id,
                token_id=position.token_id,
                reason=ExitReason.REBALANCE,
                urgency="low",
                exit_size_pct=min(exit_ratio, 0.5),  # 최대 50%만
                details={
                    "current_weight": position_weight,
                    "max_weight": self.max_position_weight_pct,
                    "excess_weight": excess_weight,
                },
            ))
            logger.info(
                "Rebalance signal",
                market_id=position.market_id,
                weight=f"{position_weight:.1f}%",
            )

        return signals

    def record_partial_exit(self, position_key: str):
        """부분 익절 기록"""
        self._partial_exits[position_key] = True

    def reset_position_tracking(self, position_key: str):
        """포지션 청산 시 추적 데이터 리셋"""
        self._highest_prices.pop(position_key, None)
        self._partial_exits.pop(position_key, None)

    def get_position_status(self, metrics: PositionMetrics) -> Dict[str, Any]:
        """포지션 상태 요약"""
        position_key = metrics.position.token_id

        # 트레일링 스탑 상태
        trailing_active = metrics.pnl_pct >= self.trailing_stop_activation_pct
        trailing_distance = 0.0
        if trailing_active:
            highest_pnl_pct = ((metrics.highest_price - metrics.entry_price) / metrics.entry_price) * 100
            trailing_distance = highest_pnl_pct - metrics.pnl_pct

        return {
            "pnl_pct": metrics.pnl_pct,
            "pnl_usd": metrics.pnl_usd,
            "holding_hours": metrics.holding_hours,
            "stop_loss_distance": metrics.pnl_pct - self.stop_loss_pct,
            "take_profit_distance": self.take_profit_pct - metrics.pnl_pct,
            "trailing_stop_active": trailing_active,
            "trailing_distance": trailing_distance,
            "partial_exit_done": self._partial_exits.get(position_key, False),
            "status": self._get_status_label(metrics),
        }

    def _get_status_label(self, metrics: PositionMetrics) -> str:
        """포지션 상태 라벨"""
        if metrics.pnl_pct >= self.take_profit_pct:
            return "🎯 TARGET_REACHED"
        elif metrics.pnl_pct >= self.partial_take_profit_pct:
            return "📈 PROFITABLE"
        elif metrics.pnl_pct >= 0:
            return "➡️ BREAKEVEN"
        elif metrics.pnl_pct >= self.stop_loss_pct:
            return "⚠️ UNDERWATER"
        else:
            return "🚨 CRITICAL"
