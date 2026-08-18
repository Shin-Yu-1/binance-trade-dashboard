import asyncio

import pytest

from app.api.eventbus import EventBus


@pytest.mark.asyncio
async def test_subscriber_receives_published_event():
    bus = EventBus()
    queue = bus.subscribe()

    bus.publish({"type": "trade", "symbol": "BTCUSDT"})

    event = queue.get_nowait()
    assert event == {"type": "trade", "symbol": "BTCUSDT"}


@pytest.mark.asyncio
async def test_each_subscriber_gets_its_own_copy():
    bus = EventBus()
    queue_a = bus.subscribe()
    queue_b = bus.subscribe()

    bus.publish({"type": "kline"})

    assert queue_a.get_nowait() == {"type": "kline"}
    assert queue_b.get_nowait() == {"type": "kline"}


@pytest.mark.asyncio
async def test_unsubscribed_queue_receives_nothing_further():
    bus = EventBus()
    queue = bus.subscribe()
    bus.unsubscribe(queue)

    bus.publish({"type": "kline"})

    with pytest.raises(asyncio.QueueEmpty):
        queue.get_nowait()


@pytest.mark.asyncio
async def test_publish_with_no_subscribers_does_not_raise():
    bus = EventBus()
    bus.publish({"type": "status"})


@pytest.mark.asyncio
async def test_preserves_publish_order_per_subscriber():
    bus = EventBus()
    queue = bus.subscribe()

    bus.publish(1)
    bus.publish(2)
    bus.publish(3)

    assert [queue.get_nowait() for _ in range(3)] == [1, 2, 3]
