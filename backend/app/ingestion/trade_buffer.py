import time
from typing import Any


class TradeBuffer:
    """Batches trade records so they're flushed to storage by count or by
    elapsed time, whichever comes first — avoids one DB write per trade
    tick while still bounding staleness during quiet periods.
    """

    def __init__(self, batch_size: int, flush_interval: float, now: float | None = None):
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._records: list[dict[str, Any]] = []
        self._last_flush = now if now is not None else time.monotonic()

    def add(self, record: dict[str, Any]) -> None:
        self._records.append(record)

    def should_flush(self, now: float | None = None) -> bool:
        if not self._records:
            return False
        if len(self._records) >= self._batch_size:
            return True
        now = now if now is not None else time.monotonic()
        return (now - self._last_flush) >= self._flush_interval

    def drain(self, now: float | None = None) -> list[dict[str, Any]]:
        records = self._records
        self._records = []
        self._last_flush = now if now is not None else time.monotonic()
        return records
