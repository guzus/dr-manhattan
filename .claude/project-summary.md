# Prediction Market Trading Bot - Project Summary

## Overview
Polymarket 예측 시장을 위한 LLM Agent 기반 자동 거래 봇 시스템.
Alpha Arena (nof1.ai) 프로젝트를 참고하여 구축됨.

## Quick Start
```bash
# Backend (port 8000)
source venv/bin/activate
python -m uvicorn dashboard.backend.main:app --reload --port 8000

# Frontend (port 3001)
cd dashboard/frontend && npm run dev
```

## Architecture
```
src/
├── agents/           # 6개 LLM Agent (research, probability, sentiment, risk, execution, arbiter)
├── core/
│   ├── polymarket/   # API 클라이언트 (client.py, demo_client.py)
│   └── llm/          # OpenAI 프로바이더
├── strategies/       # Kelly Criterion, Edge-based 사이징
├── risk/             # 리스크 관리 (일일/주간 손실 한도)
└── scheduler/        # TradingLoop

dashboard/
├── backend/          # FastAPI (main.py)
└── frontend/         # Next.js + TailwindCSS + Lightweight Charts
```

## Key Config
- **LLM**: GPT-4o-mini (~$10-15/month)
- **Mode**: Demo (시뮬레이션)
- **Initial Balance**: $1,000
- **Interval**: 15분
- **Categories**: Politics, Sports, Crypto, Entertainment

## API Endpoints
| Endpoint | Description |
|----------|-------------|
| GET `/api/status` | 봇 상태 |
| GET `/api/portfolio` | 포트폴리오 |
| GET `/api/positions` | 포지션 |
| GET `/api/trades` | 거래 내역 |
| GET `/api/markets` | 시장 목록 |
| GET `/api/agents` | Agent 통계 |
| POST `/api/start` | 자동 트레이딩 시작 |
| POST `/api/stop` | 중지 |
| POST `/api/run-cycle` | 단일 사이클 실행 |

## Polymarket API
- Events: `https://gamma-api.polymarket.com/events?active=true&closed=false`
- CLOB: `https://clob.polymarket.com`
- Category Mapping: Sports, US-current-affairs→politics, Crypto, Pop-Culture→entertainment
- **중요**: `closed=false` 파라미터 필수 (종료되지 않은 이벤트만)

## UI Updates (Latest - Alpha Arena Style)
1. 흰색 배경 기반 UI (Alpha Arena 스타일)
2. Lightweight Charts 라이브러리 사용 (TradingView 차트)
3. Live/History 탭 구조
4. 좌측 70% 차트 + 우측 30% AI Decisions 패널
5. 하단 Open Positions 테이블
6. Polymarket 링크 연동 (각 포지션/거래에서 바로 이동)

## Frontend Components
- `Header.tsx` - 상단 (Portfolio Stats, Start/Stop, Run Cycle, Demo Badge)
- `PerformanceChart.tsx` - Lightweight Charts 기반 Equity 곡선 (1D/1W/1M/ALL)
- `DecisionsPanel.tsx` - AI Agent 분석/결정 패널
- `PositionsTable.tsx` - Open Positions (Market, Position, Entry/Current Price, P&L)
- `TradesTable.tsx` - Trade History

## Environment (.env)
```
OPENAI_API_KEY=sk-...
TRADING_MODE=demo
DEMO_INITIAL_BALANCE=1000.0
EXECUTION_INTERVAL_MINUTES=15
```

## Market Price Fix
- `outcomePrices` 필드를 우선 파싱 (JSON 문자열)
- `closed=false` 파라미터로 활성 이벤트만 조회
- `tokens` 배열은 fallback으로 사용

## 중요: Polymarket Event vs Market 구조

### 데이터 모델
```
Event (이벤트)
├── id: 이벤트 ID
├── title: 이벤트 제목 (예: "Which CEOs will be gone in 2025?")
├── category: 카테고리 (Event 레벨에만 존재!)
└── markets: []  # 하위 마켓들
    ├── Market 1
    │   ├── id: 마켓 ID
    │   ├── question: 베팅 질문 (예: "Tim Cook out as Apple CEO in 2025?")
    │   ├── conditionId: 조건 ID
    │   ├── clobTokenIds: [YES토큰ID, NO토큰ID]
    │   └── outcomePrices: ["0.0185", "0.9815"]
    └── Market 2
        └── ...
```

### 핵심 포인트
1. **카테고리 정보**는 Event에만 있음 → Market에 전달 필요
2. `/events` API에서 Event 조회 후 내부 markets 파싱
3. 개별 Market 조회는 `/markets/{id}` 엔드포인트 사용
4. 카테고리가 None인 Market은 필터에서 통과 처리 (많은 마켓이 카테고리 없음)

### 카테고리 매핑 (client.py)
```python
CATEGORY_MAPPING = {
    "sports": ["Sports", "NBA Playoffs", "Olympics", "Chess", "Poker"],
    "politics": ["US-current-affairs", "Global Politics", "Ukraine & Russia"],
    "crypto": ["Crypto", "NFTs"],
    "entertainment": ["Pop-Culture", "Art"],
    "science": ["Science", "Coronavirus"],
    "business": ["Business"],
}
```

### 주의사항 (실거래 전환 시)
- Position 데이터에 market_id만 저장되어 있음
- 화면 표시 시 market_id로 Market 정보 조회 → question(이름) 획득 필요
- Event title도 필요하면 `/events` API에서 조회해야 함

## 타임존 처리
- 백엔드: 모든 시간은 **UTC**로 저장/반환
- 프론트엔드: API에서 받은 시간에 'Z' suffix를 추가하여 UTC로 파싱
  ```typescript
  const lastRunStr = status.last_run.endsWith('Z') ? status.last_run : status.last_run + 'Z';
  ```

## Recent Updates (v2.0)

### SQLite 영속화 (완료)
- `PersistentDemoClient`: SQLite 기반 데모 클라이언트
- 서버 재시작 후에도 포지션, 거래 내역, 잔고 유지
- 데이터 위치: `data/trading.db`
- `use_persistent_client=True` 옵션으로 활성화

### WebSocket 실시간 업데이트 (완료)
- `/ws` 엔드포인트 추가
- 토픽별 구독: portfolio, positions, trades, decisions, status, equity, all
- 5초마다 equity 스냅샷 자동 기록 및 브로드캐스트
- 프론트엔드 `TradingWebSocket` 클래스 및 `useWebSocket` 훅

### Event/Submarket 구조 지원 (완료)
- `Event` 모델 추가 (상위 컨테이너)
- `Market`에 `event_id`, `event_title` 필드 추가
- `/api/events` 엔드포인트로 이벤트별 그룹핑 조회
- API 응답에서 event 정보 자동 파싱

### 데이터베이스 스키마
```python
Event (새로 추가)
├── id, title, category, liquidity, volume
└── markets: List[Market]

Market (업데이트)
├── event_id: Optional[str]  # Event FK
├── event_title: Optional[str]
└── ...기존 필드들

Position (업데이트)
├── token_id: str  # 추가
├── market_id: str (FK 제거, 유연성)
└── agent_id: Optional

Trade (업데이트)
├── trade_id: str  # External ID
├── token_id: str
└── market_id: str (FK 제거)
```

## TODO
- [ ] 실거래 연동 (py-clob-client)
- [ ] PostgreSQL DB 연결 (프로덕션용)
- [x] WebSocket 실시간 업데이트
- [ ] MetaMask 인증
- [ ] 다중 LLM 경쟁 기능 (여러 LLM 모델 비교)
- [x] Event/Submarket 구조 지원
- [x] SQLite 로컬 영속화
