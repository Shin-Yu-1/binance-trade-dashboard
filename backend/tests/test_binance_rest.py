from datetime import datetime, timezone

import httpx
import pytest
import respx

from app.ingestion import binance_rest

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


@pytest.mark.asyncio
async def test_parses_kline_fields():
    now = datetime(2026, 8, 18, 12, 5, tzinfo=UTC)
    with respx.mock(assert_all_called=True) as mock:
        mock.get(f"{BASE_URL}/api/v3/klines").respond(
            200, json=[_raw_kline(1755518400000, 1755518459999)]
        )
        async with httpx.AsyncClient() as client:
            candles = await binance_rest.fetch_klines(
                client,
                BASE_URL,
                "BTCUSDT",
                datetime(2026, 8, 18, 12, 0, tzinfo=UTC),
                datetime(2026, 8, 18, 12, 1, tzinfo=UTC),
                now=now,
            )

    assert len(candles) == 1
    candle = candles[0]
    assert candle["symbol"] == "BTCUSDT"
    assert candle["open"] == "50000.00"
    assert candle["close"] == "50050.00"
    assert candle["trade_count"] == 100
    assert candle["is_closed"] is True


@pytest.mark.asyncio
async def test_marks_in_progress_candle_as_not_closed():
    now = datetime(2026, 8, 18, 12, 0, 30, tzinfo=UTC)
    open_ms = 1755518400000  # 2026-08-18T12:00:00Z
    close_ms = 1755518459999  # 2026-08-18T12:00:59.999Z (still in the future vs `now`)

    with respx.mock(assert_all_called=True) as mock:
        mock.get(f"{BASE_URL}/api/v3/klines").respond(200, json=[_raw_kline(open_ms, close_ms)])
        async with httpx.AsyncClient() as client:
            candles = await binance_rest.fetch_klines(
                client,
                BASE_URL,
                "BTCUSDT",
                datetime(2026, 8, 18, 12, 0, tzinfo=UTC),
                datetime(2026, 8, 18, 12, 1, tzinfo=UTC),
                now=now,
            )

    assert candles[0]["is_closed"] is False


@pytest.mark.asyncio
async def test_paginates_until_a_partial_page_is_returned(monkeypatch):
    monkeypatch.setattr(binance_rest, "MAX_KLINES_PER_REQUEST", 2)
    now = datetime(2026, 8, 18, 13, 0, tzinfo=UTC)

    page_1 = [
        _raw_kline(1755518400000, 1755518459999),
        _raw_kline(1755518460000, 1755518519999),
    ]
    page_2 = [_raw_kline(1755518520000, 1755518579999)]

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
                datetime(2026, 8, 18, 12, 0, tzinfo=UTC),
                datetime(2026, 8, 18, 12, 3, tzinfo=UTC),
                now=now,
            )

    assert len(candles) == 3
    assert route.call_count == 2


@pytest.mark.asyncio
async def test_empty_response_ends_pagination():
    now = datetime(2026, 8, 18, 13, 0, tzinfo=UTC)
    with respx.mock(assert_all_called=True) as mock:
        mock.get(f"{BASE_URL}/api/v3/klines").respond(200, json=[])
        async with httpx.AsyncClient() as client:
            candles = await binance_rest.fetch_klines(
                client,
                BASE_URL,
                "BTCUSDT",
                datetime(2026, 8, 18, 12, 0, tzinfo=UTC),
                datetime(2026, 8, 18, 12, 1, tzinfo=UTC),
                now=now,
            )

    assert candles == []


@pytest.mark.asyncio
async def test_retries_on_429_then_succeeds():
    now = datetime(2026, 8, 18, 13, 0, tzinfo=UTC)
    with respx.mock(assert_all_called=True) as mock:
        route = mock.get(f"{BASE_URL}/api/v3/klines")
        route.side_effect = [
            httpx.Response(429, headers={"Retry-After": "0"}, json={"msg": "rate limited"}),
            httpx.Response(200, json=[_raw_kline(1755518400000, 1755518459999)]),
        ]
        async with httpx.AsyncClient() as client:
            candles = await binance_rest.fetch_klines(
                client,
                BASE_URL,
                "BTCUSDT",
                datetime(2026, 8, 18, 12, 0, tzinfo=UTC),
                datetime(2026, 8, 18, 12, 1, tzinfo=UTC),
                now=now,
            )

    assert len(candles) == 1
    assert route.call_count == 2


@pytest.mark.asyncio
async def test_raises_after_exceeding_max_retries(monkeypatch):
    monkeypatch.setattr(binance_rest, "MAX_RETRIES", 1)
    now = datetime(2026, 8, 18, 13, 0, tzinfo=UTC)

    with respx.mock(assert_all_called=True) as mock:
        route = mock.get(f"{BASE_URL}/api/v3/klines")
        route.respond(418, headers={"Retry-After": "0"}, json={"msg": "banned"})

        async with httpx.AsyncClient() as client:
            with pytest.raises(httpx.HTTPStatusError):
                await binance_rest.fetch_klines(
                    client,
                    BASE_URL,
                    "BTCUSDT",
                    datetime(2026, 8, 18, 12, 0, tzinfo=UTC),
                    datetime(2026, 8, 18, 12, 1, tzinfo=UTC),
                    now=now,
                )

    assert route.call_count == 2
