# Binance 실시간 거래 데이터 수집 & 운영 대시보드

Binance의 BTCUSDT, ETHUSDT 체결 데이터를 실시간으로 수집·저장하고, 수집 파이프라인의
건강 상태와 시세 지표를 실시간으로 확인할 수 있는 운영 대시보드입니다.

## 목차

- [주요 기능](#주요-기능)
- [아키텍처](#아키텍처)
- [기술 스택](#기술-스택)
- [실행 방법](#실행-방법)
- [환경 변수](#환경-변수)
- [API](#api)
- [대시보드 지표와 선정 근거](#대시보드-지표와-선정-근거)
- [안정성 설계](#안정성-설계)
- [테스트](#테스트)
- [프로젝트 구조](#프로젝트-구조)

## 주요 기능

### Part 1. 데이터 수집 파이프라인

- **실시간 수집**: Binance combined WebSocket 스트림(`{symbol}@trade`, `{symbol}@kline_1m`)을
  구독해 BTCUSDT/ETHUSDT의 체결(trade)과 1분봉(kline)을 수집합니다.
- **백필 + 갭필 (단일 로직)**: `BackfillService.sync(symbol)` 하나가 두 시나리오를 모두 처리합니다.
  - **최초 실행**: `candles_1m`에 데이터가 없으면 `BACKFILL_HOURS`(기본 24시간) 만큼 Binance REST
    `GET /api/v3/klines`를 페이지네이션 호출해 과거 1분봉을 채웁니다.
  - **재시작/재연결 후 갭필**: 이미 데이터가 있으면 "저장된 마지막 open_time ~ 지금"만 계산해
    그 구간만 다시 채웁니다. 서버 다운 후 재시작뿐 아니라 WebSocket 재연결 시에도 동일 함수가
    재호출되어, 끊긴 동안의 누락 구간을 자동으로 메웁니다.
- **재연결**: WebSocket 연결이 끊기면 지수 백오프(1s → 최대 30s)로 재연결하고, 성공 시 갭필을
  실행하며 `pipeline_status.reconnect_count`를 증가시킵니다.

### Part 2. 운영 대시보드

- 종목별(BTCUSDT/ETHUSDT) 실시간가, 24h 변동률/고가/저가/거래량, 매수·매도 체결 비율을
  숫자 카드로 표시합니다.
- 1분봉 캔들 차트(`lightweight-charts`)로 가격 추이를 시각화합니다.
- 파이프라인 헬스 패널에서 WS 연결 상태, 마지막 체결 수신 후 경과 시간, 재연결/에러 카운트,
  마지막 백필 시각을 확인할 수 있습니다.
- REST로 초기 데이터를 로딩한 뒤 `WS /ws/live` 구독으로 이후 갱신을 실시간 반영합니다.

## 아키텍처

단일 FastAPI 프로세스가 asyncio 백그라운드 태스크로 Binance WebSocket을 수집하는 동시에,
같은 프로세스가 REST API + WebSocket으로 대시보드에 데이터를 서빙하는 모놀리스 구조입니다.
책임별로 모듈을 분리해 두어, 트래픽이 커지면 수집/서빙 프로세스를 분리하기 쉽습니다.

```
docker-compose.yml
├── db    (timescale/timescaledb) — 영속 볼륨
└── app   (FastAPI, uvicorn)
    ├── ingestion/   Binance WS 클라이언트, 재연결, BackfillService, IngestionPipeline
    ├── storage/     DB 모델(SQLAlchemy async) + 리포지토리(upsert 등)
    ├── api/         REST 라우터 + WS 라우터 + EventBus(프로세스 내 팬아웃)
    └── frontend/    React+Vite 빌드 결과물(정적 서빙, / 아래 mount)
```

**확장 경로**: 종목 수·트래픽이 커지면 `ingestion`을 별도 워커 프로세스로 분리하고 Postgres
LISTEN/NOTIFY 또는 Redis pub/sub로 `api` 프로세스와 연결할 수 있습니다. 모듈 경계가 이미
명확하게 분리되어 있어 배포 토폴로지만 바뀌고 코드 변경은 최소화됩니다. 자세한 설계 배경은
[`docs/superpowers/specs/2026-08-18-binance-realtime-dashboard-design.md`](docs/superpowers/specs/2026-08-18-binance-realtime-dashboard-design.md)를 참고하세요.

### 데이터 모델 (PostgreSQL + TimescaleDB)

- `trades`: 체결 틱 데이터 (hypertable, `UNIQUE(symbol, trade_id)`로 멱등 upsert)
- `candles_1m`: Binance `kline_1m` 이벤트를 그대로 upsert한 1분봉 OHLCV (hypertable). 트레이드를
  직접 집계하지 않고 Binance가 계산한 캔들을 그대로 저장해 Binance 서버와의 정합성을 보장합니다.
- `pipeline_status`: symbol당 1행, 연결 상태·마지막 수신 시각·재연결/에러 카운트·백필 커버 범위를
  지속적으로 upsert하는 운영 헬스 테이블

## 기술 스택

| 영역 | 스택 |
|---|---|
| Backend | Python 3.12, FastAPI, asyncio, `websockets`, `httpx`, SQLAlchemy 2.0(async) + Alembic, asyncpg |
| Storage | PostgreSQL + TimescaleDB extension |
| Frontend | React 18 + TypeScript(Vite), `lightweight-charts`, native WebSocket |
| 테스트 | pytest / pytest-asyncio / respx (backend), Vitest + Testing Library (frontend) |
| Infra | Docker Compose (`db`, `app`, 테스트용 `test` 프로필) |

## 실행 방법

### Docker Compose (권장)

```bash
docker compose up --build
```

- `db`(TimescaleDB)가 healthy 상태가 된 뒤 `app`이 기동됩니다.
- `app` 컨테이너 시작 시 `entrypoint.sh`가 `alembic upgrade head`로 마이그레이션을 적용한 뒤
  `uvicorn`을 실행합니다.
- 대시보드: http://localhost:8000 (FastAPI가 프론트엔드 빌드 결과물을 정적으로 서빙합니다)

### 로컬 개발 (백엔드/프론트엔드 분리 실행)

```bash
# 1) DB만 Docker로 띄우기
docker compose up db

# 2) 백엔드
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e .[dev]
cp ../.env.example .env   # 필요 시 DATABASE_URL을 localhost 기준으로 수정
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# 3) 프론트엔드 (별도 터미널)
cd frontend
npm install
npm run dev   # http://localhost:5173, /api·/ws는 vite dev 프록시 또는 8000 포트로 직접 호출
```

## 환경 변수

`.env.example`을 참고해 `.env`를 생성하세요. (Docker Compose 사용 시 `docker-compose.yml`의
`environment`가 우선 적용되므로 별도 설정 없이도 바로 실행됩니다.)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `SYMBOLS` | `BTCUSDT,ETHUSDT` | 수집 대상 심볼 목록(콤마 구분). 프론트엔드는 `/api/config`로 이 값을 읽어 재빌드 없이 종목을 늘릴 수 있습니다. |
| `BACKFILL_HOURS` | `24` | 최초 실행 시 과거 몇 시간을 백필할지 |
| `BINANCE_WS_URL` | `wss://stream.binance.com:9443/stream` | Binance combined WebSocket 엔드포인트 |
| `BINANCE_REST_URL` | `https://api.binance.com` | Binance REST(klines) 엔드포인트 |
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/binance` | PostgreSQL 접속 문자열 |

## API

| Method | Path | 설명 |
|---|---|---|
| GET | `/api/candles?symbol=&limit=` | 차트 초기 로딩용 1분봉 이력 |
| GET | `/api/stats?symbol=` | 24h 변동률/고가/저가/거래량, 매수·매도 체결량 |
| GET | `/api/health` | 전 심볼의 파이프라인 상태(연결 여부, stale 여부, 재연결/에러 카운트 등) |
| GET | `/api/config` | 대시보드가 수집 대상 심볼 목록을 런타임에 조회 |
| WS | `/ws/live` | trade/candle/status 이벤트를 실시간 push (서버 내 EventBus로 팬아웃) |

## 대시보드 지표와 선정 근거

| 구분 | 지표 | 선정 근거 |
|---|---|---|
| 투자 판단 | 실시간가 + 1분봉 캔들 차트 | 가격 추이·변동성 파악의 기본 단위 |
| 투자 판단 | 24h 변동률(%), 24h 고가/저가 | 단기 모멘텀·변동성 판단 |
| 투자 판단 | 24h 거래량(quote volume) | 유동성/시장 관심도 파악 |
| 투자 판단 | 매수/매도 체결 비율 (`is_buyer_maker` 기반) | 매수·매도 압력(시장 심리) 파악 |
| 운영 모니터링 | WS 연결 상태 + 마지막 수신 후 경과 시간 | 데이터 신선도 확인 및 장애 즉시 감지 |
| 운영 모니터링 | 재연결 횟수 / 에러 카운트 | 파이프라인 안정성 추이, 이상 징후 조기 발견 |
| 운영 모니터링 | 마지막 백필 시각 / 커버 범위 | 데이터 완전성(누락 구간 없음) 확인 |

투자 판단용 지표는 "지금 이 종목이 사고팔 만한 상태인가"를, 운영 모니터링용 지표는
"지금 이 수치를 신뢰할 수 있는가"를 답하도록 구성했습니다. 데이터가 멈춘 상태에서 가격만
보여주면 오판을 유발할 수 있어, 두 축을 하나의 화면에 같이 두었습니다.

## 안정성 설계

- 모든 DB 쓰기는 `ON CONFLICT` 기반 upsert → 재시도·재생 시에도 멱등하게 동작합니다.
- WebSocket 수신 루프는 예외를 잡아 프로세스를 죽이지 않고 지수 백오프로 재연결합니다.
- 재연결 성공 시 백필 로직을 재실행해 끊긴 동안의 데이터 갭을 자동으로 메웁니다.
- Binance와 완전히 단절되어도 대시보드는 DB에 저장된 마지막 값과 "연결 끊김/stale" 배지로
  계속 응답합니다(빈 화면·에러 페이지 방지).

## 테스트

```bash
# Backend (pytest, DB 필요 — docker compose up db 로 기동 후 실행)
cd backend && pytest -v

# Docker Compose로 테스트 DB까지 함께 기동해 실행
docker compose --profile test run --rm test

# Frontend (Vitest)
cd frontend && npm test
```

TDD로 진행한 각 단계의 근거는 `docs/testing/`에 phase별로 정리되어 있습니다.

## 프로젝트 구조

```
backend/
  app/
    ingestion/   Binance WS/REST 클라이언트, BackfillService, IngestionPipeline
    storage/     SQLAlchemy 모델, 리포지토리(upsert), DB 세션
    api/         REST/WS 라우터, EventBus
    config.py    환경 변수 기반 설정
  alembic/       DB 마이그레이션
  tests/         pytest 계약/유닛 테스트
frontend/
  src/
    components/  StatCards, CandleChart, HealthPanel
    hooks/       useLiveFeed (WS 구독 + 상태 리듀서)
    lib/         API 클라이언트, 포맷터, 실시간 상태 파생 로직
docs/
  superpowers/specs/   설계 문서
  testing/             단계별 TDD 근거 리포트
docker-compose.yml, Dockerfile   배포 구성
```
