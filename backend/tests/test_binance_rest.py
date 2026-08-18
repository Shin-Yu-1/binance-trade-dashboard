from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx

from app.ingestion import binance_rest

BASE_URL = "https://api.binance.com"
UTC = timezone.utc


def _to_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _raw_kline(open_time: datetime) -> list:
    close_time = open_time + timedelta(minutes=1) - timedelta(milliseconds=1)
    return [
        _to_ms(open_time),
        "50000.00",
        "50100.00",
        "49900.00",
        "50050.00",
        "12.5",
        _to_ms(close_time),
        "625000.0",
        100,
        "6.0",
        "300000.0",
        "0",
    ]


@pytest.mark.asyncio
async def test_parses_kline_fields():
    open_time = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    now = open_time + timedelta(minutes=5)
    with respx.mock(assert_all_called=True) as mock:
        mock.get(f"{BASE_URL}/api/v3/klines").respond(200, json=[_raw_kline(open_time)])
        async with httpx.AsyncClient() as client:
            candles = await binance_rest.fetch_klines(
                client,
                BASE_URL,
                "BTCUSDT",
                open_time,
                open_time + timedelta(minutes=1),
                now=now,
            )

    assert len(candles) == 1
    candle = candles[0]
    assert candle["symbol"] == "BTCUSDT"
    assert candle["open_time"] == open_time
    assert candle["open"] == "50000.00"
    assert candle["close"] == "50050.00"
    assert candle["trade_count"] == 100
    assert candle["is_closed"] is True


@pytest.mark.asyncio
async def test_marks_in_progress_candle_as_not_closed():
    open_time = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    now = open_time + timedelta(seconds=30)  # still inside this candle's minute

    with respx.mock(assert_all_called=True) as mock:
        mock.get(f"{BASE_URL}/api/v3/klines").respond(200, json=[_raw_kline(open_time)])
        async with httpx.AsyncClient() as client:
            candles = await binance_rest.fetch_klines(
                client,
                BASE_URL,
                "BTCUSDT",
                open_time,
                open_time + timedelta(minutes=1),
                now=now,
            )

    assert candles[0]["is_closed"] is False


@pytest.mark.asyncio
async def test_paginates_until_a_partial_page_is_returned(monkeypatch):
    monkeypatch.setattr(binance_rest, "MAX_KLINES_PER_REQUEST", 2)
    start = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    now = start + timedelta(hours=1)

    page_1 = [_raw_kline(start), _raw_kline(start + timedelta(minutes=1))]
    page_2 = [_raw_kline(start + timedelta(minutes=2))]

    with respx.mock(assert_all_called=True) as mock:
        route = mock.get(f"{BASE_URL}/api/v3/klines")
        route.side_effect = [
            httpx.Response(200, json=page_1),
            httpx.Response(200, json=page_2),
        ]
        async with httpx.AsyncClient() as client:
            candles = await binance_rest.fetch_klines(
                client,
                BASE_URL,
                "BTCUSDT",
                start,
                start + timedelta(minutes=3),
                now=now,
            )

    assert len(candles) == 3
    assert route.call_count == 2


@pytest.mark.asyncio
async def test_empty_response_ends_pagination():
    start = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    with respx.mock(assert_all_called=True) as mock:
        mock.get(f"{BASE_URL}/api/v3/klines").respond(200, json=[])
        async with httpx.AsyncClient() as client:
            candles = await binance_rest.fetch_klines(
                client,
                BASE_URL,
                "BTCUSDT",
                start,
                start + timedelta(minutes=1),
                now=start + timedelta(hours=1),
            )

    assert candles == []


@pytest.mark.asyncio
async def test_retries_on_429_then_succeeds():
    start = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    with respx.mock(assert_all_called=True) as mock:
        route = mock.get(f"{BASE_URL}/api/v3/klines")
        route.side_effect = [
            httpx.Response(429, headers={"Retry-After": "0"}, json={"msg": "rate limited"}),
            httpx.Response(200, json=[_raw_kline(start)]),
        ]
        async with httpx.AsyncClient() as client:
            candles = await binance_rest.fetch_klines(
                client,
                BASE_URL,
                "BTCUSDT",
                start,
                start + timedelta(minutes=1),
                now=start + timedelta(hours=1),
            )

    assert len(candles) == 1
    assert route.call_count == 2


@pytest.mark.asyncio
async def test_raises_after_exceeding_max_retries(monkeypatch):
    monkeypatch.setattr(binance_rest, "MAX_RETRIES", 1)
    start = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)

    with respx.mock(assert_all_called=True) as mock:
        route = mock.get(f"{BASE_URL}/api/v3/klines")
        route.respond(418, headers={"Retry-After": "0"}, json={"msg": "banned"})

        async with httpx.AsyncClient() as client:
            with pytest.raises(httpx.HTTPStatusError):
                await binance_rest.fetch_klines(
                    client,
                    BASE_URL,
                    "BTCUSDT",
                    start,
                    start + timedelta(minutes=1),
                    now=start + timedelta(hours=1),
                )

    assert route.call_count == 2
