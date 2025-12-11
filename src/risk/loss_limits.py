"""
Loss Limits

손실 제한 관리
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional
from enum import Enum


class TradingStatus(str, Enum):
    ACTIVE = "active"
    DAILY_LIMIT = "daily_limit"
    WEEKLY_LIMIT = "weekly_limit"
    DRAWDOWN_LIMIT = "drawdown_limit"
    SUSPENDED = "suspended"


@dataclass
class LossLimitCheck:
    """손실 제한 체크 결과"""

    can_trade: bool
    status: TradingStatus
    current_daily_loss_pct: float
    current_weekly_loss_pct: float
    current_drawdown_pct: float
    reason: str


@dataclass
class PnLRecord:
    """PnL 기록"""

    timestamp: datetime
    pnl: float
    equity: float


class LossLimits:
    """
    손실 제한 관리

    일일, 주간, 최대 드로우다운 손실 제한을 관리합니다.
    """

    def __init__(
        self,
        daily_loss_limit_pct: float = 5.0,  # 일일 손실 한도 5%
        weekly_loss_limit_pct: float = 10.0,  # 주간 손실 한도 10%
        max_drawdown_pct: float = 20.0,  # 최대 드로우다운 20%
        cooldown_hours_daily: int = 24,  # 일일 한도 후 쿨다운
        cooldown_hours_weekly: int = 24,  # 주간 한도 후 쿨다운
    ):
        """
        Args:
            daily_loss_limit_pct: 일일 손실 한도 (%)
            weekly_loss_limit_pct: 주간 손실 한도 (%)
            max_drawdown_pct: 최대 드로우다운 (%)
            cooldown_hours_daily: 일일 한도 도달 후 쿨다운 시간
            cooldown_hours_weekly: 주간 한도 도달 후 쿨다운 시간
        """
        self.daily_loss_limit = daily_loss_limit_pct / 100.0
        self.weekly_loss_limit = weekly_loss_limit_pct / 100.0
        self.max_drawdown = max_drawdown_pct / 100.0
        self.cooldown_hours_daily = cooldown_hours_daily
        self.cooldown_hours_weekly = cooldown_hours_weekly

        # 상태 추적
        self._daily_limit_triggered_at: Optional[datetime] = None
        self._weekly_limit_triggered_at: Optional[datetime] = None
        self._pnl_history: List[PnLRecord] = []

    def check(
        self,
        current_equity: float,
        initial_equity: float,
        high_water_mark: float,
        daily_pnl: float,
        weekly_pnl: float,
    ) -> LossLimitCheck:
        """
        손실 제한 체크

        Args:
            current_equity: 현재 자산
            initial_equity: 초기 자산
            high_water_mark: 최고점 자산
            daily_pnl: 일일 손익
            weekly_pnl: 주간 손익

        Returns:
            LossLimitCheck: 체크 결과
        """
        # 손실률 계산
        daily_loss_pct = -daily_pnl / initial_equity if initial_equity > 0 else 0
        weekly_loss_pct = -weekly_pnl / initial_equity if initial_equity > 0 else 0
        drawdown_pct = (
            (high_water_mark - current_equity) / high_water_mark
            if high_water_mark > 0
            else 0
        )

        now = datetime.utcnow()

        # 일일 쿨다운 체크
        if self._daily_limit_triggered_at:
            cooldown_end = self._daily_limit_triggered_at + timedelta(
                hours=self.cooldown_hours_daily
            )
            if now < cooldown_end:
                return LossLimitCheck(
                    can_trade=False,
                    status=TradingStatus.DAILY_LIMIT,
                    current_daily_loss_pct=daily_loss_pct * 100,
                    current_weekly_loss_pct=weekly_loss_pct * 100,
                    current_drawdown_pct=drawdown_pct * 100,
                    reason=f"Daily limit cooldown until {cooldown_end.isoformat()}",
                )
            else:
                self._daily_limit_triggered_at = None

        # 주간 쿨다운 체크
        if self._weekly_limit_triggered_at:
            cooldown_end = self._weekly_limit_triggered_at + timedelta(
                hours=self.cooldown_hours_weekly
            )
            if now < cooldown_end:
                return LossLimitCheck(
                    can_trade=False,
                    status=TradingStatus.WEEKLY_LIMIT,
                    current_daily_loss_pct=daily_loss_pct * 100,
                    current_weekly_loss_pct=weekly_loss_pct * 100,
                    current_drawdown_pct=drawdown_pct * 100,
                    reason=f"Weekly limit cooldown until {cooldown_end.isoformat()}",
                )
            else:
                self._weekly_limit_triggered_at = None

        # 최대 드로우다운 체크
        if drawdown_pct >= self.max_drawdown:
            return LossLimitCheck(
                can_trade=False,
                status=TradingStatus.DRAWDOWN_LIMIT,
                current_daily_loss_pct=daily_loss_pct * 100,
                current_weekly_loss_pct=weekly_loss_pct * 100,
                current_drawdown_pct=drawdown_pct * 100,
                reason=f"Max drawdown exceeded: {drawdown_pct*100:.1f}% >= {self.max_drawdown*100:.1f}%",
            )

        # 일일 손실 한도 체크
        if daily_loss_pct >= self.daily_loss_limit:
            self._daily_limit_triggered_at = now
            return LossLimitCheck(
                can_trade=False,
                status=TradingStatus.DAILY_LIMIT,
                current_daily_loss_pct=daily_loss_pct * 100,
                current_weekly_loss_pct=weekly_loss_pct * 100,
                current_drawdown_pct=drawdown_pct * 100,
                reason=f"Daily loss limit: {daily_loss_pct*100:.1f}% >= {self.daily_loss_limit*100:.1f}%",
            )

        # 주간 손실 한도 체크
        if weekly_loss_pct >= self.weekly_loss_limit:
            self._weekly_limit_triggered_at = now
            return LossLimitCheck(
                can_trade=False,
                status=TradingStatus.WEEKLY_LIMIT,
                current_daily_loss_pct=daily_loss_pct * 100,
                current_weekly_loss_pct=weekly_loss_pct * 100,
                current_drawdown_pct=drawdown_pct * 100,
                reason=f"Weekly loss limit: {weekly_loss_pct*100:.1f}% >= {self.weekly_loss_limit*100:.1f}%",
            )

        return LossLimitCheck(
            can_trade=True,
            status=TradingStatus.ACTIVE,
            current_daily_loss_pct=daily_loss_pct * 100,
            current_weekly_loss_pct=weekly_loss_pct * 100,
            current_drawdown_pct=drawdown_pct * 100,
            reason="Within all loss limits",
        )

    def record_pnl(self, pnl: float, equity: float):
        """PnL 기록 추가"""
        self._pnl_history.append(
            PnLRecord(timestamp=datetime.utcnow(), pnl=pnl, equity=equity)
        )

        # 30일치만 보관
        cutoff = datetime.utcnow() - timedelta(days=30)
        self._pnl_history = [r for r in self._pnl_history if r.timestamp >= cutoff]

    def calculate_daily_pnl(self) -> float:
        """일일 PnL 계산"""
        today = datetime.utcnow().date()
        daily_records = [
            r for r in self._pnl_history if r.timestamp.date() == today
        ]
        return sum(r.pnl for r in daily_records)

    def calculate_weekly_pnl(self) -> float:
        """주간 PnL 계산"""
        week_start = datetime.utcnow() - timedelta(days=7)
        weekly_records = [
            r for r in self._pnl_history if r.timestamp >= week_start
        ]
        return sum(r.pnl for r in weekly_records)

    def reset_daily_limit(self):
        """일일 제한 리셋"""
        self._daily_limit_triggered_at = None

    def reset_weekly_limit(self):
        """주간 제한 리셋"""
        self._weekly_limit_triggered_at = None

    def reset_all(self):
        """모든 제한 리셋"""
        self._daily_limit_triggered_at = None
        self._weekly_limit_triggered_at = None
        self._pnl_history.clear()
