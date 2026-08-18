from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx

from app.ingestion.backfill import BackfillService
from app.storage import repository

BASE_URL = "https://api.binance.com"
UTC = timezone.utc


def _raw_kline(open_ms: int, close_ms: int) -> list:
    return [
        open_ms,
        "50000.00",
        "50100.00",
        "49900.00",
        "50050.00",
        "12.5",
        close_ms,
        "625000.0",
        100,
        "6.0",
        "300000.0",
        "0",
    ]


def _to_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


async def _seed_candle(session, symbol: str, open_time: datetime) -> None:
    await repository.upsert_candle(
        session,
        {
            "symbol": symbol,
            "open_time": open_time,
            "close_time": open_time + timedelta(minutes=1),
            "open": "1",
            "high": "1",
            "low": "1",
            "close": "1",
            "volume": "1",
            "quote_volume": "1",
            "trade_count": 1,
            "is_closed": True,
        },
    )


@pytest.mark.asyncio
async def test_cold_start_backfills_from_configured_window(session):
    now = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    start = now - timedelta(hours=24)

    with respx.mock(assert_all_called=True) as mock:
        route = mock.get(f"{BASE_URL}/api/v3/klines")
        route.mock(
            return_value=httpx.Response(200, json=[_raw_kline(_to_ms(start), _to_ms(start) + 59999)])
        )
        async with httpx.AsyncClient() as client:
            service = BackfillService(client, BASE_URL, backfill_hours=24)
            written = await service.sync(session, "BTCUSDT", now=now)
        await session.commit()

    assert written == 1
    assert route.call_count == 1
    requested = route.calls.last.request.url.params
    assert int(requested["startTime"]) == _to_ms(start)
    assert int(requested["endTime"]) == _to_ms(now)

    status = await repository.get_pipeline_status(session, "BTCUSDT")
    assert status.backfill_covered_from == start
    assert status.last_backfill_at == now


@pytest.mark.asyncio
async def test_restart_gap_backfills_only_missing_range(session):
    now = datetime(2026, 8, 18, 12, 10, tzinfo=UTC)
    last_open = datetime(2026, 8, 18, 12, 5, tzinfo=UTC)
    await _seed_candle(session, "BTCUSDT", last_open)
    await session.commit()

    with respx.mock(assert_all_called=True) as mock:
        route = mock.get(f"{BASE_URL}/api/v3/klines")
        route.mock(
            return_value=httpx.Response(
                200, json=[_raw_kline(_to_ms(last_open), _to_ms(last_open) + 59999)]
            )
        )
        async with httpx.AsyncClient() as client:
            service = BackfillService(client, BASE_URL, backfill_hours=24)
            await service.sync(session, "BTCUSDT", now=now)

    assert route.call_count == 1
    requested = route.calls.last.request.url.params
    assert int(requested["startTime"]) == _to_ms(last_open)
    assert int(requested["endTime"]) == _to_ms(now)


@pytest.mark.asyncio
async def test_no_gap_is_a_noop_and_makes_no_rest_call(session):
    now = datetime(2026, 8, 18, 12, 5, tzinfo=UTC)
    floored_now = now.replace(second=0, microsecond=0)
    await _seed_candle(session, "BTCUSDT", floored_now)
    await session.commit()

    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(f"{BASE_URL}/api/v3/klines")
        async with httpx.AsyncClient() as client:
            service = BackfillService(client, BASE_URL, backfill_hours=24)
            written = await service.sync(session, "BTCUSDT", now=now)

    assert written == 0
    assert route.called is False


@pytest.mark.asyncio
async def test_sync_is_scoped_per_symbol(session):
    now = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    start = now - timedelta(hours=24)

    with respx.mock(assert_all_called=True) as mock:
        route = mock.get(f"{BASE_URL}/api/v3/klines")
        route.mock(
            return_value=httpx.Response(200, json=[_raw_kline(_to_ms(start), _to_ms(start) + 59999)])
        )
        async with httpx.AsyncClient() as client:
            service = BackfillService(client, BASE_URL, backfill_hours=24)
            await service.sync(session, "ETHUSDT", now=now)

    requested = route.calls.last.request.url.params
    assert requested["symbol"] == "ETHUSDT"
