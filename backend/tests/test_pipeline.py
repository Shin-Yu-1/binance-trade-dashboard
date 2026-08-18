from datetime import datetime, timedelta, timezone

import pytest

from app.api.eventbus import EventBus
from app.ingestion.pipeline import IngestionPipeline
from app.storage import repository

UTC = timezone.utc


class StubBackfillService:
    def __init__(self):
        self.calls: list[str] = []

    async def sync(self, session, symbol, now=None):
        self.calls.append(symbol)
        return 0


def _make_pipeline(session_factory, backfill=None, batch_size=100, flush_interval=999.0):
    return IngestionPipeline(
        session_factory=session_factory,
        backfill_service=backfill or StubBackfillService(),
        event_bus=EventBus(),
        symbols=["BTCUSDT", "ETHUSDT"],
        ws_url="wss://example.invalid/stream",
        trade_batch_size=batch_size,
        trade_flush_interval=flush_interval,
        ws_min_backoff=1.0,
        ws_max_backoff=30.0,
    )


@pytest.mark.asyncio
async def test_handle_kline_upserts_candle_and_publishes(session_factory):
    pipeline = _make_pipeline(session_factory)
    bus_queue = pipeline.event_bus.subscribe()
    open_time = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)

    await pipeline.handle_kline(
        "BTCUSDT",
        {
            "symbol": "BTCUSDT",
            "open_time": open_time,
            "close_time": open_time + timedelta(minutes=1),
            "open": "1",
            "high": "1",
            "low": "1",
            "close": "1",
            "volume": "1",
            "quote_volume": "1",
            "trade_count": 1,
            "is_closed": False,
        },
    )

    async with session_factory() as session:
        candles = await repository.get_candles(session, "BTCUSDT", limit=10)
    assert len(candles) == 1

    event = bus_queue.get_nowait()
    assert event["type"] == "kline"
    assert event["symbol"] == "BTCUSDT"


@pytest.mark.asyncio
async def test_handle_trade_does_not_flush_before_batch_size(session_factory):
    pipeline = _make_pipeline(session_factory, batch_size=5)

    await pipeline.handle_trade(
        "BTCUSDT",
        {
            "time": datetime(2026, 8, 18, 12, 0, tzinfo=UTC),
            "symbol": "BTCUSDT",
            "trade_id": 1,
            "price": "1",
            "qty": "1",
            "quote_qty": "1",
            "is_buyer_maker": False,
        },
    )

    async with session_factory() as session:
        status = await repository.get_pipeline_status(session, "BTCUSDT")
    assert status is None  # nothing flushed yet, so no status row was touched


@pytest.mark.asyncio
async def test_handle_trade_flushes_at_batch_size(session_factory):
    pipeline = _make_pipeline(session_factory, batch_size=2)
    bus_queue = pipeline.event_bus.subscribe()

    for trade_id in (1, 2):
        await pipeline.handle_trade(
            "BTCUSDT",
            {
                "time": datetime(2026, 8, 18, 12, 0, tzinfo=UTC),
                "symbol": "BTCUSDT",
                "trade_id": trade_id,
                "price": "1",
                "qty": "1",
                "quote_qty": "1",
                "is_buyer_maker": False,
            },
        )

    async with session_factory() as session:
        status = await repository.get_pipeline_status(session, "BTCUSDT")
    assert status is not None
    assert status.last_trade_at is not None

    events = [bus_queue.get_nowait() for _ in range(2)]
    assert [e["type"] for e in events] == ["trade", "trade"]


@pytest.mark.asyncio
async def test_handle_connected_first_time_does_not_trigger_resync(session_factory):
    backfill = StubBackfillService()
    pipeline = _make_pipeline(session_factory, backfill=backfill)

    await pipeline.handle_connected()

    assert backfill.calls == []
    async with session_factory() as session:
        status = await repository.get_pipeline_status(session, "BTCUSDT")
    assert status.ws_connected is True


@pytest.mark.asyncio
async def test_handle_connected_after_reconnect_triggers_resync(session_factory):
    backfill = StubBackfillService()
    pipeline = _make_pipeline(session_factory, backfill=backfill)

    await pipeline.handle_connected()
    await pipeline.handle_disconnected()
    await pipeline.handle_connected()

    assert sorted(backfill.calls) == ["BTCUSDT", "ETHUSDT"]
    async with session_factory() as session:
        status = await repository.get_pipeline_status(session, "BTCUSDT")
    assert status.reconnect_count == 1


@pytest.mark.asyncio
async def test_handle_disconnected_marks_status_and_records_error(session_factory):
    pipeline = _make_pipeline(session_factory)

    await pipeline.handle_disconnected()

    async with session_factory() as session:
        status = await repository.get_pipeline_status(session, "BTCUSDT")
    assert status.ws_connected is False
    assert status.error_count == 1
