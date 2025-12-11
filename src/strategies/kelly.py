"""
Kelly Criterion Implementation

포지션 사이징을 위한 Kelly Criterion 구현
"""

from dataclasses import dataclass
from typing import Optional
import math


@dataclass
class KellyResult:
    """Kelly Criterion 계산 결과"""

    full_kelly: float  # 전체 Kelly 비율
    fractional_kelly: float  # Fractional Kelly 비율
    recommended_fraction: float  # 추천 투자 비율
    expected_growth: float  # 기대 성장률
    edge: float  # Edge (확률 우위)
    odds: float  # 배당률


class KellyCriterion:
    """
    Kelly Criterion

    f* = (p * b - q) / b

    where:
    - f* = 베팅해야 할 자본 비율
    - p = 승리 확률
    - q = 패배 확률 (1 - p)
    - b = 순 배당률 (이익/손실 비율)

    예측 시장에서:
    - 가격이 0.40인 YES를 구매할 때:
      - 승리 시: $1.00 수령 (순 이익 = $0.60, 배당률 = 0.60/0.40 = 1.5)
      - 패배 시: $0.40 손실
    """

    @staticmethod
    def calculate(
        estimated_probability: float,
        market_price: float,
    ) -> KellyResult:
        """
        Kelly 비율 계산

        Args:
            estimated_probability: 예상 승리 확률 (0.0 ~ 1.0)
            market_price: 현재 시장 가격 (0.0 ~ 1.0)

        Returns:
            KellyResult: Kelly 계산 결과
        """
        # Clamp inputs
        p = max(0.01, min(0.99, estimated_probability))
        price = max(0.01, min(0.99, market_price))

        q = 1 - p

        # 배당률 계산
        # 승리 시 순 이익 = 1.0 - price
        # 손실 = price
        # odds = (1.0 - price) / price
        odds = (1.0 - price) / price

        # Kelly 공식: f* = (p * b - q) / b
        # 간소화: f* = p - q/b = p - q * price / (1 - price)
        full_kelly = (p * odds - q) / odds

        # Edge (확률 우위)
        edge = p - price

        # 기대 성장률 (로그 수익률)
        if full_kelly > 0:
            expected_growth = p * math.log(1 + full_kelly * odds) + q * math.log(
                1 - full_kelly
            )
        else:
            expected_growth = 0.0

        return KellyResult(
            full_kelly=max(0, full_kelly),
            fractional_kelly=max(0, full_kelly * 0.25),  # Quarter Kelly
            recommended_fraction=max(0, full_kelly * 0.25),
            expected_growth=expected_growth,
            edge=edge,
            odds=odds,
        )

    @staticmethod
    def calculate_bet_size(
        estimated_probability: float,
        market_price: float,
        bankroll: float,
        fraction: float = 0.25,
        max_bet_fraction: float = 0.10,
    ) -> float:
        """
        실제 베팅 금액 계산

        Args:
            estimated_probability: 예상 승리 확률
            market_price: 현재 시장 가격
            bankroll: 현재 자본금
            fraction: Kelly 분수 (기본 0.25 = Quarter Kelly)
            max_bet_fraction: 최대 베팅 비율 (기본 10%)

        Returns:
            float: 베팅 금액 (USD)
        """
        result = KellyCriterion.calculate(estimated_probability, market_price)

        # Fractional Kelly
        kelly_fraction = result.full_kelly * fraction

        # Cap at max bet fraction
        capped_fraction = min(kelly_fraction, max_bet_fraction)

        # 음수 Kelly (edge 없음)면 베팅하지 않음
        if capped_fraction <= 0:
            return 0.0

        return bankroll * capped_fraction


class FractionalKelly:
    """
    Fractional Kelly Betting

    다양한 fraction 옵션을 제공하는 Kelly 구현
    """

    # 일반적인 Fractional Kelly 값들
    FULL = 1.0  # 100% Kelly (매우 공격적, 비추천)
    HALF = 0.5  # 50% Kelly (공격적)
    QUARTER = 0.25  # 25% Kelly (중간, 권장)
    EIGHTH = 0.125  # 12.5% Kelly (보수적)
    TENTH = 0.1  # 10% Kelly (매우 보수적)

    def __init__(
        self,
        fraction: float = QUARTER,
        max_bet_pct: float = 10.0,
        min_edge: float = 0.05,
    ):
        """
        Args:
            fraction: Kelly 분수 (기본 0.25)
            max_bet_pct: 최대 베팅 비율 (%)
            min_edge: 최소 edge 요구량
        """
        self.fraction = fraction
        self.max_bet_pct = max_bet_pct / 100.0
        self.min_edge = min_edge

    def calculate_position_size(
        self,
        estimated_probability: float,
        market_price: float,
        total_equity: float,
        available_balance: Optional[float] = None,
    ) -> float:
        """
        포지션 사이즈 계산

        Args:
            estimated_probability: 예상 확률
            market_price: 시장 가격
            total_equity: 총 자산
            available_balance: 사용 가능 잔고 (없으면 total_equity 사용)

        Returns:
            float: 포지션 사이즈 (USD)
        """
        if available_balance is None:
            available_balance = total_equity

        # Edge 확인
        edge = estimated_probability - market_price
        if edge < self.min_edge:
            return 0.0

        # Kelly 계산
        result = KellyCriterion.calculate(estimated_probability, market_price)

        # Fractional Kelly
        kelly_fraction = result.full_kelly * self.fraction

        # Cap at max bet
        capped_fraction = min(kelly_fraction, self.max_bet_pct)

        if capped_fraction <= 0:
            return 0.0

        # 총 자산 기준 계산
        position_size = total_equity * capped_fraction

        # 사용 가능 잔고로 제한
        position_size = min(position_size, available_balance)

        return position_size

    def get_kelly_breakdown(
        self,
        estimated_probability: float,
        market_price: float,
    ) -> dict:
        """Kelly 계산 상세 분해"""
        result = KellyCriterion.calculate(estimated_probability, market_price)

        return {
            "estimated_probability": estimated_probability,
            "market_price": market_price,
            "edge": result.edge,
            "edge_pct": result.edge * 100,
            "odds": result.odds,
            "full_kelly": result.full_kelly,
            "full_kelly_pct": result.full_kelly * 100,
            "fractional_kelly": result.full_kelly * self.fraction,
            "fractional_kelly_pct": result.full_kelly * self.fraction * 100,
            "recommended_fraction": min(
                result.full_kelly * self.fraction, self.max_bet_pct
            ),
            "recommended_fraction_pct": min(
                result.full_kelly * self.fraction, self.max_bet_pct
            ) * 100,
            "expected_growth": result.expected_growth,
        }
