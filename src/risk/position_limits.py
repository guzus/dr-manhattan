"""
Position Limits

포지션 제한 관리
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class PositionLimitCheck:
    """포지션 제한 체크 결과"""

    passed: bool
    max_allowed_size: float
    reason: str


class PositionLimits:
    """
    포지션 제한 관리

    단일 포지션 및 전체 포트폴리오 레벨의 포지션 제한을 관리합니다.
    """

    def __init__(
        self,
        max_position_pct: float = 10.0,  # 단일 포지션 최대 10%
        max_positions: int = 10,  # 최대 동시 포지션 수
        max_per_market_pct: float = 15.0,  # 단일 시장 최대 15%
        max_correlated_pct: float = 30.0,  # 상관관계 있는 시장 합계 최대 30%
        min_position_usd: float = 10.0,  # 최소 포지션 금액
    ):
        """
        Args:
            max_position_pct: 단일 포지션 최대 비율 (%)
            max_positions: 최대 동시 포지션 수
            max_per_market_pct: 단일 시장 최대 비율 (%)
            max_correlated_pct: 상관 시장 합계 최대 비율 (%)
            min_position_usd: 최소 포지션 금액 (USD)
        """
        self.max_position_pct = max_position_pct / 100.0
        self.max_positions = max_positions
        self.max_per_market_pct = max_per_market_pct / 100.0
        self.max_correlated_pct = max_correlated_pct / 100.0
        self.min_position_usd = min_position_usd

    def check_new_position(
        self,
        proposed_size: float,
        total_equity: float,
        current_position_count: int,
        existing_position_in_market: float = 0.0,
    ) -> PositionLimitCheck:
        """
        새 포지션 제한 체크

        Args:
            proposed_size: 제안된 포지션 사이즈 (USD)
            total_equity: 총 자산
            current_position_count: 현재 포지션 수
            existing_position_in_market: 해당 시장 기존 포지션 (USD)

        Returns:
            PositionLimitCheck: 체크 결과
        """
        # 최소 포지션 체크
        if proposed_size < self.min_position_usd:
            return PositionLimitCheck(
                passed=False,
                max_allowed_size=0,
                reason=f"Position too small: ${proposed_size:.2f} < ${self.min_position_usd:.2f}",
            )

        # 최대 포지션 수 체크
        if current_position_count >= self.max_positions and existing_position_in_market == 0:
            return PositionLimitCheck(
                passed=False,
                max_allowed_size=0,
                reason=f"Max positions reached: {current_position_count}/{self.max_positions}",
            )

        # 단일 포지션 제한 체크
        max_single_position = total_equity * self.max_position_pct
        if proposed_size > max_single_position:
            return PositionLimitCheck(
                passed=False,
                max_allowed_size=max_single_position,
                reason=f"Exceeds single position limit: ${proposed_size:.2f} > ${max_single_position:.2f}",
            )

        # 시장당 최대 제한 체크
        total_in_market = existing_position_in_market + proposed_size
        max_per_market = total_equity * self.max_per_market_pct
        if total_in_market > max_per_market:
            max_allowed = max_per_market - existing_position_in_market
            return PositionLimitCheck(
                passed=False,
                max_allowed_size=max(0, max_allowed),
                reason=f"Exceeds per-market limit: ${total_in_market:.2f} > ${max_per_market:.2f}",
            )

        return PositionLimitCheck(
            passed=True,
            max_allowed_size=min(max_single_position, max_per_market - existing_position_in_market),
            reason="Position within limits",
        )

    def calculate_max_position(
        self,
        total_equity: float,
        existing_position_in_market: float = 0.0,
    ) -> float:
        """
        최대 가능 포지션 사이즈 계산

        Args:
            total_equity: 총 자산
            existing_position_in_market: 해당 시장 기존 포지션

        Returns:
            float: 최대 가능 포지션 사이즈 (USD)
        """
        max_single = total_equity * self.max_position_pct
        max_per_market = total_equity * self.max_per_market_pct
        remaining_in_market = max_per_market - existing_position_in_market

        return max(0, min(max_single, remaining_in_market))

    def get_position_utilization(
        self,
        total_positions_value: float,
        total_equity: float,
    ) -> float:
        """
        포지션 활용률 계산

        Args:
            total_positions_value: 전체 포지션 가치
            total_equity: 총 자산

        Returns:
            float: 활용률 (0.0 ~ 1.0)
        """
        if total_equity <= 0:
            return 0.0
        return total_positions_value / total_equity
