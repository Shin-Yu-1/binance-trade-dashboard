from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.api.eventbus import EventBus
from app.api.routes_rest import router as rest_router
from app.api.routes_ws import router as ws_router
from app.config import get_settings
from app.storage import repository
from app.storage.db import get_session

UTC = timezone.utc


def _build_app(session_factory) -> FastAPI:
    app = FastAPI()
    app.state.event_bus = EventBus()
    app.include_router(rest_router)
    app.include_router(ws_router)

    async def override_get_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    return app


async def _seed_candle(session_factory, **overrides):
    base = {
        "symbol": "BTCUSDT",
        "open_time": datetime(2026, 8, 18, 11, 0, tzinfo=UTC),
        "close_time": datetime(2026, 8, 18, 11, 1, tzinfo=UTC),
        "open": "100",
        "high": "110",
        "low": "90",
        "close": "105",
        "volume": "10",
        "quote_volume": "1000",
        "trade_count": 5,
        "is_closed": True,
    }
    base.update(overrides)
    async with session_factory() as session:
        await repository.upsert_candle(session, base)
        await session.commit()


@pytest.mark.asyncio
async def test_get_candles_returns_seeded_candles(session_factory):
    await _seed_candle(session_factory)

    app = _build_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/candles", params={"symbol": "btcusdt", "limit": 10})

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["symbol"] == "BTCUSDT"
    assert body[0]["close"] == "105"


@pytest.mark.asyncio
async def test_get_candles_empty_when_no_data(session_factory):
    app = _build_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/candles", params={"symbol": "ETHUSDT"})

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_get_stats_computes_change_high_low_volume(session_factory):
    await _seed_candle(
        session_factory,
        open_time=datetime(2026, 8, 18, 11, 0, tzinfo=UTC),
        close_time=datetime(2026, 8, 18, 11, 1, tzinfo=UTC),
        open="100",
        high="120",
        low="95",
        close="110",
        volume="5",
    )
    await _seed_candle(
        session_factory,
        open_time=datetime(2026, 8, 18, 11, 1, tzinfo=UTC),
        close_time=datetime(2026, 8, 18, 11, 2, tzinfo=UTC),
        open="110",
        high="130",
        low="108",
        close="125",
        volume="7",
    )

    app = _build_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/stats", params={"symbol": "BTCUSDT"})

    body = response.json()
    assert body["symbol"] == "BTCUSDT"
    assert body["last_price"] == "125"
    assert body["high"] == "130"
    assert body["low"] == "95"
    assert body["volume"] == "12"
    assert body["change_pct"] == pytest.approx(25.0)


@pytest.mark.asyncio
async def test_get_stats_reports_taker_buy_sell_volume(session_factory):
    # /api/stats는 "지금부터 24h"만 집계하므로 체결 시각도 현재 기준 상대값으로
    # 심는다 (고정 날짜를 쓰면 시간이 지나면서 집계 창을 벗어나 깨진다).
    recent = datetime.now(UTC) - timedelta(minutes=5)
    async with session_factory() as session:
        await repository.upsert_trades(
            session,
            [
                {
                    "time": recent,
                    "symbol": "BTCUSDT",
                    "trade_id": 1,
                    "price": "100",
                    "qty": "2",
                    "quote_qty": "200",
                    "is_buyer_maker": False,
                },
                {
                    "time": recent,
                    "symbol": "BTCUSDT",
                    "trade_id": 2,
                    "price": "100",
                    "qty": "3",
                    "quote_qty": "300",
                    "is_buyer_maker": True,
                },
            ],
        )
        await session.commit()

    app = _build_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/stats", params={"symbol": "BTCUSDT"})

    body = response.json()
    assert body["taker_buy_volume"] == "2"
    assert body["taker_sell_volume"] == "3"


@pytest.mark.asyncio
async def test_get_stats_handles_symbol_with_no_data(session_factory):
    app = _build_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/stats", params={"symbol": "ETHUSDT"})

    body = response.json()
    assert body["last_price"] is None
    assert body["change_pct"] is None


@pytest.mark.asyncio
async def test_get_health_reports_status_and_staleness(session_factory):
    async with session_factory() as session:
        await repository.ensure_pipeline_status_row(session, "BTCUSDT")
        now = datetime.now(UTC)
        await repository.set_ws_connected(session, "BTCUSDT", True, now)
        await repository.record_trade_received(session, "BTCUSDT", now - timedelta(hours=1))
        await session.commit()

    app = _build_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/health")

    body = response.json()
    assert len(body) == 1
    assert body[0]["symbol"] == "BTCUSDT"
    assert body[0]["ws_connected"] is True
    assert body[0]["stale"] is True


def test_ws_live_streams_published_events():
    app = FastAPI()
    app.state.event_bus = EventBus()
    app.include_router(ws_router)

    client = TestClient(app)
    with client.websocket_connect("/ws/live") as websocket:
        app.state.event_bus.publish({"type": "trade", "symbol": "BTCUSDT"})
        message = websocket.receive_json()

    assert message == {"type": "trade", "symbol": "BTCUSDT"}


def test_ws_live_serializes_datetime_and_decimal():
    app = FastAPI()
    app.state.event_bus = EventBus()
    app.include_router(ws_router)

    client = TestClient(app)
    with client.websocket_connect("/ws/live") as websocket:
        app.state.event_bus.publish(
            {
                "type": "kline",
                "record": {
                    "open_time": datetime(2026, 8, 18, 12, 0, tzinfo=UTC),
                    "close": Decimal("100.5"),
                },
            }
        )
        message = websocket.receive_json()

    assert message["record"]["open_time"] == "2026-08-18T12:00:00+00:00"
    assert message["record"]["close"] == "100.5"


@pytest.mark.asyncio
async def test_get_config_exposes_configured_symbols(session_factory):
    """대시보드가 SYMBOLS 환경변수를 프론트 재빌드 없이 따라가게 한다."""
    app = _build_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/config")

    assert response.status_code == 200
    body = response.json()
    assert body["symbols"] == get_settings().symbol_list
    assert body["symbols"]
