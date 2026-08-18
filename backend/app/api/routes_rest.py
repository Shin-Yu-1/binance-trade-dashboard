from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.storage import repository
from app.storage.db import get_session
from app.storage.models import Candle1m

router = APIRouter(prefix="/api")

STALE_THRESHOLD_SECONDS = 10
STATS_LOOKBACK_MINUTES = 1440  # 24h of 1m candles


def _serialize_candle(candle: Candle1m) -> dict:
    return {
        "symbol": candle.symbol,
        "open_time": candle.open_time.isoformat(),
        "close_time": candle.close_time.isoformat(),
        "open": str(candle.open),
        "high": str(candle.high),
        "low": str(candle.low),
        "close": str(candle.close),
        "volume": str(candle.volume),
        "quote_volume": str(candle.quote_volume),
        "trade_count": candle.trade_count,
        "is_closed": candle.is_closed,
    }


@router.get("/candles")
async def get_candles(
    symbol: str,
    limit: int = Query(500, ge=1, le=STATS_LOOKBACK_MINUTES),
    session: AsyncSession = Depends(get_session),
):
    candles = await repository.get_candles(session, symbol.upper(), limit=limit)
    return [_serialize_candle(c) for c in candles]


@router.get("/stats")
async def get_stats(symbol: str, session: AsyncSession = Depends(get_session)):
    symbol = symbol.upper()
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=24)

    candles = await repository.get_candles(session, symbol, limit=STATS_LOOKBACK_MINUTES)
    buy_volume, sell_volume = await repository.get_taker_buy_sell_volume(session, symbol, since)

    if not candles:
        return {
            "symbol": symbol,
            "last_price": None,
            "change_pct": None,
            "high": None,
            "low": None,
            "volume": None,
            "taker_buy_volume": str(buy_volume),
            "taker_sell_volume": str(sell_volume),
        }

    first_open = candles[0].open
    last_close = candles[-1].close
    change_pct = float((last_close - first_open) / first_open * 100) if first_open else None

    return {
        "symbol": symbol,
        "last_price": str(last_close),
        "change_pct": change_pct,
        "high": str(max(c.high for c in candles)),
        "low": str(min(c.low for c in candles)),
        "volume": str(sum(c.volume for c in candles)),
        "taker_buy_volume": str(buy_volume),
        "taker_sell_volume": str(sell_volume),
    }


@router.get("/health")
async def get_health(session: AsyncSession = Depends(get_session)):
    statuses = await repository.get_all_pipeline_status(session)
    now = datetime.now(timezone.utc)

    result = []
    for status in statuses:
        stale = (
            not status.ws_connected
            or status.last_trade_at is None
            or (now - status.last_trade_at).total_seconds() > STALE_THRESHOLD_SECONDS
        )
        result.append(
            {
                "symbol": status.symbol,
                "ws_connected": status.ws_connected,
                "last_trade_at": status.last_trade_at.isoformat() if status.last_trade_at else None,
                "last_backfill_at": (
                    status.last_backfill_at.isoformat() if status.last_backfill_at else None
                ),
                "backfill_covered_from": (
                    status.backfill_covered_from.isoformat()
                    if status.backfill_covered_from
                    else None
                ),
                "reconnect_count": status.reconnect_count,
                "error_count": status.error_count,
                "stale": stale,
            }
        )
    return result
