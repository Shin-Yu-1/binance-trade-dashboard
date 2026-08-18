from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.storage.models import Candle1m, PipelineStatus, Trade

_CANDLE_UPDATE_COLUMNS = (
    "close_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "quote_volume",
    "trade_count",
    "is_closed",
)


async def upsert_trades(session: AsyncSession, trades: Sequence[dict[str, Any]]) -> None:
    """Insert executed trades, silently skipping ones already stored.

    Trade fields never change after the fact, so a duplicate ``(time, symbol,
    trade_id)`` is safe to ignore rather than update.
    """
    if not trades:
        return
    stmt = insert(Trade).values(list(trades))
    stmt = stmt.on_conflict_do_nothing(index_elements=["time", "symbol", "trade_id"])
    await session.execute(stmt)


async def upsert_candle(session: AsyncSession, candle: dict[str, Any]) -> None:
    """Insert or refresh a 1-minute candle for ``(symbol, open_time)``.

    Candles evolve while still forming, so unlike trades this always
    overwrites the OHLCV fields with the latest values from Binance.
    """
    stmt = insert(Candle1m).values(**candle)
    update_cols = {col: stmt.excluded[col] for col in _CANDLE_UPDATE_COLUMNS}
    stmt = stmt.on_conflict_do_update(
        index_elements=["symbol", "open_time"],
        set_=update_cols,
    )
    await session.execute(stmt)


async def get_latest_candle_open_time(session: AsyncSession, symbol: str) -> datetime | None:
    result = await session.execute(
        select(Candle1m.open_time)
        .where(Candle1m.symbol == symbol)
        .order_by(Candle1m.open_time.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_candles(session: AsyncSession, symbol: str, limit: int = 500) -> list[Candle1m]:
    result = await session.execute(
        select(Candle1m)
        .where(Candle1m.symbol == symbol)
        .order_by(Candle1m.open_time.desc())
        .limit(limit)
    )
    candles = list(result.scalars().all())
    candles.reverse()
    return candles


async def ensure_pipeline_status_row(session: AsyncSession, symbol: str) -> None:
    stmt = insert(PipelineStatus).values(symbol=symbol)
    stmt = stmt.on_conflict_do_nothing(index_elements=["symbol"])
    await session.execute(stmt)


async def get_pipeline_status(session: AsyncSession, symbol: str) -> PipelineStatus | None:
    result = await session.execute(select(PipelineStatus).where(PipelineStatus.symbol == symbol))
    return result.scalar_one_or_none()


async def get_all_pipeline_status(session: AsyncSession) -> list[PipelineStatus]:
    result = await session.execute(select(PipelineStatus))
    return list(result.scalars().all())


async def set_ws_connected(session: AsyncSession, symbol: str, connected: bool, at: datetime) -> None:
    await ensure_pipeline_status_row(session, symbol)
    await session.execute(
        update(PipelineStatus)
        .where(PipelineStatus.symbol == symbol)
        .values(ws_connected=connected, updated_at=at)
    )


async def record_trade_received(session: AsyncSession, symbol: str, at: datetime) -> None:
    await ensure_pipeline_status_row(session, symbol)
    await session.execute(
        update(PipelineStatus)
        .where(PipelineStatus.symbol == symbol)
        .values(last_trade_at=at, updated_at=at)
    )


async def record_reconnect(session: AsyncSession, symbol: str, at: datetime) -> None:
    await ensure_pipeline_status_row(session, symbol)
    await session.execute(
        update(PipelineStatus)
        .where(PipelineStatus.symbol == symbol)
        .values(reconnect_count=PipelineStatus.reconnect_count + 1, updated_at=at)
    )


async def record_error(session: AsyncSession, symbol: str, at: datetime) -> None:
    await ensure_pipeline_status_row(session, symbol)
    await session.execute(
        update(PipelineStatus)
        .where(PipelineStatus.symbol == symbol)
        .values(error_count=PipelineStatus.error_count + 1, updated_at=at)
    )


async def record_backfill(
    session: AsyncSession, symbol: str, covered_from: datetime, at: datetime
) -> None:
    await ensure_pipeline_status_row(session, symbol)
    await session.execute(
        update(PipelineStatus)
        .where(PipelineStatus.symbol == symbol)
        .values(backfill_covered_from=covered_from, last_backfill_at=at, updated_at=at)
    )
