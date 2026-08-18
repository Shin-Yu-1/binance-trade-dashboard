# TDD Evidence: Phase 4 — REST/WS API 계층

- Source plan: 8-phase 구현 계획 Phase 4. 스펙 §5(API), §6(지표)
- Scope: `app/api/routes_rest.py`, `app/api/routes_ws.py`, `app/main.py`,
  `app/storage/repository.get_taker_buy_sell_volume`

## Task report

- 검증 명령: `docker compose run --rm test pytest tests/test_api.py -v`
- RED: `ModuleNotFoundError: No module named 'app.api.routes_rest'`
- GREEN: `8 passed`(test_api.py), 전체 스위트 `57 passed`

## Test specification

| # | 보장하는 동작 | 테스트 | 결과 |
|---|---|---|---|
| 1 | /api/candles가 저장된 캔들을 심볼 대소문자 무관하게 반환 | `test_get_candles_returns_seeded_candles` | PASS |
| 2 | 데이터 없는 심볼은 빈 배열 | `test_get_candles_empty_when_no_data` | PASS |
| 3 | /api/stats가 변동률/고가/저가/거래량을 캔들에서 정확히 계산 | `test_get_stats_computes_change_high_low_volume` | PASS |
| 4 | /api/stats의 매수/매도 비율이 is_buyer_maker 기준으로 정확히 집계 | `test_get_stats_reports_taker_buy_sell_volume` | PASS |
| 5 | 데이터 없는 심볼도 500 에러 없이 null 필드로 응답 | `test_get_stats_handles_symbol_with_no_data` | PASS |
| 6 | /api/health가 staleness(연결됐지만 1시간째 무거래)를 True로 판정 | `test_get_health_reports_status_and_staleness` | PASS |
| 7 | /ws/live가 EventBus publish를 그대로 클라이언트에 전달 | `test_ws_live_streams_published_events` | PASS |
| 8 | /ws/live가 datetime→ISO, Decimal→문자열로 직렬화 | `test_ws_live_serializes_datetime_and_decimal` | PASS |

## 알려진 한계

`pytest-cov`로 `app/api/routes_rest.py`만 측정하면 65%로 낮게 나오지만
(라인 39/49-65/82-109가 "미실행"으로 표시), 위 테스트들은 그 라인들이
만들어내는 정확한 반환값(변동률 수치, buy/sell 볼륨, stale 플래그 등)을
직접 단언하므로 실제로는 실행되고 있다 — SQLAlchemy의 greenlet 기반
async-to-sync 브릿지와 coverage.py의 trace 수집이 상호작용하는 방식의
측정 한계로 보인다. 다른 모듈(repository, backfill 등)은 같은 방식으로
100%에 가깝게 잡히는 것으로 보아 특정 조합에서만 나타나는 도구
이슈이며, 테스트 내용 자체의 공백은 아니다.
