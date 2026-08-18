# Binance 실시간 거래 데이터 수집 및 운영 대시보드 — 설계 문서

- 작성일: 2026-08-18
- 상태: 승인됨 (구현 계획 단계로 진행)

## 1. 목표 및 요구사항

**Part 1 — 데이터 수집 파이프라인**
- BTCUSDT, ETHUSDT 두 종목의 실시간 거래 데이터를 Binance API로 수집한다.
- 최초 실행 시(과거 시세 없음) 과거 데이터를 백필한다.
- 서버 다운 후 재시작 시 누락 구간을 백필한다.
- 위 두 기능은 반드시 분리 구현할 필요 없음 (동일 로직 재사용 가능).

**Part 2 — 운영 대시보드**
- 수집한 데이터를 기반으로 실시간 확인 가능한 대시보드를 제공한다.
- 지표는 자유롭게 정의하되, 선택 이유와 근거를 문서로 남긴다 (`METRICS.md`).
- 투자 판단 또는 운영 현황 파악에 도움이 되는 지표로 구성한다.
- 표시 방식(그래프/카드/테이블)은 자유.

**평가 관점**: 완성도뿐 아니라 문제 접근 방식, 구조 설계, 안정성, 확장성에 대한 고민, AI 활용 방식.

## 2. 아키텍처

단일 FastAPI 프로세스(`app`)가 asyncio 백그라운드 태스크로 Binance WebSocket을 수집하면서, 같은 프로세스가 REST API + WebSocket으로 대시보드에 데이터를 서빙하는 모놀리스 구조. 코드는 책임별로 모듈을 분리해, 필요 시 수집/서빙 프로세스를 나누는 확장이 쉽도록 한다.

```
docker-compose.yml
├── db    (timescale/timescaledb) — 영속 볼륨
└── app   (FastAPI, uvicorn)
    ├── ingestion/   Binance WS 클라이언트, 재연결, BackfillService
    ├── storage/     DB 모델(SQLAlchemy) + 리포지토리(upsert 등)
    ├── api/         REST 라우터 + WS 라우터 + EventBus
    └── frontend/    React+Vite 빌드 결과물(정적 서빙)
```

**확장 경로 (문서화, 현재 범위 밖)**: 트래픽/종목 수가 커지면 `ingestion`을 별도 워커 프로세스로 분리하고 Postgres LISTEN/NOTIFY 또는 Redis pub/sub로 `api` 프로세스와 연결한다. 모듈 경계가 이미 명확하므로 코드 변경 없이 배포 토폴로지만 바뀐다.

## 3. 데이터 모델 (PostgreSQL + TimescaleDB)

```sql
-- 체결 틱 데이터 (hypertable, time 기준 파티셔닝)
trades (
  time            timestamptz NOT NULL,
  symbol          text NOT NULL,
  trade_id        bigint NOT NULL,
  price           numeric NOT NULL,
  qty             numeric NOT NULL,
  quote_qty       numeric NOT NULL,
  is_buyer_maker  boolean NOT NULL,
  UNIQUE (symbol, trade_id)
)

-- 1분봉 OHLCV (hypertable), Binance kline_1m 이벤트를 그대로 upsert
candles_1m (
  symbol      text NOT NULL,
  open_time   timestamptz NOT NULL,
  close_time  timestamptz NOT NULL,
  open, high, low, close  numeric NOT NULL,
  volume        numeric NOT NULL,
  quote_volume  numeric NOT NULL,
  trade_count   integer NOT NULL,
  is_closed     boolean NOT NULL,
  PRIMARY KEY (symbol, open_time)
)

-- 파이프라인 헬스 상태 (symbol당 1행, 계속 upsert)
pipeline_status (
  symbol              text PRIMARY KEY,
  ws_connected        boolean NOT NULL,
  last_trade_at       timestamptz,
  last_backfill_at    timestamptz,
  backfill_covered_from timestamptz,
  reconnect_count     integer NOT NULL DEFAULT 0,
  error_count         integer NOT NULL DEFAULT 0,
  updated_at          timestamptz NOT NULL
)
```

`candles_1m`은 직접 트레이드를 집계하지 않고 Binance가 보내주는 `kline_1m` 이벤트(진행 중 캔들 포함)를 그대로 upsert한다. 집계 로직을 자체 구현하는 것보다 단순하고 Binance 서버와의 정합성이 보장된다.

## 4. 수집 파이프라인

### 4.1 백필 + 갭필 (단일 로직)

`BackfillService.sync(symbol)`:
1. `candles_1m`에서 해당 symbol의 최신 `open_time` 조회.
2. 없으면 `start = now - BACKFILL_HOURS` (환경변수, 기본 24h), 있으면 `start = 최신 open_time`.
3. `end = now` (분 단위 내림).
4. `start < end`이면 Binance REST `GET /api/v3/klines`를 1000개 단위로 페이지네이션 호출하여 `candles_1m`에 upsert (`is_closed=true`, 진행 중인 마지막 봉만 `false`).

이 함수가 다음 두 경우에 모두 쓰인다:
- **최초 실행**: 프로세스 시작 시 각 symbol에 대해 1회 실행 → 과거 데이터가 없는 상태에서 `BACKFILL_HOURS`만큼 채움.
- **재시작 후 갭**: 동일하게 시작 시 실행되며, 이미 데이터가 있으므로 자연히 "마지막 저장 시각 ~ 지금"만 채워짐(갭필).
- **런타임 중 WS 재연결 시**도 동일 함수를 재호출해 재연결 사이 유실 구간을 메꾼다.

### 4.2 실시간 스트림

- Binance combined stream 구독: `{symbol}@trade`, `{symbol}@kline_1m` (전 symbol 통합).
- `trade` 이벤트: 큐에 버퍼링 후 배치(개수 또는 500ms 주기)로 `trades` upsert. 동시에 최신가를 즉시 EventBus로 브로드캐스트(DB 반영 이전에 대시보드로 전달해 지연 최소화).
- `kline_1m` 이벤트: `candles_1m` upsert 후 EventBus 브로드캐스트.
- 연결 끊김: 지수 백오프(1s → 최대 30s)로 재연결. 재연결 성공 시 `BackfillService.sync` 재실행 + `pipeline_status.reconnect_count` 증가.
- `pipeline_status`는 주기적으로(예: 1s throttle) 갱신.

## 5. API

- `GET /api/candles?symbol=&limit=` — 차트 초기 로딩용 캔들 이력
- `GET /api/stats?symbol=` — 24h 변동률/고가/저가/거래량 (candles_1m 기반 계산)
- `GET /api/health` — 전 symbol의 `pipeline_status`
- `WS /ws/live` — trade/candle/status 이벤트를 실시간 push (프로세스 내 asyncio EventBus로 팬아웃)

## 6. 대시보드 지표 및 근거

`METRICS.md`에 상세 근거를 남기되, 설계 단계 요약은 다음과 같다.

**투자 판단용**
| 지표 | 근거 |
|---|---|
| 실시간가 + 1분봉 캔들차트 | 가격 추이·변동성 파악의 기본 단위 |
| 24h 변동률(%), 24h 고가/저가 | 단기 모멘텀·변동성 판단 |
| 24h 거래량(quote volume) | 유동성/시장 관심도 |
| 매수/매도 체결 비율 (`is_buyer_maker` 기반) | 매수·매도 압력(시장 심리) 파악 |

**운영 모니터링용**
| 지표 | 근거 |
|---|---|
| WS 연결 상태 + 마지막 수신 후 경과시간 | 데이터 신선도 및 장애 즉시 감지 |
| 재연결 횟수 / 에러 카운트 | 파이프라인 안정성 추이, 이상 징후 조기 발견 |
| 마지막 백필 시각 / 커버 범위 | 데이터 완전성(누락 없음) 확인 |

표시: 상단 통계 카드(가격/변동률/거래량 등) + 캔들 차트(lightweight-charts) + 파이프라인 헬스 패널(연결 배지, 지연시간, 에러카운트).

## 7. 안정성 / 에러 처리

- 모든 DB 쓰기는 `ON CONFLICT` upsert → 재시도·재생 시에도 멱등.
- Binance REST 429/418 응답 시 `Retry-After` 존중하며 backoff 재시도.
- WS 연결 루프는 예외를 잡아 프로세스를 죽이지 않고 재연결.
- Binance 완전 단절 시에도 대시보드는 DB의 마지막 값 + "stale" 상태 배지로 계속 응답 (빈 화면/에러 페이지 방지).

## 8. 테스트 전략

- Unit: `BackfillService`의 갭 계산, kline 파싱, 재연결 백오프 계산 — Binance REST/WS는 mock.
- Integration: 레코딩된 WS 메시지 fixture로 trades/candles 저장 및 upsert 정합성 검증.
- 실 Binance망에 의존하는 E2E는 CI에서 제외(레이트리밋/불안정성 방지).

## 9. 배포

`docker-compose.yml`:
- `db`: `timescale/timescaledb:latest-pg16`, named volume으로 영속화.
- `app`: 멀티스테이지 Dockerfile (프론트 빌드 → Python 이미지에 정적 파일 포함), entrypoint에서 `alembic upgrade head` 후 `uvicorn` 기동.

환경변수: `SYMBOLS`(기본 `BTCUSDT,ETHUSDT`), `BACKFILL_HOURS`(기본 24), `BINANCE_WS_URL`, `BINANCE_REST_URL`, `DATABASE_URL`.

실행: `docker compose up --build` 한 번으로 db+app 기동, 대시보드는 `http://localhost:8000`.

## 10. 기술 스택 요약

- Backend: Python 3.12, FastAPI, asyncio, `websockets`, `httpx`, SQLAlchemy 2.0 (async) + Alembic, asyncpg
- Storage: PostgreSQL + TimescaleDB extension
- Frontend: React + TypeScript (Vite), `lightweight-charts`, native WebSocket
- Infra: Docker Compose (2 서비스: db, app)
