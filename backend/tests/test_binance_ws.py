import asyncio
import json
from datetime import datetime, timezone

import pytest
import websockets

from app.ingestion import binance_ws

UTC = timezone.utc


def test_build_stream_url_combines_trade_and_kline_streams():
    url = binance_ws.build_stream_url("wss://stream.binance.com:9443/stream", ["BTCUSDT", "ETHUSDT"])

    assert url == (
        "wss://stream.binance.com:9443/stream"
        "?streams=btcusdt@trade/btcusdt@kline_1m/ethusdt@trade/ethusdt@kline_1m"
    )


def test_parse_message_extracts_trade_event():
    raw = {
        "stream": "btcusdt@trade",
        "data": {
            "e": "trade",
            "s": "BTCUSDT",
            "t": 12345,
            "p": "50000.00",
            "q": "0.01",
            "T": 1755518400000,
            "m": True,
        },
    }

    event = binance_ws.parse_message(raw)

    assert event["type"] == "trade"
    assert event["symbol"] == "BTCUSDT"
    record = event["record"]
    assert record["trade_id"] == 12345
    assert record["price"] == "50000.00"
    assert record["qty"] == "0.01"
    assert record["is_buyer_maker"] is True
    assert record["time"] == datetime(2025, 8, 18, 12, 0, tzinfo=UTC)


def test_parse_message_extracts_kline_event():
    raw = {
        "stream": "btcusdt@kline_1m",
        "data": {
            "e": "kline",
            "s": "BTCUSDT",
            "k": {
                "t": 1755518400000,
                "T": 1755518459999,
                "o": "50000.0",
                "h": "50100.0",
                "l": "49900.0",
                "c": "50050.0",
                "v": "12.5",
                "n": 100,
                "x": False,
                "q": "625000.0",
            },
        },
    }

    event = binance_ws.parse_message(raw)

    assert event["type"] == "kline"
    assert event["symbol"] == "BTCUSDT"
    record = event["record"]
    assert record["symbol"] == "BTCUSDT"
    assert record["open"] == "50000.0"
    assert record["is_closed"] is False
    assert record["trade_count"] == 100


def test_parse_message_returns_none_for_unknown_event_type():
    raw = {"stream": "btcusdt@trade", "data": {"e": "someOtherEvent"}}

    assert binance_ws.parse_message(raw) is None


def test_next_backoff_starts_at_min_and_doubles_up_to_max():
    assert binance_ws.next_backoff(0.0, min_s=1.0, max_s=30.0) == 1.0
    assert binance_ws.next_backoff(1.0, min_s=1.0, max_s=30.0) == 2.0
    assert binance_ws.next_backoff(20.0, min_s=1.0, max_s=30.0) == 30.0
    assert binance_ws.next_backoff(30.0, min_s=1.0, max_s=30.0) == 30.0


@pytest.mark.asyncio
async def test_client_reconnects_and_resumes_dispatching_after_disconnect():
    trades: list[tuple[str, dict]] = []
    connect_count = 0
    connect_event = asyncio.Event()

    async def handler(ws):
        nonlocal connect_count
        connect_count += 1
        if connect_count == 1:
            await ws.send(
                json.dumps(
                    {
                        "data": {
                            "e": "trade",
                            "s": "BTCUSDT",
                            "t": 1,
                            "p": "1",
                            "q": "1",
                            "T": 0,
                            "m": False,
                        }
                    }
                )
            )
            await ws.close()
        else:
            connect_event.set()
            await asyncio.sleep(10)

    async with websockets.serve(handler, "localhost", 0) as server:
        port = server.sockets[0].getsockname()[1]

        async def on_trade(symbol: str, record: dict) -> None:
            trades.append((symbol, record))

        async def on_kline(symbol: str, record: dict) -> None:
            pass

        client = binance_ws.BinanceWebSocketClient(
            ws_url=f"ws://localhost:{port}/stream",
            symbols=["BTCUSDT"],
            on_trade=on_trade,
            on_kline=on_kline,
            min_backoff=0.01,
            max_backoff=0.01,
        )
        run_task = asyncio.create_task(client.run())
        try:
            await asyncio.wait_for(connect_event.wait(), timeout=5)
        finally:
            client.stop()
            run_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await run_task

    assert connect_count == 2
    assert trades == [("BTCUSDT", trades[0][1])]
    assert trades[0][1]["trade_id"] == 1


@pytest.mark.asyncio
async def test_client_survives_handler_exception_and_keeps_reconnecting():
    """핸들러(=DB 쓰기 등)에서 터진 예상 밖 예외가 수집을 영구히 멈추면 안 된다.

    이걸 잡지 않으면 백그라운드 태스크만 조용히 죽고 API는 200을 계속
    돌려주는 최악의 장애 모드가 된다.
    """
    connect_count = 0
    second_connect = asyncio.Event()

    async def handler(ws):
        nonlocal connect_count
        connect_count += 1
        if connect_count == 1:
            await ws.send(
                json.dumps(
                    {
                        "data": {
                            "e": "trade",
                            "s": "BTCUSDT",
                            "t": 1,
                            "p": "1",
                            "q": "1",
                            "T": 0,
                            "m": False,
                        }
                    }
                )
            )
            await asyncio.sleep(10)
        else:
            second_connect.set()
            await asyncio.sleep(10)

    async def on_trade(symbol: str, record: dict) -> None:
        raise RuntimeError("simulated DB failure")

    async def on_kline(symbol: str, record: dict) -> None:
        pass

    async with websockets.serve(handler, "localhost", 0) as server:
        port = server.sockets[0].getsockname()[1]
        client = binance_ws.BinanceWebSocketClient(
            ws_url=f"ws://localhost:{port}/stream",
            symbols=["BTCUSDT"],
            on_trade=on_trade,
            on_kline=on_kline,
            min_backoff=0.01,
            max_backoff=0.01,
        )
        run_task = asyncio.create_task(client.run())
        try:
            await asyncio.wait_for(second_connect.wait(), timeout=5)
        finally:
            client.stop()
            run_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await run_task

    assert connect_count == 2


@pytest.mark.asyncio
async def test_client_survives_lifecycle_hook_exception():
    """상태 기록(on_disconnected)이 DB 장애로 터져도 재연결은 계속돼야 한다."""
    connect_count = 0
    second_connect = asyncio.Event()

    async def handler(ws):
        nonlocal connect_count
        connect_count += 1
        if connect_count == 1:
            await ws.close()
        else:
            second_connect.set()
            await asyncio.sleep(10)

    async def on_trade(symbol: str, record: dict) -> None:
        pass

    async def on_kline(symbol: str, record: dict) -> None:
        pass

    async def on_disconnected() -> None:
        raise RuntimeError("simulated DB failure while recording status")

    async with websockets.serve(handler, "localhost", 0) as server:
        port = server.sockets[0].getsockname()[1]
        client = binance_ws.BinanceWebSocketClient(
            ws_url=f"ws://localhost:{port}/stream",
            symbols=["BTCUSDT"],
            on_trade=on_trade,
            on_kline=on_kline,
            on_disconnected=on_disconnected,
            min_backoff=0.01,
            max_backoff=0.01,
        )
        run_task = asyncio.create_task(client.run())
        try:
            await asyncio.wait_for(second_connect.wait(), timeout=5)
        finally:
            client.stop()
            run_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await run_task

    assert connect_count == 2
