"""
Market Filter

거래 대상 시장 필터링
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from src.core.polymarket.models import MarketData


@dataclass
class MarketFilterResult:
    """시장 필터링 결과"""

    market: MarketData
    passed: bool
    score: float  # 종합 점수 (높을수록 좋음)
    reasons: List[str]  # 필터 통과/실패 이유


class MarketFilter:
    """
    시장 필터

    거래에 적합한 시장을 선별합니다.
    """

    def __init__(
        self,
        min_liquidity: float = 50000.0,  # 최소 유동성 ($50k)
        min_volume_24h: float = 10000.0,  # 최소 24시간 거래량 ($10k)
        max_spread: float = 0.10,  # 최대 스프레드 (10%)
        min_days_to_resolution: int = 1,  # 최소 결과까지 일수
        max_days_to_resolution: int = 60,  # 최대 결과까지 일수
        allowed_categories: Optional[List[str]] = None,
        excluded_keywords: Optional[List[str]] = None,
    ):
        """
        Args:
            min_liquidity: 최소 유동성
            min_volume_24h: 최소 24시간 거래량
            max_spread: 최대 허용 스프레드
            min_days_to_resolution: 최소 결과까지 일수
            max_days_to_resolution: 최대 결과까지 일수
            allowed_categories: 허용 카테고리 목록
            excluded_keywords: 제외 키워드 목록
        """
        self.min_liquidity = min_liquidity
        self.min_volume_24h = min_volume_24h
        self.max_spread = max_spread
        self.min_days_to_resolution = min_days_to_resolution
        self.max_days_to_resolution = max_days_to_resolution
        self.allowed_categories = allowed_categories or ["politics", "sports", "crypto"]
        self.excluded_keywords = excluded_keywords or []

    def filter(self, market: MarketData) -> MarketFilterResult:
        """
        단일 시장 필터링

        Args:
            market: 필터링할 시장

        Returns:
            MarketFilterResult: 필터링 결과
        """
        reasons = []
        score = 0.0
        passed = True

        # 1. 활성 상태 확인
        if not market.is_active or market.is_resolved:
            passed = False
            reasons.append("Market is not active or already resolved")
            return MarketFilterResult(market=market, passed=False, score=0, reasons=reasons)

        # 2. 유동성 확인
        if market.liquidity >= self.min_liquidity:
            score += 20
            reasons.append(f"✓ Liquidity: ${market.liquidity:,.0f}")
        else:
            passed = False
            reasons.append(
                f"✗ Insufficient liquidity: ${market.liquidity:,.0f} < ${self.min_liquidity:,.0f}"
            )

        # 3. 거래량 확인
        if market.volume_24h >= self.min_volume_24h:
            score += 20
            reasons.append(f"✓ 24h Volume: ${market.volume_24h:,.0f}")
        else:
            passed = False
            reasons.append(
                f"✗ Insufficient volume: ${market.volume_24h:,.0f} < ${self.min_volume_24h:,.0f}"
            )

        # 4. 스프레드 확인
        spread = abs(market.yes_price + market.no_price - 1.0)
        if spread <= self.max_spread:
            score += 15
            reasons.append(f"✓ Spread: {spread:.1%}")
        else:
            passed = False
            reasons.append(f"✗ Spread too wide: {spread:.1%} > {self.max_spread:.1%}")

        # 5. 결과 일자 확인
        if market.end_date:
            # timezone-aware datetime 비교
            now = datetime.now(timezone.utc)
            end_date = market.end_date
            if end_date.tzinfo is None:
                end_date = end_date.replace(tzinfo=timezone.utc)
            days_to_resolution = (end_date - now).days

            if days_to_resolution < self.min_days_to_resolution:
                passed = False
                reasons.append(
                    f"✗ Too close to resolution: {days_to_resolution} days"
                )
            elif days_to_resolution > self.max_days_to_resolution:
                passed = False
                reasons.append(
                    f"✗ Too far from resolution: {days_to_resolution} days"
                )
            else:
                score += 15
                reasons.append(f"✓ Days to resolution: {days_to_resolution}")
        else:
            # 종료일 정보 없음 - 패스하되 점수 낮춤
            score += 5
            reasons.append("△ No end date specified")

        # 6. 카테고리 확인 (카테고리가 None인 경우는 통과 - 많은 마켓이 카테고리 없음)
        if self.allowed_categories:
            market_category = (market.category or "").lower()
            market_tags = [t.lower() for t in market.tags]

            # 카테고리가 없거나 허용 목록에 있으면 통과
            if not market.category:
                score += 10
                reasons.append("△ No category specified (allowed)")
            else:
                category_match = any(
                    cat.lower() in market_category or cat.lower() in market_tags
                    for cat in self.allowed_categories
                )

                if category_match:
                    score += 15
                    reasons.append(f"✓ Category: {market.category}")
                else:
                    # 카테고리가 있지만 허용 목록에 없으면 통과하되 점수 낮춤
                    score += 5
                    reasons.append(f"△ Category not in preferred list: {market.category}")

        # 7. 제외 키워드 확인
        if self.excluded_keywords:
            question_lower = market.question.lower()
            for keyword in self.excluded_keywords:
                if keyword.lower() in question_lower:
                    passed = False
                    reasons.append(f"✗ Contains excluded keyword: {keyword}")
                    break

        # 8. 가격 범위 확인 (너무 극단적인 가격은 제외)
        if 0.05 <= market.yes_price <= 0.95:
            score += 15
            reasons.append(f"✓ Price range OK: YES=${market.yes_price:.2f}")
        else:
            # 경고만, 필터 실패는 아님
            score += 5
            reasons.append(
                f"△ Extreme price: YES=${market.yes_price:.2f} (may have limited upside)"
            )

        return MarketFilterResult(
            market=market,
            passed=passed,
            score=score,
            reasons=reasons,
        )

    def filter_markets(
        self,
        markets: List[MarketData],
        top_n: Optional[int] = None,
    ) -> List[MarketFilterResult]:
        """
        여러 시장 필터링 및 정렬

        Args:
            markets: 필터링할 시장 목록
            top_n: 상위 N개만 반환 (None이면 전체)

        Returns:
            List[MarketFilterResult]: 필터 통과한 시장들 (점수순 정렬)
        """
        results = [self.filter(m) for m in markets]

        # 통과한 것만 필터
        passed_results = [r for r in results if r.passed]

        # 점수순 정렬
        passed_results.sort(key=lambda r: r.score, reverse=True)

        if top_n:
            return passed_results[:top_n]

        return passed_results

    def get_tradeable_markets(
        self,
        markets: List[MarketData],
        top_n: int = 10,
    ) -> List[MarketData]:
        """
        거래 가능한 시장만 반환

        Args:
            markets: 시장 목록
            top_n: 상위 N개

        Returns:
            List[MarketData]: 필터 통과한 시장들
        """
        results = self.filter_markets(markets, top_n)
        return [r.market for r in results]
