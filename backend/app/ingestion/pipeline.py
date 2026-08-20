import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.eventbus import EventBus
from app.ingestion.backfill import BackfillService
from app.ingestion.binance_ws import BinanceWebSocketClient
from app.ingestion.trade_buffer import TradeBuffer
from app.storage import repository

logger = logging.getLogger(__name__)


class IngestionPipeline:
    """Wires BackfillService + BinanceWebSocketClient + storage together.

    Startup does one backfill pass per symbol (covers both the cold-start
    and "we were down for a while" cases), then the WS client takes over.
    Every reconnect after the first successful connection re-runs the same
    backfill sync to cover whatever gap the drop left behind.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        backfill_service: BackfillService,
        event_bus: EventBus,
        symbols: list[str],
        ws_url: str,
        trade_batch_size: int,
        trade_flush_interval: float,
        ws_min_backoff: float,
        ws_max_backoff: float,
    ):
        self._session_factory = session_factory
        self._backfill_service = backfill_service
        self.event_bus = event_bus
        self._symbols = symbols
        self._buffers = {
            symbol: TradeBuffer(trade_batch_size, trade_flush_interval) for symbol in symbols
        }
        self._connected_once = False
        self.ws_client = BinanceWebSocketClient(
            ws_url=ws_url,
            symbols=symbols,
            on_trade=self.handle_trade,
            on_kline=self.handle_kline,
            on_connected=self.handle_connected,
            on_disconnected=self.handle_disconnected,
            min_backoff=ws_min_backoff,
            max_backoff=ws_max_backoff,
        )

    async def initial_backfill(self) -> None:
        """심볼별로 독립 시도한다 — 한 심볼의 실패가 나머지를 막지 않는다."""
        for symbol in self._symbols:
            try:
                async with self._session_factory() as session:
                    await self._backfill_service.sync(session, symbol)
                    await session.commit()
            except Exception:
                # 과거 구간이 비는 것보다 지금 들어오는 체결을 놓치는 쪽이
                # 더 치명적이다. 백필은 다음 재연결 때 같은 로직으로 재시도된다.
                logger.exception("Initial backfill failed for %s; continuing", symbol)

    async def run(self) -> None:
        await self.initial_backfill()
        await self.ws_client.run()

    def stop(self) -> None:
        self.ws_client.stop()

    async def handle_connected(self) -> None:
        now = datetime.now(timezone.utc)
        if self._connected_once:
            for symbol in self._symbols:
                async with self._session_factory() as session:
                    await self._backfill_service.sync(session, symbol, now=now)
                    await repository.record_reconnect(session, symbol, now)
                    await session.commit()
        self._connected_once = True

        for symbol in self._symbols:
            async with self._session_factory() as session:
                await repository.set_ws_connected(session, symbol, True, now)
                await session.commit()
        self.event_bus.publish({"type": "status", "ws_connected": True})

    async def handle_disconnected(self) -> None:
        now = datetime.now(timezone.utc)
        for symbol in self._symbols:
            async with self._session_factory() as session:
                await repository.set_ws_connected(session, symbol, False, now)
                await repository.record_error(session, symbol, now)
                await session.commit()
        self.event_bus.publish({"type": "status", "ws_connected": False})

    async def handle_trade(self, symbol: str, record: dict[str, Any]) -> None:
        buffer = self._buffers[symbol]
        buffer.add(record)
        self.event_bus.publish({"type": "trade", "symbol": symbol, "record": record})
        if buffer.should_flush():
            await self._flush_trades(symbol)

    async def flush_all(self) -> None:
        for symbol in self._symbols:
            if self._buffers[symbol].should_flush():
                await self._flush_trades(symbol)

    async def _flush_trades(self, symbol: str) -> None:
        records = self._buffers[symbol].drain()
        if not records:
            return
        async with self._session_factory() as session:
            await repository.upsert_trades(session, records)
            await repository.record_trade_received(session, symbol, datetime.now(timezone.utc))
            await session.commit()

    async def handle_kline(self, symbol: str, record: dict[str, Any]) -> None:
        async with self._session_factory() as session:
            await repository.upsert_candle(session, record)
            await session.commit()
        self.event_bus.publish({"type": "kline", "symbol": symbol, "record": record})
