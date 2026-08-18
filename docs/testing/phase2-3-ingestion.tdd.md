# TDD Evidence: Phase 2-3 — Binance 수집 파이프라인 (ingestion)

- Source plan: 8-phase 구현 계획 Phase 2, 3. 스펙 §4 (수집 파이프라인)
- Scope: `app/ingestion/binance_rest.py`, `backfill.py`, `binance_ws.py`,
  `trade_buffer.py`, `pipeline.py`, `app/api/eventbus.py`

## User journey (from the plan/spec)

> 서버 최초 실행 시 과거 시세가 없어도, 그리고 서버가 다운되었다가
> 재시작되어도, 같은 백필 로직으로 candles_1m의 누락 구간이 채워져야
> 한다. 실시간 체결/캔들은 대시보드에 지연 없이 반영되고, 연결이
> 끊겼다 붙어도 유실된 구간이 자동으로 메워져야 한다.

## Task report

| Task | 검증 명령 | RED | GREEN |
|---|---|---|---|
| fetch_klines(페이지네이션/재시도/파싱) | `pytest tests/test_binance_rest.py -v` | `ModuleNotFoundError` | `6 passed` |
| BackfillService.sync(콜드스타트/갭필/노갭) | `pytest tests/test_backfill.py -v` | `ModuleNotFoundError` | `4 passed` |
| EventBus | `pytest tests/test_eventbus.py -v` | (구현과 함께 작성, 아래 참고) | `5 passed` |
| TradeBuffer(개수/시간 flush 정책) | `pytest tests/test_trade_buffer.py -v` | 〃 | `6 passed` |
| BinanceWebSocketClient(파싱/백오프/재연결) | `pytest tests/test_binance_ws.py -v` | 〃 | `6 passed` |
| IngestionPipeline(오케스트레이션) | `pytest tests/test_pipeline.py -v` | `ModuleNotFoundError` | `6 passed` |

EventBus/TradeBuffer/BinanceWebSocketClient 세 모듈은 인터페이스가
이미 설계 문서에 확정되어 있어 테스트와 구현을 한 커밋에 같이
작성했다(별도 RED 캡처 없음) — 나머지 네 모듈은 표준 RED→GREEN
커밋 쌍으로 남겼다.

## 발견/수정한 버그

1. **kline fixture epoch-ms 오타** — 테스트에 하드코딩한 ms 리터럴이
   실제로는 의도한 날짜보다 1년 전을 가리켜 `is_closed` 판정이 항상
   `True`로 나왔다. datetime 객체에서 ms를 계산하는 헬퍼로 바꿔
   재발을 막았다(`test_binance_rest.py`).
2. **재연결 시 갭필 중복 방지** — `IngestionPipeline`은 `run()`의
   `initial_backfill`이 최초 연결을 이미 커버하므로, `handle_connected`는
   `_connected_once` 플래그로 첫 연결과 재연결을 구분해 재연결에서만
   `BackfillService.sync`를 재호출한다(`test_handle_connected_first_time_does_not_trigger_resync`
   /`test_handle_connected_after_reconnect_triggers_resync`로 고정).

## Coverage

```
$ docker compose run --rm test pytest --cov=app --cov-report=term-missing
app/api/eventbus.py                14      0   100%
app/ingestion/backfill.py          24      0   100%
app/ingestion/binance_rest.py      46      1    98%
app/ingestion/binance_ws.py        73      7    90%   (재시도 로깅 등 부수 경로)
app/ingestion/pipeline.py          72     11    85%   (run()/flush_all 등은 Phase 8 실통합 검증으로 커버)
app/ingestion/trade_buffer.py      22      0   100%
49 passed in 13.89s
```

`IngestionPipeline.run()`(WS 무한루프 진입점)과 `flush_all()`(유휴 구간
주기 flush)은 실제 WS 연결이 필요해 단위 테스트로 커버하지 않았다 —
Phase 8에서 `docker compose up`으로 실제 Binance에 연결해 데이터가
들어오는지, 재시작 후 갭이 메워지는지 수동으로 검증한다.
