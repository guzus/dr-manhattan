"""
Risk Manager

통합 리스크 관리자
"""

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional
import structlog

from .position_limits import PositionLimits, PositionLimitCheck
from .loss_limits import LossLimits, LossLimitCheck, TradingStatus

logger = structlog.get_logger()


@dataclass
class RiskCheckResult:
    """리스크 체크 결과"""

    can_trade: bool
    approved_size: float
    original_size: float
    position_check: PositionLimitCheck
    loss_check: LossLimitCheck
    warnings: List[str]
    reason: str


@dataclass
class PortfolioRiskMetrics:
    """포트폴리오 리스크 지표"""

    total_equity: float
    available_balance: float
    total_positions_value: float
    unrealized_pnl: float
    realized_pnl: float
    daily_pnl: float
    weekly_pnl: float
    high_water_mark: float
    current_drawdown_pct: float
    position_count: int
    position_utilization: float
    trading_status: TradingStatus


class RiskManager:
    """
    통합 리스크 관리자

    포지션 제한과 손실 제한을 통합 관리합니다.
    """

    def __init__(
        self,
        initial_equity: float = 1000.0,
        # Position Limits
        max_position_pct: float = 10.0,
        max_positions: int = 10,
        max_per_market_pct: float = 15.0,
        min_position_usd: float = 10.0,
        # Loss Limits
        daily_loss_limit_pct: float = 5.0,
        weekly_loss_limit_pct: float = 10.0,
        max_drawdown_pct: float = 20.0,
    ):
        """
        Args:
            initial_equity: 초기 자산
            max_position_pct: 단일 포지션 최대 비율 (%)
            max_positions: 최대 동시 포지션 수
            max_per_market_pct: 단일 시장 최대 비율 (%)
            min_position_usd: 최소 포지션 금액 (USD)
            daily_loss_limit_pct: 일일 손실 한도 (%)
            weekly_loss_limit_pct: 주간 손실 한도 (%)
            max_drawdown_pct: 최대 드로우다운 (%)
        """
        self.initial_equity = initial_equity
        self.high_water_mark = initial_equity

        self.position_limits = PositionLimits(
            max_position_pct=max_position_pct,
            max_positions=max_positions,
            max_per_market_pct=max_per_market_pct,
            min_position_usd=min_position_usd,
        )

        self.loss_limits = LossLimits(
            daily_loss_limit_pct=daily_loss_limit_pct,
            weekly_loss_limit_pct=weekly_loss_limit_pct,
            max_drawdown_pct=max_drawdown_pct,
        )

        # 현재 상태
        self._current_equity: float = initial_equity
        self._available_balance: float = initial_equity
        self._position_count: int = 0
        self._daily_pnl: float = 0.0
        self._weekly_pnl: float = 0.0

        logger.info(
            "Risk manager initialized",
            initial_equity=initial_equity,
            max_position_pct=max_position_pct,
            max_positions=max_positions,
            daily_loss_limit=daily_loss_limit_pct,
            weekly_loss_limit=weekly_loss_limit_pct,
            max_drawdown=max_drawdown_pct,
        )

    def check_trade(
        self,
        proposed_size: float,
        market_id: str,
        existing_position_in_market: float = 0.0,
    ) -> RiskCheckResult:
        """
        거래 리스크 체크

        Args:
            proposed_size: 제안된 포지션 사이즈 (USD)
            market_id: 시장 ID
            existing_position_in_market: 해당 시장 기존 포지션 (USD)

        Returns:
            RiskCheckResult: 리스크 체크 결과
        """
        warnings = []

        # 1. 손실 제한 체크
        loss_check = self.loss_limits.check(
            current_equity=self._current_equity,
            initial_equity=self.initial_equity,
            high_water_mark=self.high_water_mark,
            daily_pnl=self._daily_pnl,
            weekly_pnl=self._weekly_pnl,
        )

        if not loss_check.can_trade:
            logger.warning(
                "Trade rejected by loss limits",
                market_id=market_id,
                reason=loss_check.reason,
            )
            return RiskCheckResult(
                can_trade=False,
                approved_size=0,
                original_size=proposed_size,
                position_check=PositionLimitCheck(
                    passed=False, max_allowed_size=0, reason="Loss limit active"
                ),
                loss_check=loss_check,
                warnings=[loss_check.reason],
                reason=loss_check.reason,
            )

        # 2. 포지션 제한 체크
        position_check = self.position_limits.check_new_position(
            proposed_size=proposed_size,
            total_equity=self._current_equity,
            current_position_count=self._position_count,
            existing_position_in_market=existing_position_in_market,
        )

        if not position_check.passed:
            # 사이즈 조정 시도
            if position_check.max_allowed_size > self.position_limits.min_position_usd:
                approved_size = position_check.max_allowed_size
                warnings.append(
                    f"Size reduced from ${proposed_size:.2f} to ${approved_size:.2f}"
                )
            else:
                logger.warning(
                    "Trade rejected by position limits",
                    market_id=market_id,
                    reason=position_check.reason,
                )
                return RiskCheckResult(
                    can_trade=False,
                    approved_size=0,
                    original_size=proposed_size,
                    position_check=position_check,
                    loss_check=loss_check,
                    warnings=[position_check.reason],
                    reason=position_check.reason,
                )
        else:
            approved_size = proposed_size

        # 3. 사용 가능 잔고 체크
        if approved_size > self._available_balance:
            if self._available_balance >= self.position_limits.min_position_usd:
                approved_size = self._available_balance
                warnings.append(
                    f"Size limited by available balance: ${self._available_balance:.2f}"
                )
            else:
                return RiskCheckResult(
                    can_trade=False,
                    approved_size=0,
                    original_size=proposed_size,
                    position_check=position_check,
                    loss_check=loss_check,
                    warnings=["Insufficient available balance"],
                    reason=f"Insufficient balance: ${self._available_balance:.2f}",
                )

        # 4. 경고 추가
        if loss_check.current_daily_loss_pct > 3:
            warnings.append(
                f"Warning: Daily loss at {loss_check.current_daily_loss_pct:.1f}%"
            )

        if loss_check.current_drawdown_pct > 10:
            warnings.append(
                f"Warning: Drawdown at {loss_check.current_drawdown_pct:.1f}%"
            )

        logger.info(
            "Trade approved",
            market_id=market_id,
            original_size=proposed_size,
            approved_size=approved_size,
            warnings=warnings,
        )

        return RiskCheckResult(
            can_trade=True,
            approved_size=approved_size,
            original_size=proposed_size,
            position_check=position_check,
            loss_check=loss_check,
            warnings=warnings,
            reason="Trade approved",
        )

    def update_state(
        self,
        current_equity: float,
        available_balance: float,
        position_count: int,
        daily_pnl: float,
        weekly_pnl: float,
    ):
        """
        리스크 관리자 상태 업데이트

        Args:
            current_equity: 현재 자산
            available_balance: 사용 가능 잔고
            position_count: 현재 포지션 수
            daily_pnl: 일일 손익
            weekly_pnl: 주간 손익
        """
        self._current_equity = current_equity
        self._available_balance = available_balance
        self._position_count = position_count
        self._daily_pnl = daily_pnl
        self._weekly_pnl = weekly_pnl

        # High water mark 업데이트
        if current_equity > self.high_water_mark:
            self.high_water_mark = current_equity

    def record_trade_pnl(self, pnl: float):
        """거래 PnL 기록"""
        self.loss_limits.record_pnl(pnl, self._current_equity)
        self._daily_pnl += pnl
        self._weekly_pnl += pnl

    def get_portfolio_metrics(self) -> PortfolioRiskMetrics:
        """포트폴리오 리스크 지표 반환"""
        drawdown = (
            (self.high_water_mark - self._current_equity) / self.high_water_mark
            if self.high_water_mark > 0
            else 0
        )

        position_utilization = self.position_limits.get_position_utilization(
            self._current_equity - self._available_balance,
            self._current_equity,
        )

        loss_check = self.loss_limits.check(
            self._current_equity,
            self.initial_equity,
            self.high_water_mark,
            self._daily_pnl,
            self._weekly_pnl,
        )

        return PortfolioRiskMetrics(
            total_equity=self._current_equity,
            available_balance=self._available_balance,
            total_positions_value=self._current_equity - self._available_balance,
            unrealized_pnl=0,  # 별도 계산 필요
            realized_pnl=self._current_equity - self.initial_equity,
            daily_pnl=self._daily_pnl,
            weekly_pnl=self._weekly_pnl,
            high_water_mark=self.high_water_mark,
            current_drawdown_pct=drawdown * 100,
            position_count=self._position_count,
            position_utilization=position_utilization,
            trading_status=loss_check.status,
        )

    def reset_daily_pnl(self):
        """일일 PnL 리셋 (매일 자정)"""
        self._daily_pnl = 0.0
        self.loss_limits.reset_daily_limit()

    def reset_weekly_pnl(self):
        """주간 PnL 리셋 (매주 월요일)"""
        self._weekly_pnl = 0.0
        self.loss_limits.reset_weekly_limit()
