# TDD Evidence: Phase 1 — 저장 계층 (storage)

- Source plan: 사용자 승인된 8-phase 구현 계획 (Phase 1), 기반 스펙
  `docs/superpowers/specs/2026-08-18-binance-realtime-dashboard-design.md` §3, §7
- Scope: `app/storage/models.py`, `app/storage/repository.py`,
  `alembic/versions/0001_initial_schema.py`

## User journey (from the plan)

> 저장 계층의 upsert가 멱등적이어서, 파이프라인이 같은 trade/candle을
> 재시도·재생해도 중복 행이나 예외 없이 안전해야 한다. pipeline_status는
> 운영 대시보드 헬스 패널의 근거가 되므로 연결 상태·재연결/에러
> 카운트·백필 커버리지를 정확히 반영해야 한다.

## Task report

1. **repository 계약 명세** — `upsert_trades`/`upsert_candle`/조회/
   `pipeline_status` 함수 11종의 기대 동작을 16개 테스트로 먼저 작성.
   - 검증 명령: `docker compose run --rm test pytest -v`
   - 결과(RED): `ModuleNotFoundError: No module named 'app.storage.models'`
2. **모델/리포지토리 구현** — SQLAlchemy 2.0 모델(트레이드는 불변이라
   `ON CONFLICT DO NOTHING`, 캔들/상태는 계속 갱신되므로
   `ON CONFLICT DO UPDATE`) + Alembic 초기 마이그레이션(하이퍼테이블).
   - 검증 명령: `docker compose run --rm test pytest -v`
   - 결과(GREEN): `16 passed in 0.76s`
   - 추가 검증: `docker compose run --rm test alembic upgrade head` →
     `timescaledb_information.hypertables`에 `trades`, `candles_1m` 확인
3. **버그 수정 2건 (GREEN 도달 과정에서 발견)**
   - `conftest.py`의 세션 스코프 엔진이 pytest-asyncio의 함수별 이벤트
     루프와 충돌(`attached to a different loop`) → 테스트마다 새 엔진
     생성하는 방식으로 변경.
   - 모델의 datetime 컬럼이 기본적으로 tz-naive `TIMESTAMP`로 매핑되어
     tz-aware 값 삽입 시 `DataError` 발생 → 전 컬럼에
     `DateTime(timezone=True)` 명시.

## Test specification

| # | 보장하는 동작 | 테스트 | 종류 | 결과 |
|---|---|---|---|---|
| 1 | 신규 trade 배치 삽입 | `test_inserts_new_trades` | integration | PASS |
| 2 | 동일 trade_id 재삽입은 에러 없이 무시(멱등) | `test_duplicate_trade_id_is_ignored_without_error` | integration | PASS |
| 3 | 빈 배치는 no-op | `test_empty_batch_is_a_noop` | integration | PASS |
| 4 | 캔들 upsert가 기존 open_time 행을 갱신 | `test_insert_then_update_same_open_time` | integration | PASS |
| 5 | 같은 open_time이라도 심볼이 다르면 별도 행 | `test_different_symbols_do_not_collide` | integration | PASS |
| 6 | 데이터 없으면 최신 캔들 시각 None | `test_returns_none_when_empty` | integration | PASS |
| 7 | 최신 캔들 시각이 심볼별 최댓값 | `test_returns_max_open_time_for_symbol` | integration | PASS |
| 8 | 캔들 조회가 시간순 정렬 + limit 적용 | `test_orders_chronologically_and_respects_limit` | integration | PASS |
| 9 | pipeline_status 최초 행 기본값 | `test_ensure_row_creates_default` | integration | PASS |
| 10 | pipeline_status ensure는 멱등 | `test_ensure_row_is_idempotent` | integration | PASS |
| 11 | 연결 상태 갱신 시 updated_at 갱신 | `test_set_ws_connected_updates_flag_and_timestamp` | integration | PASS |
| 12 | trade 수신 시 last_trade_at 갱신 | `test_record_trade_received_updates_last_trade_at` | integration | PASS |
| 13 | 재연결 카운트 누적 | `test_record_reconnect_increments_count` | integration | PASS |
| 14 | 에러 카운트 누적 | `test_record_error_increments_count` | integration | PASS |
| 15 | 백필 커버리지 필드 갱신 | `test_record_backfill_updates_coverage_fields` | integration | PASS |
| 16 | 전 심볼 상태 조회 | `test_get_all_pipeline_status_returns_every_symbol` | integration | PASS |

모든 테스트는 실제 TimescaleDB(binance_test DB, Docker `test` 서비스)를 대상으로
실행되는 integration test — ON CONFLICT/hypertable 관련 동작은 Postgres
방언에 의존하므로 SQLite 등으로 대체하지 않았다.

## Coverage and known gaps

```
$ docker compose run --rm test pytest --cov=app --cov-report=term-missing
app/storage/models.py          38      0   100%
app/storage/repository.py      52      0   100%
app/config.py                  20     20     0%   (Phase 3/4에서 ingestion·API가 사용하며 커버됨)
app/storage/db.py               8      8     0%   (Phase 4 API 테스트에서 get_session 사용 시 커버됨)
TOTAL                         118     28    76%
```

이번 phase의 대상인 `models.py`/`repository.py`는 100% 커버리지. `config.py`,
`db.py`는 단순 배선 코드로 이번 phase 테스트가 직접 호출하지 않아 0%로
잡히지만, 별도 테스트를 추가하기보다 이후 phase(ingestion의 Settings 사용,
API의 get_session 의존성 주입)에서 실사용 경로로 커버할 계획이다.
