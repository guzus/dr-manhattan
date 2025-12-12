"""
Trading Loop

메인 트레이딩 루프 - 주기적으로 시장을 분석하고 거래를 실행합니다.

개선된 라이프사이클:
1. 포지션 가격 실시간 업데이트
2. Exit 시그널 체크 (익절/손절/트레일링)
3. 가격 변동 기반 포지션 재분석
4. 신규 시장 탐색 및 진입
"""

import asyncio
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Union
import structlog

from src.agents import AgentOrchestrator, TradingDecision
from src.core.llm import OpenAIProvider
from src.core.polymarket import DemoPolymarketClient
from src.core.polymarket.persistent_demo_client import PersistentDemoClient
from src.core.polymarket.models import MarketData, Order, Side, OutcomeSide, PositionData
from src.strategies import MarketFilter, FractionalKelly
from src.strategies.exit_manager import ExitManager, ExitSignal, ExitReason
from src.risk import RiskManager
from src.core.database.connection import get_db_session
from src.core.database.models import Decision as DecisionModel

logger = structlog.get_logger()


async def save_decision_to_db(
    decision: TradingDecision,
    market: Optional[MarketData] = None,
) -> None:
    """TradingDecision을 DB에 저장"""
    try:
        async with get_db_session() as session:
            # Agent 분석 결과 요약 추출
            research_summary = None
            probability_assessment = None
            sentiment_analysis = None
            risk_assessment = None
            arbiter_reasoning = None

            if decision.research_result and decision.research_result.success:
                research_data = decision.research_result.data
                research_summary = research_data.get("summary", research_data.get("analysis", ""))[:1000]

            if decision.probability_result and decision.probability_result.success:
                prob_data = decision.probability_result.data
                probability_assessment = f"YES: {prob_data.get('estimated_probability_yes', 'N/A')}, NO: {prob_data.get('estimated_probability_no', 'N/A')}, Edge: {prob_data.get('edge', 'N/A')}"

            if decision.sentiment_result and decision.sentiment_result.success:
                sent_data = decision.sentiment_result.data
                sentiment_analysis = f"Score: {sent_data.get('sentiment_score', 'N/A')}, Market: {sent_data.get('market_sentiment', 'N/A')}"

            if decision.risk_result and decision.risk_result.success:
                risk_data = decision.risk_result.data
                risk_assessment = f"Should Trade: {risk_data.get('should_trade', False)}, Size: ${risk_data.get('recommended_position_size_usd', 0):.2f}"

            if decision.arbiter_result and decision.arbiter_result.success:
                arbiter_reasoning = decision.reasoning[:2000] if decision.reasoning else None

            # Decision DB 모델 생성
            db_decision = DecisionModel(
                market_id=decision.market_id,
                decision_type="trading",
                decision={
                    "action": decision.action,
                    "side": decision.side,
                    "decision": decision.decision,
                    "confidence": decision.confidence,
                    "position_size_usd": decision.position_size_usd,
                    "should_trade": decision.should_trade,
                },
                confidence={"high": 0.8, "medium": 0.5, "low": 0.3}.get(decision.confidence, 0.5),
                action=decision.action,
                side=decision.side,
                position_size_usd=decision.position_size_usd,
                limit_price=decision.limit_price,
                market_question=market.question[:500] if market else None,
                research_summary=research_summary,
                probability_assessment=probability_assessment,
                sentiment_analysis=sentiment_analysis,
                risk_assessment=risk_assessment,
                arbiter_reasoning=arbiter_reasoning,
                total_tokens=decision.total_tokens,
                cost=decision.total_cost,
                created_at=decision.timestamp,
            )

            session.add(db_decision)
            await session.commit()

            logger.debug(
                "Decision saved to DB",
                market_id=decision.market_id,
                decision=decision.decision,
            )
    except Exception as e:
        logger.error(f"Failed to save decision to DB: {e}", exc_info=True)


class TradingLoop:
    """
    메인 트레이딩 루프

    개선된 라이프사이클:
    1. 포지션 가격 실시간 업데이트
    2. Exit 시그널 체크 (익절/손절/트레일링)
    3. 가격 변동 기반 포지션 재분석
    4. 신규 시장 탐색 및 진입
    """

    def __init__(
        self,
        openai_api_key: str,
        initial_balance: float = 1000.0,
        interval_minutes: int = 15,
        max_markets_per_cycle: int = 5,
        demo_mode: bool = True,
        # Exit Manager 설정
        take_profit_pct: float = 20.0,
        stop_loss_pct: float = -15.0,
        # 가격 변동 재분석 임계값
        price_change_threshold_pct: float = 5.0,
        # Persistent client 사용 여부
        use_persistent_client: bool = False,
    ):
        """
        Args:
            openai_api_key: OpenAI API 키
            initial_balance: 초기 자본
            interval_minutes: 실행 간격 (분)
            max_markets_per_cycle: 사이클당 분석할 최대 시장 수
            demo_mode: 데모 모드 여부
            take_profit_pct: 익절 비율 (%)
            stop_loss_pct: 손절 비율 (%)
            price_change_threshold_pct: 재분석 트리거 가격 변동률 (%)
            use_persistent_client: SQLite 영속화 클라이언트 사용 여부
        """
        self.interval_minutes = interval_minutes
        self.max_markets_per_cycle = max_markets_per_cycle
        self.demo_mode = demo_mode
        self.price_change_threshold_pct = price_change_threshold_pct
        self.use_persistent_client = use_persistent_client

        # Components
        self.llm_provider = OpenAIProvider(
            api_key=openai_api_key,
            default_model="gpt-4o-mini",
        )

        # Choose client based on persistence setting
        if use_persistent_client:
            self.polymarket_client: Union[DemoPolymarketClient, PersistentDemoClient] = PersistentDemoClient(
                initial_balance=initial_balance,
            )
        else:
            self.polymarket_client = DemoPolymarketClient(
                initial_balance=initial_balance,
            )

        self.orchestrator = AgentOrchestrator(
            llm_provider=self.llm_provider,
        )

        self.market_filter = MarketFilter(
            min_liquidity=10000,  # 데모용으로 낮춤
            min_volume_24h=1000,
            max_spread=0.15,
            allowed_categories=["politics", "sports", "crypto"],
        )

        self.kelly = FractionalKelly(
            fraction=0.25,
            max_bet_pct=10.0,
            min_edge=0.05,
        )

        self.risk_manager = RiskManager(
            initial_equity=initial_balance,
            max_position_pct=10.0,
            max_positions=10,
            daily_loss_limit_pct=5.0,
            weekly_loss_limit_pct=10.0,
            max_drawdown_pct=20.0,
        )

        # Exit Manager (퀀트 방식 익절/손절 관리)
        self.exit_manager = ExitManager(
            take_profit_pct=take_profit_pct,
            stop_loss_pct=stop_loss_pct,
        )

        # State
        self._running = False
        self._last_run: Optional[datetime] = None
        self._cycle_count = 0
        self._total_decisions = 0
        self._total_trades = 0
        self._total_exits = 0

        # 포지션 진입 시간 추적
        self._position_entry_times: Dict[str, datetime] = {}
        # 마지막 분석 시 가격 추적 (재분석 트리거용)
        self._last_analyzed_prices: Dict[str, float] = {}

        logger.info(
            "Trading loop initialized",
            demo_mode=demo_mode,
            initial_balance=initial_balance,
            interval_minutes=interval_minutes,
            take_profit_pct=take_profit_pct,
            stop_loss_pct=stop_loss_pct,
            use_persistent_client=use_persistent_client,
        )

    async def run_once(self) -> List[TradingDecision]:
        """
        단일 트레이딩 사이클 실행 (개선된 라이프사이클)

        Returns:
            List[TradingDecision]: 이번 사이클의 결정들
        """
        self._cycle_count += 1
        cycle_start = datetime.utcnow()

        logger.info(
            f"Starting trading cycle #{self._cycle_count}",
            timestamp=cycle_start.isoformat(),
        )

        decisions = []
        exits_executed = 0

        try:
            # ============================================
            # Phase 1: 포지션 업데이트 및 가격 갱신
            # ============================================
            equity = await self.polymarket_client.get_equity()
            balance = await self.polymarket_client.get_balance()
            positions = await self.polymarket_client.get_positions()

            # 포지션 토큰 가격 갱신
            if positions:
                token_ids = [p.token_id for p in positions]
                await self.polymarket_client.refresh_prices(token_ids)
                # 갱신된 가격으로 포지션 다시 조회
                positions = await self.polymarket_client.get_positions()

            self.risk_manager.update_state(
                current_equity=equity,
                available_balance=balance,
                position_count=len(positions),
                daily_pnl=0,  # TODO: 실제 PnL 계산
                weekly_pnl=0,
            )

            logger.info(
                "Portfolio updated",
                equity=f"${equity:.2f}",
                balance=f"${balance:.2f}",
                positions=len(positions),
            )

            # ============================================
            # Phase 2: Exit 시그널 체크 (익절/손절/트레일링)
            # ============================================
            for position in positions:
                entry_time = self._position_entry_times.get(
                    position.token_id, datetime.utcnow() - timedelta(hours=1)
                )

                metrics = self.exit_manager.analyze_position(
                    position=position,
                    entry_time=entry_time,
                )

                exit_signals = self.exit_manager.check_exit_signals(
                    metrics=metrics,
                    total_equity=equity,
                )

                # 즉시 실행이 필요한 exit 시그널 처리
                for signal in exit_signals:
                    if signal.urgency == "immediate":
                        success = await self._execute_exit(position, signal)
                        if success:
                            exits_executed += 1
                            self._total_exits += 1

                # 포지션 상태 로깅
                status = self.exit_manager.get_position_status(metrics)
                logger.debug(
                    f"Position status: {status['status']}",
                    market_id=position.market_id,
                    pnl_pct=f"{status['pnl_pct']:.1f}%",
                    holding_hours=f"{status['holding_hours']:.1f}h",
                )

            # 리스크 상태 체크
            risk_metrics = self.risk_manager.get_portfolio_metrics()
            if risk_metrics.trading_status.value != "active":
                logger.warning(
                    "Trading suspended",
                    status=risk_metrics.trading_status.value,
                )
                self._last_run = datetime.utcnow()
                return []

            # ============================================
            # Phase 3: 보유 포지션 재분석 (가격 변동 시에만)
            # ============================================
            positions_to_reanalyze = []

            for position in positions:
                last_price = self._last_analyzed_prices.get(position.token_id)
                current_price = position.current_price

                if last_price is not None:
                    price_change_pct = abs((current_price - last_price) / last_price) * 100

                    if price_change_pct >= self.price_change_threshold_pct:
                        positions_to_reanalyze.append(position)
                        logger.info(
                            f"Position requires re-analysis due to price change",
                            market_id=position.market_id,
                            price_change=f"{price_change_pct:.1f}%",
                        )

            # 재분석이 필요한 포지션의 시장 조회 및 분석
            for position in positions_to_reanalyze[:2]:  # 최대 2개만 재분석
                market = await self.polymarket_client.get_market(position.market_id)
                if market:
                    try:
                        decision = await self.orchestrator.analyze_market(
                            market=market,
                            total_equity=equity,
                            available_balance=balance,
                            position_count=len(positions),
                            daily_pnl=risk_metrics.daily_pnl,
                        )

                        self._total_decisions += 1
                        decisions.append(decision)
                        self._last_analyzed_prices[position.token_id] = position.current_price

                        # Decision을 DB에 저장
                        await save_decision_to_db(decision, market)

                        # 포지션 조정이 필요하면 실행
                        if decision.should_trade:
                            await self._execute_decision(market, decision)

                    except Exception as e:
                        logger.error(f"Error re-analyzing position {position.market_id}: {e}")

            # ============================================
            # Phase 4: 신규 시장 탐색 및 진입
            # ============================================
            # 현재 보유 중인 시장 ID 목록
            held_market_ids = {p.market_id for p in positions}

            # 시장 목록 가져오기 (카테고리 필터 없이 - MarketFilter에서 처리)
            markets = await self.polymarket_client.get_markets(
                active_only=True,
                limit=50,
            )

            logger.info(f"Fetched {len(markets)} markets")

            # 시장 필터링 (이미 보유 중인 시장 제외)
            filtered_results = self.market_filter.filter_markets(
                markets, top_n=self.max_markets_per_cycle * 2  # 여유있게 필터링
            )

            # 보유 중인 시장 제외
            new_market_results = [
                r for r in filtered_results
                if r.market.id not in held_market_ids
            ][:self.max_markets_per_cycle]

            if not new_market_results:
                logger.info("No new markets to analyze")
            else:
                logger.info(
                    f"Analyzing {len(new_market_results)} new markets",
                    markets=[r.market.question[:50] for r in new_market_results],
                )

            # 각 신규 시장 분석 및 거래 결정
            for filter_result in new_market_results:
                market = filter_result.market

                try:
                    # Agent 분석
                    decision = await self.orchestrator.analyze_market(
                        market=market,
                        total_equity=equity,
                        available_balance=balance,
                        position_count=len(positions),
                        daily_pnl=risk_metrics.daily_pnl,
                    )

                    self._total_decisions += 1
                    decisions.append(decision)

                    # Decision을 DB에 저장
                    await save_decision_to_db(decision, market)

                    # 거래 실행 (결정이 거래를 권장하는 경우)
                    if decision.should_trade:
                        success = await self._execute_decision(market, decision)
                        if success:
                            # 진입 시간 기록
                            token_id = (
                                market.yes_token_id
                                if decision.side == "YES"
                                else market.no_token_id
                            )
                            if token_id:
                                self._position_entry_times[token_id] = datetime.utcnow()
                                self._last_analyzed_prices[token_id] = market.get_price(
                                    OutcomeSide.YES if decision.side == "YES" else OutcomeSide.NO
                                )

                except Exception as e:
                    logger.error(
                        f"Error analyzing market {market.id}: {e}",
                        exc_info=True,
                    )

            # ============================================
            # Phase 5: 사이클 완료
            # ============================================
            cycle_duration = (datetime.utcnow() - cycle_start).total_seconds()
            total_cost = sum(d.total_cost for d in decisions)

            logger.info(
                f"Cycle #{self._cycle_count} completed",
                duration_seconds=cycle_duration,
                markets_analyzed=len(decisions),
                trades_executed=sum(1 for d in decisions if d.should_trade),
                exits_executed=exits_executed,
                total_cost=f"${total_cost:.4f}",
                current_equity=f"${equity:.2f}",
            )

            self._last_run = datetime.utcnow()

        except Exception as e:
            logger.error(f"Trading cycle failed: {e}", exc_info=True)

        return decisions

    async def _execute_exit(self, position: PositionData, signal: ExitSignal) -> bool:
        """Exit 시그널에 따른 포지션 청산"""
        try:
            # 청산 수량 계산
            exit_size = position.size * signal.exit_size_pct

            # 매도 주문 생성
            order = Order(
                market_id=position.market_id,
                token_id=position.token_id,
                side=Side.SELL,
                outcome_side=position.outcome_side,
                price=signal.recommended_price or position.current_price,
                size=exit_size,
            )

            result = await self.polymarket_client.place_order(order)

            if result.success:
                logger.info(
                    f"Exit executed: {signal.reason.value}",
                    market_id=position.market_id,
                    exit_size=exit_size,
                    exit_pct=f"{signal.exit_size_pct * 100:.0f}%",
                    price=result.average_price,
                )

                # 전량 청산이면 추적 데이터 정리
                if signal.exit_size_pct >= 1.0:
                    self.exit_manager.reset_position_tracking(position.token_id)
                    self._position_entry_times.pop(position.token_id, None)
                    self._last_analyzed_prices.pop(position.token_id, None)
                elif signal.reason == ExitReason.TAKE_PROFIT:
                    # 부분 익절 기록
                    self.exit_manager.record_partial_exit(position.token_id)

                self._total_trades += 1
                return True
            else:
                logger.error(f"Exit failed: {result.error_message}")
                return False

        except Exception as e:
            logger.error(f"Exit execution error: {e}")
            return False

    async def _execute_decision(
        self, market: MarketData, decision: TradingDecision
    ) -> bool:
        """거래 결정 실행"""
        if not decision.should_trade:
            return False

        # 리스크 체크
        risk_check = self.risk_manager.check_trade(
            proposed_size=decision.position_size_usd,
            market_id=market.id,
        )

        if not risk_check.can_trade:
            logger.warning(
                f"Trade rejected by risk manager: {risk_check.reason}",
                market_id=market.id,
            )
            return False

        # 주문 생성
        outcome_side = OutcomeSide.YES if decision.side == "YES" else OutcomeSide.NO
        token_id = (
            market.yes_token_id if outcome_side == OutcomeSide.YES else market.no_token_id
        )

        if not token_id:
            logger.error(f"No token ID for {outcome_side.value} in market {market.id}")
            return False

        price = decision.limit_price or market.get_price(outcome_side)
        size = risk_check.approved_size / price  # 주식 수 계산

        order = Order(
            market_id=market.id,
            token_id=token_id,
            side=Side.BUY if decision.action == "BUY" else Side.SELL,
            outcome_side=outcome_side,
            price=price,
            size=size,
        )

        # 주문 실행
        result = await self.polymarket_client.place_order(order)

        if result.success:
            self._total_trades += 1
            logger.info(
                "Trade executed",
                market_id=market.id,
                decision=decision.decision,
                size=f"${risk_check.approved_size:.2f}",
                price=price,
                order_id=result.order_id,
            )
            return True
        else:
            logger.error(
                f"Trade execution failed: {result.error_message}",
                market_id=market.id,
            )
            return False

    async def run(self):
        """
        트레이딩 루프 실행 (무한 루프)
        """
        self._running = True
        logger.info("Trading loop started")

        while self._running:
            try:
                await self.run_once()

                # 다음 사이클까지 대기
                await asyncio.sleep(self.interval_minutes * 60)

            except asyncio.CancelledError:
                logger.info("Trading loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in trading loop: {e}", exc_info=True)
                # 에러 후 짧은 대기
                await asyncio.sleep(60)

        logger.info("Trading loop stopped")

    def stop(self):
        """트레이딩 루프 중지"""
        self._running = False
        logger.info("Trading loop stop requested")

    def get_status(self) -> dict:
        """현재 상태 반환"""
        return {
            "running": self._running,
            "demo_mode": self.demo_mode,
            "cycle_count": self._cycle_count,
            "total_decisions": self._total_decisions,
            "total_trades": self._total_trades,
            "total_exits": self._total_exits,
            "last_run": self._last_run.isoformat() if self._last_run else None,
            "interval_minutes": self.interval_minutes,
            "risk_metrics": (
                self.risk_manager.get_portfolio_metrics().__dict__
                if self._cycle_count > 0
                else None
            ),
            "agent_stats": self.orchestrator.get_agent_stats(),
        }

    async def close(self):
        """리소스 정리"""
        self.stop()
        await self.polymarket_client.close()
