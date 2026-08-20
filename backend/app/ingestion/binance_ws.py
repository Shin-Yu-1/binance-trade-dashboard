import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

import websockets

logger = logging.getLogger(__name__)

TradeHandler = Callable[[str, dict[str, Any]], Awaitable[None]]
KlineHandler = Callable[[str, dict[str, Any]], Awaitable[None]]
LifecycleHandler = Callable[[], Awaitable[None]]


def build_stream_url(base_ws_url: str, symbols: list[str]) -> str:
    streams: list[str] = []
    for symbol in symbols:
        lower = symbol.lower()
        streams.append(f"{lower}@trade")
        streams.append(f"{lower}@kline_1m")
    return f"{base_ws_url}?streams={'/'.join(streams)}"


def _from_ms(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def parse_message(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize a combined-stream message into ``{"type", "symbol", "record"}``.

    Returns ``None`` for event types we don't care about, so callers can
    just skip anything unrecognized instead of special-casing it.
    """
    payload = raw.get("data", raw)
    event_type = payload.get("e")

    if event_type == "trade":
        price = payload["p"]
        qty = payload["q"]
        return {
            "type": "trade",
            "symbol": payload["s"],
            "record": {
                "time": _from_ms(payload["T"]),
                "symbol": payload["s"],
                "trade_id": payload["t"],
                "price": price,
                "qty": qty,
                "quote_qty": str(float(price) * float(qty)),
                "is_buyer_maker": payload["m"],
            },
        }

    if event_type == "kline":
        k = payload["k"]
        return {
            "type": "kline",
            "symbol": payload["s"],
            "record": {
                "symbol": payload["s"],
                "open_time": _from_ms(k["t"]),
                "close_time": _from_ms(k["T"]),
                "open": k["o"],
                "high": k["h"],
                "low": k["l"],
                "close": k["c"],
                "volume": k["v"],
                "quote_volume": k["q"],
                "trade_count": k["n"],
                "is_closed": k["x"],
            },
        }

    return None


def next_backoff(current: float, min_s: float, max_s: float) -> float:
    if current <= 0:
        return min_s
    return min(current * 2, max_s)


class BinanceWebSocketClient:
    """Runs the combined trade+kline_1m stream with auto-reconnect.

    On every (re)connect the caller's ``on_connected`` hook fires, which
    the ingestion pipeline uses to re-run BackfillService.sync and cover
    whatever gap the disconnect left behind.
    """

    def __init__(
        self,
        ws_url: str,
        symbols: list[str],
        on_trade: TradeHandler,
        on_kline: KlineHandler,
        on_connected: LifecycleHandler | None = None,
        on_disconnected: LifecycleHandler | None = None,
        min_backoff: float = 1.0,
        max_backoff: float = 30.0,
    ):
        self._url = build_stream_url(ws_url, symbols)
        self._on_trade = on_trade
        self._on_kline = on_kline
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected
        self._min_backoff = min_backoff
        self._max_backoff = max_backoff
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    async def run(self) -> None:
        backoff = 0.0
        while not self._stop:
            try:
                async with websockets.connect(self._url) as ws:
                    backoff = 0.0
                    if self._on_connected:
                        await self._on_connected()
                    async for raw_message in ws:
                        await self._dispatch(raw_message)
            except (websockets.exceptions.ConnectionClosed, OSError) as exc:
                logger.warning("Binance WS disconnected: %s", exc)
            except Exception:
                # 핸들러(DB 쓰기 등)에서 올라온 예상 밖 예외까지 여기서 막는다.
                # 이걸 놓치면 수집 태스크만 조용히 죽고 API는 계속 200을
                # 반환하는, 가장 발견하기 어려운 장애가 된다.
                logger.exception("Binance WS loop failed unexpectedly; reconnecting")
            finally:
                if self._on_disconnected:
                    try:
                        await self._on_disconnected()
                    except Exception:
                        # 상태 기록 실패가 재연결 루프를 멈추게 하지 않는다.
                        logger.exception("on_disconnected hook failed")

            if self._stop:
                break
            backoff = next_backoff(backoff, self._min_backoff, self._max_backoff)
            await asyncio.sleep(backoff)

    async def _dispatch(self, raw_message: str | bytes) -> None:
        event = parse_message(json.loads(raw_message))
        if event is None:
            return
        if event["type"] == "trade":
            await self._on_trade(event["symbol"], event["record"])
        elif event["type"] == "kline":
            await self._on_kline(event["symbol"], event["record"])
