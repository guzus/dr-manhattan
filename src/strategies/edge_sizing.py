"""
Edge-Based Position Sizing

Edge 기반 포지션 사이징 전략
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class EdgeSizingResult:
    """Edge 기반 사이징 결과"""

    edge: float  # 절대 edge
    edge_pct: float  # Edge %
    base_size: float  # 기본 사이즈
    scaled_size: float  # 스케일된 사이즈
    final_size: float  # 최종 사이즈 (캡 적용)
    confidence_multiplier: float
    should_trade: bool
    reason: str


class EdgeBasedSizing:
    """
    Edge 기반 포지션 사이징

    edge가 클수록 더 큰 포지션을 취하는 전략
    """

    def __init__(
        self,
        min_edge: float = 0.05,  # 최소 5% edge
        base_edge: float = 0.10,  # 기준 edge (10%)
        base_size_pct: float = 5.0,  # 기준 포지션 사이즈 (%)
        max_size_pct: float = 10.0,  # 최대 포지션 사이즈 (%)
        min_size_usd: float = 10.0,  # 최소 포지션 (USD)
    ):
        """
        Args:
            min_edge: 거래를 위한 최소 edge
            base_edge: 기준 edge (이 edge에서 base_size_pct 사용)
            base_size_pct: 기준 포지션 사이즈 (%)
            max_size_pct: 최대 포지션 사이즈 (%)
            min_size_usd: 최소 포지션 금액 (USD)
        """
        self.min_edge = min_edge
        self.base_edge = base_edge
        self.base_size_pct = base_size_pct / 100.0
        self.max_size_pct = max_size_pct / 100.0
        self.min_size_usd = min_size_usd

    def calculate(
        self,
        estimated_probability: float,
        market_price: float,
        total_equity: float,
        available_balance: Optional[float] = None,
        confidence: str = "medium",
    ) -> EdgeSizingResult:
        """
        Edge 기반 포지션 사이즈 계산

        Args:
            estimated_probability: 예상 확률
            market_price: 시장 가격
            total_equity: 총 자산
            available_balance: 사용 가능 잔고
            confidence: 신뢰도 ("high", "medium", "low")

        Returns:
            EdgeSizingResult: 사이징 결과
        """
        if available_balance is None:
            available_balance = total_equity

        # Edge 계산
        edge = estimated_probability - market_price
        edge_pct = edge * 100

        # Edge가 부족하면 거래하지 않음
        if edge < self.min_edge:
            return EdgeSizingResult(
                edge=edge,
                edge_pct=edge_pct,
                base_size=0,
                scaled_size=0,
                final_size=0,
                confidence_multiplier=0,
                should_trade=False,
                reason=f"Insufficient edge: {edge_pct:.1f}% < {self.min_edge*100:.1f}%",
            )

        # 신뢰도 배수
        confidence_multipliers = {
            "high": 1.25,
            "medium": 1.0,
            "low": 0.75,
        }
        confidence_mult = confidence_multipliers.get(confidence, 1.0)

        # 기본 사이즈 (총 자산의 %)
        base_size = total_equity * self.base_size_pct

        # Edge 비율에 따른 스케일링
        # edge가 base_edge일 때 1.0x, 그 이상이면 더 크게
        edge_ratio = edge / self.base_edge
        scaled_size = base_size * edge_ratio * confidence_mult

        # 최대 사이즈 제한
        max_size = total_equity * self.max_size_pct
        capped_size = min(scaled_size, max_size)

        # 사용 가능 잔고로 제한
        final_size = min(capped_size, available_balance)

        # 최소 사이즈 확인
        if final_size < self.min_size_usd:
            return EdgeSizingResult(
                edge=edge,
                edge_pct=edge_pct,
                base_size=base_size,
                scaled_size=scaled_size,
                final_size=0,
                confidence_multiplier=confidence_mult,
                should_trade=False,
                reason=f"Position too small: ${final_size:.2f} < ${self.min_size_usd:.2f}",
            )

        return EdgeSizingResult(
            edge=edge,
            edge_pct=edge_pct,
            base_size=base_size,
            scaled_size=scaled_size,
            final_size=final_size,
            confidence_multiplier=confidence_mult,
            should_trade=True,
            reason=f"Edge: {edge_pct:.1f}%, Size: ${final_size:.2f}",
        )

    def calculate_for_both_sides(
        self,
        estimated_prob_yes: float,
        estimated_prob_no: float,
        market_price_yes: float,
        market_price_no: float,
        total_equity: float,
        available_balance: Optional[float] = None,
        confidence: str = "medium",
    ) -> dict:
        """
        YES와 NO 양쪽 edge 계산

        Returns:
            dict: YES/NO 각각의 사이징 결과
        """
        yes_result = self.calculate(
            estimated_prob_yes,
            market_price_yes,
            total_equity,
            available_balance,
            confidence,
        )

        no_result = self.calculate(
            estimated_prob_no,
            market_price_no,
            total_equity,
            available_balance,
            confidence,
        )

        # 더 좋은 edge를 가진 쪽 선택
        if yes_result.should_trade and no_result.should_trade:
            recommended = "YES" if yes_result.edge > no_result.edge else "NO"
        elif yes_result.should_trade:
            recommended = "YES"
        elif no_result.should_trade:
            recommended = "NO"
        else:
            recommended = None

        return {
            "yes": yes_result,
            "no": no_result,
            "recommended_side": recommended,
            "recommended_result": yes_result if recommended == "YES" else (
                no_result if recommended == "NO" else None
            ),
        }
