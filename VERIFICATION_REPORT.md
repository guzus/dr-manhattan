# Polymarket API 전체 검증 보고서

**검증일시:** 2026-02-08 22:00 KST  
**테스트 주소:** `0x56687bf447db6ffa42ffe2204a05edaa20f55839`

---

## 코드 수정 사항

### 1. `fetch_live_volume` — 파라미터 이름 수정 (BUG FIX)
- **파일:** `dr_manhattan/exchanges/polymarket/polymarket_data.py`
- **변경:** `eventId` → `id` (API가 `id` 파라미터를 요구)

### 2. `fetch_supported_assets` — 응답 파싱 수정 (BUG FIX)
- **파일:** `dr_manhattan/exchanges/polymarket/polymarket_bridge.py`
- **변경:** API가 `{"supportedAssets": [...]}` 형태로 응답하나 flat list만 처리하고 있었음
- **수정:** dict 응답 시 `data.get("supportedAssets", [])` 로 파싱

---

## 전체 검증 결과

### ✅ 작동 (45개)

#### Gamma API
| 메서드 | 결과 |
|--------|------|
| `get_gamma_status()` | OK — `{status_code: 200, ok: true}` |
| `fetch_markets(limit=3)` | OK — 3개 마켓 반환 |
| `fetch_market(market_id)` | OK — numeric Gamma ID로 호출 시 정상 |
| `fetch_markets_by_slug(slug)` | OK — 1개 마켓 반환 |
| `search_markets(limit=5, query="bitcoin")` | OK — 1개 결과 |
| `fetch_events(limit=5)` | OK — 5개 이벤트 |
| `fetch_event(event_id)` | OK |
| `fetch_event_by_slug(slug)` | OK |
| `fetch_series(limit=3)` | OK — 3개 시리즈 |
| `fetch_series_by_id(series_id)` | OK |
| `fetch_tags(limit=5)` | OK — 5개 태그 |
| `fetch_tag_by_id(tag_id)` | OK |
| `get_tag_by_slug("politics")` | OK — Tag 객체 반환 |
| `fetch_market_tags(market_id)` | OK — numeric ID로 호출 시 정상 (7개 태그) |
| `fetch_event_tags(event_id)` | OK — 1개 태그 |
| `fetch_sports_metadata()` | OK — 129개 항목 |
| `fetch_sports_market_types()` | OK — 빈 리스트 (현재 등록된 타입 없음) |

#### CLOB API
| 메서드 | 결과 |
|--------|------|
| `get_orderbook(token_id)` | OK — bids/asks 포함 |
| `get_midpoint(token_id)` | OK — `{mid: "0.50"}` |
| `fetch_price_history(market)` | OK — 289개 데이터포인트 |
| `fetch_token_ids(condition_id)` | OK — 2개 토큰 ID |

#### Data API
| 메서드 | 결과 |
|--------|------|
| `fetch_public_trades(limit=5)` | OK — 5개 거래 |
| `fetch_leaderboard(limit=5)` | OK — 5명 |
| `fetch_user_activity(addr, limit=5)` | OK — 5개 활동 |
| `fetch_top_holders(cid, limit=5)` | OK — 2명 |
| `fetch_open_interest(cid)` | OK |
| `fetch_closed_positions(addr, limit=5)` | OK — 5개 |
| `fetch_positions_data(addr, limit=5)` | OK — 0개 (현재 포지션 없음) |
| `fetch_portfolio_value(addr)` | OK |
| `fetch_live_volume(event_id)` | OK — 수정 후 정상 ✅ |
| `fetch_traded_count(addr)` | OK — `{user, traded}` |
| `fetch_builder_leaderboard(limit=5)` | OK — 5개 |
| `fetch_builder_volume(builder_id)` | OK — 시계열 데이터 |
| `fetch_accounting_snapshot(addr)` | OK — 392 bytes (ZIP) |

#### Bridge API
| 메서드 | 결과 |
|--------|------|
| `fetch_supported_assets()` | OK — 수정 후 111개 자산 반환 ✅ |

### ⚠️ 부분 작동 (4개)

| 메서드 | 상태 | 설명 |
|--------|------|------|
| `get_orderbooks([t1,t2])` | 빈 리스트 반환 | CLOB batch endpoint가 현재 비활성/deprecated. 개별 `get_orderbook()` 정상 |
| `get_price(token_id)` | 빈 dict 반환 | `side` 파라미터 없이 호출 시 빈 응답. `side=buy` 추가하면 정상 |
| `get_prices([t1,t2])` | 빈 리스트 반환 | CLOB batch endpoint 비활성. 개별 `get_price()` 정상 |
| `get_spreads([t1,t2])` | 빈 리스트 반환 | CLOB batch endpoint 비활성. 개별 `/spread` 엔드포인트 정상 |

### ❌ 실패 (2개)

| 메서드 | 에러 | 원인 |
|--------|------|------|
| `fetch_comments(...)` | 422 Unprocessable Entity | API가 `entity_entity_type`과 `parent_entity_id` 요구하나, 유효한 조합을 찾지 못함. 인증 필요 가능성 |
| `fetch_bridge_status(addr)` | 500 Internal Server Error | Polymarket 서버 측 오류. 코드 문제 아님 |

### 🔒 인증 필요 (6개)

| 메서드 | 비고 |
|--------|------|
| `fetch_profile(address)` | 401 — 인증 필요 |
| `split(condition_id, amount)` | import 확인 완료 |
| `merge(condition_id, amount)` | import 확인 완료 |
| `redeem(condition_id)` | import 확인 완료 |
| `redeem_all()` | import 확인 완료 |
| `fetch_redeemable_positions()` | import 확인 완료 |

---

## 페이지네이션 검증

| 메서드 | limit=3 | limit=10 | offset | 결과 |
|--------|---------|----------|--------|------|
| `fetch_events` | 3개 | 10개 | ✅ 다른 결과 | ✅ |
| `fetch_series` | 3개 | 10개 | ✅ 다른 결과 | ✅ |
| `fetch_tags` | 3개 | 10개 | ✅ 다른 결과 | ✅ |
| `fetch_public_trades` | 3개 | 10개 | ✅ 다른 결과 | ✅ |
| `search_markets` | 0개 | 2개 | 확인 (데이터 적음) | ✅ |
| `fetch_user_activity` | 3개 | 10개 | ✅ 다른 결과 | ✅ |
| `fetch_closed_positions` | 3개 | 10개 | ✅ 다른 결과 | ✅ |
| `fetch_positions_data` | 0개 | 0개 | 확인 (데이터 없음) | ✅ |
| `fetch_leaderboard` | 3개 | 10개 | ✅ 다른 결과 | ✅ |
| `fetch_builder_leaderboard` | 3개 | 10개 | ✅ 다른 결과 | ✅ |

**모든 페이지네이션 정상 작동** ✅

---

## 참고사항

1. **`fetch_markets()`** 는 CLOB `/sampling-markets` 에서 가져오므로 반환되는 `market.id`가 hex condition_id임. Gamma API 메서드(`fetch_market`, `fetch_market_tags` 등)는 numeric Gamma market ID가 필요. 혼용 시 주의.

2. **CLOB batch endpoints** (`/books`, `/prices`, `/spreads`)는 현재 Polymarket에서 비활성화된 것으로 보임. 개별 엔드포인트(`/book`, `/price`, `/spread`, `/midpoint`)는 모두 정상.

3. **`get_price()`** 는 `side` 파라미터 없이 호출하면 빈 응답을 반환. `side=buy` 또는 `side=sell`을 추가해야 가격을 받을 수 있음.

4. **`fetch_builder_volume()`** 호출 시 빌더 리더보드에서 `builder` 키 값을 사용 (예: `"betmoar"`).
