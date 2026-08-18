from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.binance_rest import fetch_klines
from app.storage import repository


def _floor_to_minute(dt: datetime) -> datetime:
    return dt.replace(second=0, microsecond=0)


class BackfillService:
    """Fills the ``candles_1m`` gap for a symbol via Binance REST klines.

    The same ``sync`` call handles both the cold-start case (no candles
    stored yet) and the restart/reconnect gap-fill case (some candles
    already stored) — the only difference is where the gap's start point
    comes from.
    """

    def __init__(self, client: httpx.AsyncClient, base_url: str, backfill_hours: int):
        self._client = client
        self._base_url = base_url
        self._backfill_hours = backfill_hours

    async def sync(
        self, session: AsyncSession, symbol: str, now: datetime | None = None
    ) -> int:
        now = now or datetime.now(timezone.utc)
        end = _floor_to_minute(now)

        latest = await repository.get_latest_candle_open_time(session, symbol)
        start = latest if latest is not None else end - timedelta(hours=self._backfill_hours)

        if start >= end:
            return 0

        candles = await fetch_klines(self._client, self._base_url, symbol, start, end, now=now)
        for candle in candles:
            await repository.upsert_candle(session, candle)

        await repository.record_backfill(session, symbol, start, now)

        return len(candles)
