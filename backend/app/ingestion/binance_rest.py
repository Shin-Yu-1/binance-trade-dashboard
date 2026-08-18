import asyncio
from datetime import datetime, timezone
from typing import Any

import httpx

KLINES_PATH = "/api/v3/klines"
MAX_KLINES_PER_REQUEST = 1000
RETRYABLE_STATUS_CODES = {418, 429}
MAX_RETRIES = 5


def _to_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _from_ms(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def _parse_kline(symbol: str, raw: list[Any], now_ms: int) -> dict[str, Any]:
    open_time_ms, open_, high, low, close, volume, close_time_ms, quote_volume, trade_count = raw[:9]
    return {
        "symbol": symbol,
        "open_time": _from_ms(open_time_ms),
        "close_time": _from_ms(close_time_ms),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "quote_volume": quote_volume,
        "trade_count": int(trade_count),
        "is_closed": close_time_ms <= now_ms,
    }


async def _get_with_retry(
    client: httpx.AsyncClient, base_url: str, params: dict[str, Any]
) -> list[list[Any]]:
    attempt = 0
    while True:
        response = await client.get(f"{base_url}{KLINES_PATH}", params=params)
        if response.status_code not in RETRYABLE_STATUS_CODES:
            response.raise_for_status()
            return response.json()

        attempt += 1
        if attempt > MAX_RETRIES:
            response.raise_for_status()

        retry_after = response.headers.get("Retry-After")
        delay = float(retry_after) if retry_after else min(2**attempt, 30)
        await asyncio.sleep(delay)


async def fetch_klines(
    client: httpx.AsyncClient,
    base_url: str,
    symbol: str,
    start_time: datetime,
    end_time: datetime,
    interval: str = "1m",
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Fetch 1m klines for ``[start_time, end_time]``, paginating in pages of
    up to ``MAX_KLINES_PER_REQUEST`` candles.

    ``now`` controls which of the returned candles are treated as still
    forming (``is_closed=False``); it defaults to the real current time and
    is only overridden by tests.
    """
    now_ms = _to_ms(now) if now is not None else _to_ms(datetime.now(timezone.utc))
    results: list[dict[str, Any]] = []
    cursor_ms = _to_ms(start_time)
    end_ms = _to_ms(end_time)

    while cursor_ms < end_ms:
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": cursor_ms,
            "endTime": end_ms,
            "limit": MAX_KLINES_PER_REQUEST,
        }
        raw_klines = await _get_with_retry(client, base_url, params)
        if not raw_klines:
            break

        results.extend(_parse_kline(symbol, raw, now_ms) for raw in raw_klines)

        next_cursor_ms = raw_klines[-1][0] + 1
        if next_cursor_ms <= cursor_ms:
            break
        cursor_ms = next_cursor_ms

        if len(raw_klines) < MAX_KLINES_PER_REQUEST:
            break

    return results
