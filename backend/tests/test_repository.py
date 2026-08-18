from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.storage import repository
from app.storage.models import Candle1m, PipelineStatus, Trade

UTC = timezone.utc


def _dt(minute: int) -> datetime:
    return datetime(2026, 8, 18, 12, minute, 0, tzinfo=UTC)


async def _count(session, model) -> int:
    result = await session.execute(select(func.count()).select_from(model))
    return result.scalar_one()


class TestUpsertTrades:
    async def test_inserts_new_trades(self, session):
        await repository.upsert_trades(
            session,
            [
                {
                    "time": _dt(0),
                    "symbol": "BTCUSDT",
                    "trade_id": 1,
                    "price": "50000.10",
                    "qty": "0.01",
                    "quote_qty": "500.001",
                    "is_buyer_maker": False,
                },
                {
                    "time": _dt(0),
                    "symbol": "BTCUSDT",
                    "trade_id": 2,
                    "price": "50000.20",
                    "qty": "0.02",
                    "quote_qty": "1000.004",
                    "is_buyer_maker": True,
                },
            ],
        )
        await session.commit()

        assert await _count(session, Trade) == 2

    async def test_duplicate_trade_id_is_ignored_without_error(self, session):
        trade = {
            "time": _dt(0),
            "symbol": "BTCUSDT",
            "trade_id": 1,
            "price": "50000.10",
            "qty": "0.01",
            "quote_qty": "500.001",
            "is_buyer_maker": False,
        }
        await repository.upsert_trades(session, [trade])
        await session.commit()

        await repository.upsert_trades(session, [trade])
        await session.commit()

        assert await _count(session, Trade) == 1

    async def test_empty_batch_is_a_noop(self, session):
        await repository.upsert_trades(session, [])
        await session.commit()

        assert await _count(session, Trade) == 0


class TestUpsertCandle:
    async def test_insert_then_update_same_open_time(self, session):
        base = {
            "symbol": "ETHUSDT",
            "open_time": _dt(0),
            "close_time": _dt(1),
            "open": "3000.0",
            "high": "3010.0",
            "low": "2990.0",
            "close": "3005.0",
            "volume": "10.5",
            "quote_volume": "31500.0",
            "trade_count": 42,
            "is_closed": False,
        }
        await repository.upsert_candle(session, base)
        await session.commit()

        updated = {**base, "close": "3050.0", "trade_count": 60, "is_closed": True}
        await repository.upsert_candle(session, updated)
        await session.commit()

        assert await _count(session, Candle1m) == 1
        candles = await repository.get_candles(session, "ETHUSDT", limit=10)
        assert len(candles) == 1
        assert candles[0].close == pytest.approx(3050.0)
        assert candles[0].trade_count == 60
        assert candles[0].is_closed is True

    async def test_different_symbols_do_not_collide(self, session):
        for symbol in ("BTCUSDT", "ETHUSDT"):
            await repository.upsert_candle(
                session,
                {
                    "symbol": symbol,
                    "open_time": _dt(0),
                    "close_time": _dt(1),
                    "open": "1.0",
                    "high": "1.0",
                    "low": "1.0",
                    "close": "1.0",
                    "volume": "1.0",
                    "quote_volume": "1.0",
                    "trade_count": 1,
                    "is_closed": True,
                },
            )
        await session.commit()

        assert await _count(session, Candle1m) == 2


class TestGetLatestCandleOpenTime:
    async def test_returns_none_when_empty(self, session):
        assert await repository.get_latest_candle_open_time(session, "BTCUSDT") is None

    async def test_returns_max_open_time_for_symbol(self, session):
        for minute in (0, 1, 2):
            await repository.upsert_candle(
                session,
                {
                    "symbol": "BTCUSDT",
                    "open_time": _dt(minute),
                    "close_time": _dt(minute + 1),
                    "open": "1.0",
                    "high": "1.0",
                    "low": "1.0",
                    "close": "1.0",
                    "volume": "1.0",
                    "quote_volume": "1.0",
                    "trade_count": 1,
                    "is_closed": True,
                },
            )
        await session.commit()

        latest = await repository.get_latest_candle_open_time(session, "BTCUSDT")
        assert latest == _dt(2)


class TestGetCandles:
    async def test_orders_chronologically_and_respects_limit(self, session):
        for minute in range(5):
            await repository.upsert_candle(
                session,
                {
                    "symbol": "BTCUSDT",
                    "open_time": _dt(minute),
                    "close_time": _dt(minute + 1),
                    "open": "1.0",
                    "high": "1.0",
                    "low": "1.0",
                    "close": str(float(minute)),
                    "volume": "1.0",
                    "quote_volume": "1.0",
                    "trade_count": 1,
                    "is_closed": True,
                },
            )
        await session.commit()

        candles = await repository.get_candles(session, "BTCUSDT", limit=3)

        assert [c.open_time for c in candles] == [_dt(2), _dt(3), _dt(4)]


class TestPipelineStatus:
    async def test_ensure_row_creates_default(self, session):
        await repository.ensure_pipeline_status_row(session, "BTCUSDT")
        await session.commit()

        status = await repository.get_pipeline_status(session, "BTCUSDT")
        assert status is not None
        assert status.ws_connected is False
        assert status.reconnect_count == 0
        assert status.error_count == 0

    async def test_ensure_row_is_idempotent(self, session):
        await repository.ensure_pipeline_status_row(session, "BTCUSDT")
        await repository.ensure_pipeline_status_row(session, "BTCUSDT")
        await session.commit()

        assert await _count(session, PipelineStatus) == 1

    async def test_set_ws_connected_updates_flag_and_timestamp(self, session):
        await repository.ensure_pipeline_status_row(session, "BTCUSDT")
        at = _dt(5)

        await repository.set_ws_connected(session, "BTCUSDT", True, at)
        await session.commit()

        status = await repository.get_pipeline_status(session, "BTCUSDT")
        assert status.ws_connected is True
        assert status.updated_at == at

    async def test_record_trade_received_updates_last_trade_at(self, session):
        await repository.ensure_pipeline_status_row(session, "BTCUSDT")
        at = _dt(7)

        await repository.record_trade_received(session, "BTCUSDT", at)
        await session.commit()

        status = await repository.get_pipeline_status(session, "BTCUSDT")
        assert status.last_trade_at == at

    async def test_record_reconnect_increments_count(self, session):
        await repository.ensure_pipeline_status_row(session, "BTCUSDT")
        await repository.record_reconnect(session, "BTCUSDT", _dt(1))
        await repository.record_reconnect(session, "BTCUSDT", _dt(2))
        await session.commit()

        status = await repository.get_pipeline_status(session, "BTCUSDT")
        assert status.reconnect_count == 2

    async def test_record_error_increments_count(self, session):
        await repository.ensure_pipeline_status_row(session, "BTCUSDT")
        await repository.record_error(session, "BTCUSDT", _dt(1))
        await session.commit()

        status = await repository.get_pipeline_status(session, "BTCUSDT")
        assert status.error_count == 1

    async def test_record_backfill_updates_coverage_fields(self, session):
        await repository.ensure_pipeline_status_row(session, "BTCUSDT")
        covered_from = _dt(0)
        at = _dt(0) + timedelta(hours=24)

        await repository.record_backfill(session, "BTCUSDT", covered_from, at)
        await session.commit()

        status = await repository.get_pipeline_status(session, "BTCUSDT")
        assert status.backfill_covered_from == covered_from
        assert status.last_backfill_at == at

    async def test_get_all_pipeline_status_returns_every_symbol(self, session):
        await repository.ensure_pipeline_status_row(session, "BTCUSDT")
        await repository.ensure_pipeline_status_row(session, "ETHUSDT")
        await session.commit()

        statuses = await repository.get_all_pipeline_status(session)
        assert {s.symbol for s in statuses} == {"BTCUSDT", "ETHUSDT"}
