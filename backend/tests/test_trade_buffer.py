from app.ingestion.trade_buffer import TradeBuffer


def test_does_not_flush_below_batch_size_and_within_interval():
    buf = TradeBuffer(batch_size=5, flush_interval=10.0)
    buf.add({"trade_id": 1})

    assert buf.should_flush(now=0.0) is False


def test_flushes_when_batch_size_reached():
    buf = TradeBuffer(batch_size=2, flush_interval=10.0)
    buf.add({"trade_id": 1})
    buf.add({"trade_id": 2})

    assert buf.should_flush(now=0.0) is True


def test_flushes_when_interval_elapsed_even_below_batch_size():
    buf = TradeBuffer(batch_size=100, flush_interval=0.5, now=0.0)
    buf.add({"trade_id": 1})

    assert buf.should_flush(now=0.6) is True


def test_empty_buffer_never_needs_flushing():
    buf = TradeBuffer(batch_size=1, flush_interval=0.0, now=0.0)

    assert buf.should_flush(now=1000.0) is False


def test_drain_returns_and_clears_records():
    buf = TradeBuffer(batch_size=5, flush_interval=10.0)
    buf.add({"trade_id": 1})
    buf.add({"trade_id": 2})

    drained = buf.drain(now=0.0)

    assert drained == [{"trade_id": 1}, {"trade_id": 2}]
    assert buf.should_flush(now=0.0) is False


def test_drain_resets_the_flush_interval_clock():
    buf = TradeBuffer(batch_size=100, flush_interval=1.0, now=0.0)
    buf.add({"trade_id": 1})
    buf.drain(now=5.0)

    buf.add({"trade_id": 2})

    assert buf.should_flush(now=5.5) is False
    assert buf.should_flush(now=6.1) is True
